"""Find a suitable controller pilot group among explicitly supplied candidates.

Queries only sonet_group.user.get for each candidate, read-only; never prints
employee identifiers, names, membership lists, or credentials. This script does
not grant permissions and cannot verify authorization of a particular viewer.
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import sys
from typing import Any

MAX_GROUPS = 10
MAX_CONTROLLERS = 200


class SelectionError(ValueError):
    pass


def parse_ids(value: str, *, label: str, max_count: int) -> list[int]:
    parts = [part.strip() for part in value.split(",")]
    if not parts or any(not part.isdecimal() for part in parts):
        raise SelectionError(f"{label}: ожидается список числовых ID через запятую")
    ids = [int(part) for part in parts]
    if any(i <= 0 for i in ids) or len(ids) > max_count or len(ids) != len(set(ids)):
        raise SelectionError(f"{label}: некорректное количество или повтор ID")
    return ids


def extract_members(payload: Any) -> set[int]:
    """Recognize only a known result envelope or list of participant objects."""
    if isinstance(payload, dict):
        if "error" in payload:
            raise SelectionError("Метод вернул ошибку доступа или параметров")
        if "result" not in payload:
            raise SelectionError("Неизвестный формат ответа участников")
        payload = payload["result"]
    if not isinstance(payload, list):
        raise SelectionError("Неизвестный формат списка участников")
    result = set()
    for entry in payload:
        if not isinstance(entry, dict):
            raise SelectionError("Неизвестный формат записи участника")
        raw = entry.get("USER_ID", entry.get("userId"))
        if isinstance(raw, bool) or not isinstance(raw, (str, int)) or not str(raw).isdecimal():
            raise SelectionError("Неизвестный формат ID участника")
        result.add(int(raw))
    return result


async def check_groups(client: object, groups: list[int], controller_ids: list[int]) -> list[dict]:
    method = getattr(client, "call", None)
    if not callable(method):
        raise SelectionError("Клиент Битрикс24 не поддерживает .call")
    controllers = set(controller_ids)
    results = []
    for group_id in groups:
        try:
            response = method("sonet_group.user.get", {"ID": group_id}, raw=True)
            if inspect.isawaitable(response):
                response = await response
            members = extract_members(response)
            results.append({
                "group_id": group_id,
                "status": "ok",
                "members_count": len(members),
                "controller_matches": len(controllers & members),
                "eligible_for_next_check": bool(controllers & members),
            })
        except Exception:
            # No full exception text: it may include token, URL, group data.
            results.append({
                "group_id": group_id,
                "status": "unavailable",
                "members_count": None,
                "controller_matches": None,
                "eligible_for_next_check": False,
            })
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Поиск группы с участником из списка контролёров")
    parser.add_argument("--groups", required=True, help="До 10 ID кандидатов через запятую")
    args = parser.parse_args()
    try:
        groups = parse_ids(args.groups, label="Группы", max_count=MAX_GROUPS)
        controllers = parse_ids(os.environ.get("CONTROLLER_PILOT_CONTROLLER_IDS", ""),
                                label="Контролёры", max_count=MAX_CONTROLLERS)
        from tools.tools import fast_bitrix
        matches = asyncio.run(check_groups(fast_bitrix, groups, controllers))
        print(json.dumps({
            "ok": True,
            "groups_checked": len(matches),
            "groups_with_controller": sum(row["eligible_for_next_check"] for row in matches),
            "groups": matches,
            "controller_rights_verified": False,
            "task_participation_verified": False,
            "data_saved": False,
            "note": "Совпадение по членству в группе – только первый шаг. Требуется проверка задач и реальных ACL.",
        }, ensure_ascii=False, indent=2))
        return 0
    except SelectionError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps({"ok": False, "error": "Ошибка запуска проверки",
                          "kind": type(exc).__name__}, ensure_ascii=False), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
