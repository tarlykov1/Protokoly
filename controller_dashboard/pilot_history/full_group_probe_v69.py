"""Read-only, bounded pagination of Bitrix24 REST v2 tasks.task.list.

This is a server-side diagnostic, not a controller-facing API. It never stores
task rows, returns personal fields, or treats the result as verified controller ACL.
The caller must use fast_bitrix.call(..., raw=True) to preserve REST 'next'.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from collections.abc import Awaitable, Callable
from typing import Any

from live_probe_v68 import MAX_PAGE, SELECT, ProbeError, _id, _rows, _value

TaskCall = Callable[[str, dict[str, Any]], Awaitable[Any]]
MAX_PAGES = 10


def _next_start(payload: Any, current_start: int) -> int | None:
    if not isinstance(payload, dict):
        raise ProbeError("Для постраничного чтения нужен исходный REST-ответ с next")
    if "error" in payload:
        raise ProbeError("REST вернул признак ошибки без раскрытия содержимого")
    nxt = payload.get("next")
    if nxt is None:
        return None
    if isinstance(nxt, bool) or not isinstance(nxt, (int, str)):
        raise ProbeError("Некорректный тип указателя следующей страницы")
    try:
        offset = int(nxt)
    except ValueError:
        raise ProbeError("Некорректное смещение следующей страницы") from None
    if offset != current_start + MAX_PAGE:
        raise ProbeError("Неожиданное смещение страницы: обработка остановлена")
    return offset


async def probe_full_group(
    call: TaskCall,
    *,
    group_id: int,
    allowed_groups: frozenset[int],
    max_pages: int = MAX_PAGES,
) -> dict[str, Any]:
    if isinstance(group_id, bool) or not isinstance(group_id, int) or group_id <= 0 or group_id not in allowed_groups:
        raise ProbeError("Группа не входит в явно разрешённый список для проверки")
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or not 1 <= max_pages <= MAX_PAGES:
        raise ProbeError("Максимум страниц должен быть от 1 до 10")

    seen: set[int] = set()
    status_codes: Counter[str] = Counter()
    deadlines_present = 0
    missing_status = 0
    offset = 0
    pages_checked = 0
    complete = False
    next_offset: int | None = None

    for _ in range(max_pages):
        params = {
            "filter": {"GROUP_ID": group_id},
            "select": list(SELECT),
            "order": {"ID": "ASC"},
            "start": offset,
        }
        try:
            response = await call("tasks.task.list", params)
        except Exception as exc:
            raise ProbeError(
                f"Ошибка REST на странице {pages_checked + 1} ({type(exc).__name__}); "
                "полная сводка не подтверждена"
            ) from None

        rows = _rows(response)
        if len(rows) > MAX_PAGE:
            raise ProbeError("Ответ превышает 50 записей – диагностика остановлена")
        page_ids: set[int] = set()
        page_counts: Counter[str] = Counter()
        page_deadlines = 0
        page_missing_status = 0
        for item in rows:
            task_id = _id(_value(item, "ID"))
            actual_group = _id(_value(item, "GROUP_ID"))
            if task_id is None or actual_group != group_id:
                raise ProbeError("В ответе обнаружена задача без ID или вне разрешённой группы")
            if task_id in seen or task_id in page_ids:
                raise ProbeError("Повторяющиеся задачи при пагинации; результаты не учитываются")
            page_ids.add(task_id)
            code = _value(item, "STATUS")
            if code is None or str(code).strip() == "":
                page_missing_status += 1
            else:
                page_counts[str(code)] += 1
            if _value(item, "DEADLINE"):
                page_deadlines += 1

        nxt = _next_start(response, offset)
        if nxt is not None and len(rows) != MAX_PAGE:
            raise ProbeError("REST сообщил next при неполной странице; остановлено")

        seen.update(page_ids)
        status_codes.update(page_counts)
        missing_status += page_missing_status
        deadlines_present += page_deadlines
        pages_checked += 1
        next_offset = nxt

        if nxt is None:
            complete = True
            break
        offset = nxt

    return {
        "ok": True,
        "group_id": group_id,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017 – deployed on Python 3.10
        "source": "tasks.task.list / REST v2 / raw=True",
        "pages_checked": pages_checked,
        "tasks_checked": len(seen),
        "pagination_complete": complete,
        "limit_reached": not complete,
        "next_start": next_offset if not complete else None,
        "status_codes": dict(sorted(status_codes.items())),
        "missing_status": missing_status,
        "deadlines_present": deadlines_present,
        "kpi_calculated": False,
        "acl_verified_for_controller": False,
        "data_saved": False,
        "notice": (
            "Сведения только по группе, доступной интеграционной учётной записи. "
            "Исключённые/неактуальные поручения и права контролёра не проверены. "
            "Если pagination_complete=false, это неполная выборка."
        ),
    }
