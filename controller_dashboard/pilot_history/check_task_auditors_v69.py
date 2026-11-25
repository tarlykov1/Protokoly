"""Read-only check of observers for one explicitly chosen Bitrix24 task.

Does not print users, task titles, text, credentials, or raw REST errors.
This checks AUDITORS membership, NOT viewer permissions or controller activity.
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import sys
from typing import Any


class AuditorCheckError(ValueError):
    pass


def positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str) and not value.strip().isdecimal():
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def field(row: dict, name: str):
    camel = name.lower().split("_")
    alias = camel[0] + "".join(x.title() for x in camel[1:])
    for key in (name, name.lower(), alias):
        if key in row:
            return True, row[key]
    return False, None


def unwrap_task(payload: Any) -> dict:
    value = payload
    for _ in range(4):
        if not isinstance(value, dict):
            raise AuditorCheckError("Неизвестная структура ответа задачи")
        if "error" in value:
            raise AuditorCheckError("REST вернул ошибку (текст скрыт)")
        if "result" in value:
            value = value["result"]
        elif "task" in value:
            value = value["task"]
        elif "data" in value:
            value = value["data"]
        else:
            if field(value, "ID")[0]:
                return value
            raise AuditorCheckError("Не найден объект задачи в ответе")
    if not isinstance(value, dict) or not field(value, "ID")[0]:
        raise AuditorCheckError("Не найден объект задачи в ответе")
    return value


def parse_auditors(raw: Any) -> set[int]:
    if not isinstance(raw, list):
        raise AuditorCheckError("Неверный формат наблюдателей")
    ids = set()
    for entry in raw:
        if isinstance(entry, dict):
            record = entry
            found, entry = field(record, "ID")
            if not found:
                found, entry = field(record, "USER_ID")
            if not found:
                raise AuditorCheckError("Неизвестный формат записи наблюдателя")
        uid = positive_int(entry)
        if uid is None:
            raise AuditorCheckError("Некорректный ID наблюдателя")
        ids.add(uid)
    return ids


def parse_roster(raw: str) -> set[int] | None:
    raw = raw.strip()
    if not raw:
        return None
    parts = [part.strip() for part in raw.split(",")]
    if not 1 <= len(parts) <= 200 or len(parts) != len(set(parts)):
        raise AuditorCheckError("Некорректный список контролёров")
    roster = set()
    for part in parts:
        n = positive_int(part)
        if n is None:
            raise AuditorCheckError("Некорректный список контролёров")
        roster.add(n)
    return roster


def summarize(payload: Any, *, task_id: int, group_id: int, roster: set[int] | None) -> dict:
    task = unwrap_task(payload)
    _, actual_id = field(task, "ID")
    group_found, actual_group = field(task, "GROUP_ID")
    if positive_int(actual_id) != task_id:
        raise AuditorCheckError("Ответ не соответствует запрошенной задаче")
    if not group_found or positive_int(actual_group) != group_id:
        raise AuditorCheckError("Принадлежность задачи запрошенной группе не подтверждена")
    has_auditors, raw = field(task, "AUDITORS")
    auditors = parse_auditors(raw) if has_auditors else None
    return {
        "ok": True,
        "task_id": task_id,
        "group_id": group_id,
        "group_verified": True,
        "auditors_field_present": has_auditors,
        "auditors_count": len(auditors) if auditors is not None else None,
        "controller_roster_provided": roster is not None,
        "controller_matches": len(auditors & roster) if auditors is not None and roster is not None else None,
        "controller_present_in_auditors": bool(auditors & roster) if auditors is not None and roster is not None else None,
        "acl_verified_for_controller": False,
        "data_saved": False,
        "notice": "Это только сверка наблюдателей со списком. Доступ контролёра и его действия не проверены.",
    }


async def check(client: Any, *, task_id: int, group_id: int, roster: set[int] | None) -> dict:
    method = getattr(client, "call", None)
    if not callable(method):
        raise AuditorCheckError("Клиент Битрикс24 не поддерживает .call")
    params = {"taskId": task_id, "select": ["ID", "GROUP_ID", "AUDITORS"]}
    try:
        answer = method("tasks.task.get", params, raw=True)
        if inspect.isawaitable(answer):
            answer = await answer
    except Exception as exc:
        raise AuditorCheckError(f"Ошибка чтения задачи ({type(exc).__name__}); подробности скрыты") from None
    return summarize(answer, task_id=task_id, group_id=group_id, roster=roster)


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка наблюдателей одной задачи без вывода персональных данных")
    parser.add_argument("--task-id", type=int, required=True)
    parser.add_argument("--group-id", type=int, required=True)
    args = parser.parse_args()
    try:
        if positive_int(args.task_id) is None or positive_int(args.group_id) is None:
            raise AuditorCheckError("ID задачи и группы должны быть положительными")
        allowed = positive_int(os.environ.get("CONTROLLER_PILOT_ALLOWED_GROUP"))
        if allowed != args.group_id:
            raise AuditorCheckError("Группа не включена в список разрешённых для проверки")
        roster = parse_roster(os.environ.get("CONTROLLER_PILOT_CONTROLLER_IDS", ""))
        from tools.tools import fast_bitrix
        result = asyncio.run(check(fast_bitrix, task_id=args.task_id, group_id=args.group_id, roster=roster))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except AuditorCheckError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps({"ok": False, "error": "Ошибка запуска", "kind": type(exc).__name__}, ensure_ascii=False), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
