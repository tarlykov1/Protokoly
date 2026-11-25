"""Read only a minimized pilot aggregate for workgroup 734.

Never fetch corporate tasks inside an HTTP request.  The snapshot is created
explicitly by a local CLI and contains no task, employee or comment records.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

GROUP_ID = 734
LIST_ID = 91
SCHEMA = 1
FILE_NAME = "group734_summary_v71.json"
MAX_FILE_BYTES = 20000


class SnapshotError(ValueError):
    """Safe, non-sensitive failure shown to pilot viewers."""


def snapshot_path() -> Path:
    root = Path(__file__).resolve().parent / "data"
    return root / FILE_NAME


def _is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def validate_snapshot(data: Any) -> dict[str, Any]:
    """Explicit allowlist; unexpected fields never enter API output."""
    if not isinstance(data, dict):
        raise SnapshotError("Некорректный формат сводки группы")
    if data.get("schema") != SCHEMA or data.get("group_id") != GROUP_ID or data.get("list_id") != LIST_ID:
        raise SnapshotError("Сводка не соответствует версии или разрешённой группе")
    count_fields = (
        "pages_checked", "tasks_checked", "deadlines_present", "no_deadline",
        "invalid_deadlines", "overdue_open_count", "due_in_7_days_count",
        "list91_employee_count", "list91_item_count", "tasks_with_list91_auditor",
        "tasks_with_unknown_auditors", "tasks_with_nontechnical_roster_auditor",
    )
    for key in count_fields:
        if key == "tasks_with_nontechnical_roster_auditor" and data.get(key) is None:
            continue
        if not _is_nonnegative_int(data.get(key)):
            raise SnapshotError("Некорректные значения сводки группы")
    flags = ("pagination_complete", "list_scan_complete", "technical_exclusions_verified")
    if any(not isinstance(data.get(key), bool) for key in flags):
        raise SnapshotError("Не подтверждена полнота источников")
    if not isinstance(data.get("collected_at_utc"), str) or len(data["collected_at_utc"]) > 42:
        raise SnapshotError("Не указана дата получения данных")
    statuses = data.get("status_codes")
    if not isinstance(statuses, dict) or len(statuses) > 20:
        raise SnapshotError("Некорректные коды статусов")
    if not all(isinstance(k, str) and k.isdecimal() and _is_nonnegative_int(v)
               for k, v in statuses.items()):
        raise SnapshotError("Некорректные коды статусов")
    total = data["tasks_checked"]
    if sum(statuses.values()) != total:
        raise SnapshotError("Количество задач и статусов не совпадает")
    if (data["deadlines_present"] + data["no_deadline"] != total
            or data["overdue_open_count"] > total
            or data["due_in_7_days_count"] > total
            or data["tasks_with_list91_auditor"] > total
            or data["tasks_with_unknown_auditors"] > total):
        raise SnapshotError("Неконсистентная сводка")
    if data["tasks_with_nontechnical_roster_auditor"] is not None:
        if not data["technical_exclusions_verified"]:
            raise SnapshotError("Исключение технических записей не подтверждено")
        if data["tasks_with_nontechnical_roster_auditor"] > data["tasks_with_list91_auditor"]:
            raise SnapshotError("Неверный подсчёт контролёров")
    safe = {key: data[key] for key in (
        "schema", "group_id", "list_id", "collected_at_utc",
        *count_fields, *flags, "status_codes",
    )}
    safe.update({
        "ok": True,
        "source": "Локальная обезличенная проверка REST v2 / группа 734",
        "kpi_calculated": False,
        "controller_acl_verified": False,
        "historical_weekly_dynamics_available": False,
        "notice": (
            "ИД не рассчитывается: не подтверждён признак неактуальности и права контролёра. "
            "Совпадение наблюдателя со списком № 91 не доказывает его полномочия. "
            "Срез обновляется только вручную на сервере."
        ),
    })
    return safe


def read_snapshot(path: Path | None = None) -> dict[str, Any]:
    target = path or snapshot_path()
    try:
        if target.is_symlink() or not target.is_file() or target.stat().st_size > MAX_FILE_BYTES:
            raise SnapshotError("Сводка группы ещё не загружена или недоступна")
        with target.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
        return validate_snapshot(data)
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise SnapshotError("Не удалось прочитать тестовую сводку") from exc


def atomic_write(data: dict[str, Any], path: Path | None = None) -> Path:
    """Replace a snapshot atomically, with 0600 permissions and no task rows."""
    from tempfile import mkstemp

    target = path or snapshot_path()
    if target.is_symlink() or not target.parent.is_dir() or target.parent.is_symlink():
        raise SnapshotError("Каталог отдельной тестовой сводки недоступен")
    validated = validate_snapshot(data)
    payload = {key: data[key] for key in data if key in (
        "schema", "group_id", "list_id", "collected_at_utc",
        "pages_checked", "tasks_checked", "deadlines_present", "no_deadline",
        "invalid_deadlines", "overdue_open_count", "due_in_7_days_count",
        "list91_employee_count", "list91_item_count", "tasks_with_list91_auditor",
        "tasks_with_unknown_auditors", "tasks_with_nontechnical_roster_auditor",
        "pagination_complete", "list_scan_complete", "technical_exclusions_verified", "status_codes",
    )}
    del validated
    fd, temp_name = mkstemp(prefix=".group734_", suffix=".tmp", dir=str(target.parent))
    temp = Path(temp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)
        return target
    finally:
        if temp.exists():
            temp.unlink()
