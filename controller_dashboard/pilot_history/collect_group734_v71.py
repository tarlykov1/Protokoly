"""Manual, read-only Bitrix24 scan and privacy-minimized pilot snapshot.

No task texts, task IDs, user IDs, names, comments or credentials are written.
The only persisted artifact is an aggregate JSON with 0600 permissions.
"""
from __future__ import annotations

import argparse
import asyncio
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from inspect import isawaitable
from typing import Any
from zoneinfo import ZoneInfo

from group734_v71 import GROUP_ID, LIST_ID, atomic_write, validate_snapshot
from roster_probe_v70 import parse_employee_property

PAGE_SIZE = 50
MAX_TASK_PAGES = 40
MAX_LIST_PAGES = 10
EMPLOYEE_PROPERTY = "PROPERTY_306"
MOSCOW = ZoneInfo("Europe/Moscow")
# Never store real corporate logins in public source control.
# Set two explicitly approved technical logins only in the server environment.
TECHNICAL_LOGINS = frozenset(
    name.strip().casefold() for name in os.environ.get("CONTROLLER_PILOT_TECH_LOGINS", "").split(",")
    if name.strip()
)


class CollectionError(ValueError):
    """Safe error; never embeds raw REST responses or employee details."""


def _id(value: Any) -> int | None:
    if isinstance(value, bool) or value is None or not str(value).strip().isdecimal():
        return None
    number = int(value)
    return number if number > 0 else None


def _field(record: dict[str, Any], name: str) -> Any:
    parts = name.lower().split("_")
    camel = parts[0] + "".join(x.title() for x in parts[1:])
    for key in (name, name.lower(), camel):
        if key in record:
            return record[key]
    return None


def _parse_members(value: Any) -> set[int] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise CollectionError("Неверный формат наблюдателей в задачах")
    found = set()
    for item in value:
        if isinstance(item, dict):
            item = _field(item, "USER_ID") or _field(item, "ID")
        number = _id(item)
        if number is None:
            raise CollectionError("Неверная запись наблюдателя в задаче")
        found.add(number)
    return found


def _unwrap(response: Any, *, collection: str) -> tuple[list[dict], int | None, int | None]:
    """Only documented REST envelopes; no fabricated pagination completion."""
    if not isinstance(response, dict) or "error" in response:
        raise CollectionError(f"Не получен исходный REST-ответ {collection}")
    value = response.get("result")
    if collection == "tasks" and isinstance(value, dict):
        value = value.get("tasks")
    if not isinstance(value, list) or len(value) > PAGE_SIZE:
        raise CollectionError(f"Неизвестный формат страницы {collection}")
    if not all(isinstance(item, dict) for item in value):
        raise CollectionError(f"Неизвестный формат записей {collection}")
    nxt = response.get("next")
    total = response.get("total")
    if nxt is not None and (isinstance(nxt, bool) or not str(nxt).isdecimal()):
        raise CollectionError(f"Некорректное продолжение страницы {collection}")
    if total is not None and (isinstance(total, bool) or not str(total).isdecimal()):
        raise CollectionError(f"Некорректное общее число записей {collection}")
    return value, int(nxt) if nxt is not None else None, int(total) if total is not None else None


async def _call(client: Any, method: str, params: dict) -> Any:
    fn = getattr(client, "call", None)
    if not callable(fn):
        raise CollectionError("У клиента Битрикс24 отсутствует метод .call")
    try:
        result = fn(method, params, raw=True)
        return await result if isawaitable(result) else result
    except Exception as exc:
        raise CollectionError(f"REST-запрос {method} завершился ошибкой ({type(exc).__name__})") from None


async def _roster(client: Any) -> tuple[set[int], int]:
    answer = await _call(client, "lists.get.iblock.type.id", {"IBLOCK_ID": LIST_ID})
    if not isinstance(answer, dict) or answer.get("result") != "lists":
        raise CollectionError("Не подтверждён тип списка № 91")
    answer = await _call(client, "lists.field.get", {"IBLOCK_TYPE_ID": "lists", "IBLOCK_ID": LIST_ID})
    props = answer.get("result") if isinstance(answer, dict) else None
    if not isinstance(props, dict):
        raise CollectionError("Не получена схема списка № 91")
    prop = props.get(EMPLOYEE_PROPERTY)
    if not isinstance(prop, dict) or "employee" not in str(prop.get("TYPE", "") + " " + str(prop.get("PROPERTY_USER_TYPE", ""))).casefold():
        raise CollectionError("Поле сотрудников PROPERTY_306 не подтверждено")

    members: set[int] = set()
    seen_items: set[int] = set()
    offset = 0
    for _ in range(MAX_LIST_PAGES):
        answer = await _call(client, "lists.element.get", {
            "IBLOCK_TYPE_ID": "lists", "IBLOCK_ID": LIST_ID,
            "SELECT": ["ID", EMPLOYEE_PROPERTY], "start": offset,
        })
        records, nxt, total = _unwrap(answer, collection="list")
        for record in records:
            element_id = _id(record.get("ID"))
            if element_id is None or element_id in seen_items:
                raise CollectionError("Повтор или отсутствие ID элемента списка")
            seen_items.add(element_id)
            try:
                members.update(parse_employee_property(record.get(EMPLOYEE_PROPERTY)))
            except Exception:
                raise CollectionError("Неоднозначное поле сотрудника в списке № 91") from None
        if total is not None and total < len(seen_items):
            raise CollectionError("Список № 91 вернул противоречивый total")
        if nxt is None:
            if total is not None and len(seen_items) < total:
                raise CollectionError("Список № 91 загружен не полностью")
            if len(records) == PAGE_SIZE and total is None:
                raise CollectionError("Полнота списка № 91 не подтверждена")
            if not members:
                raise CollectionError("В списке № 91 нет сотрудников")
            return members, len(seen_items)
        if nxt != offset + PAGE_SIZE or len(records) != PAGE_SIZE:
            raise CollectionError("Непредвиденная пагинация списка № 91")
        offset = nxt
    raise CollectionError("Превышен лимит страниц списка № 91")


async def _technical_accounts(client: Any, members: set[int]) -> tuple[set[int], bool]:
    """Recognize only exact admin logins shown in the approved list screenshot.

    If user.get cannot identify both, leave the 'nontechnical' count unknown.
    """
    if len(TECHNICAL_LOGINS) != 2:
        return set(), False
    technical: set[int] = set()
    unresolved = False
    for uid in sorted(members):
        try:
            answer = await _call(client, "user.get", {"ID": uid})
            user_list = answer.get("result") if isinstance(answer, dict) else None
            if isinstance(user_list, dict):
                user_list = [user_list]
            if not isinstance(user_list, list) or len(user_list) != 1:
                unresolved = True
                continue
            user = user_list[0]
            if not isinstance(user, dict) or _id(_field(user, "ID")) != uid:
                unresolved = True
                continue
            login = str(_field(user, "LOGIN") or "").strip().casefold()
            if not login:
                unresolved = True
            elif login in TECHNICAL_LOGINS:
                technical.add(uid)
        except CollectionError:
            unresolved = True
    return technical, (not unresolved and len(technical) == len(TECHNICAL_LOGINS))


def _date_moscow(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if len(raw) == 10:
        raw += "T23:59:59"
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        result = datetime.fromisoformat(raw.replace(" ", "T"))
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=MOSCOW)
    return result.astimezone(MOSCOW)


async def collect(client: Any, *, max_pages: int = 20,
                  now: datetime | None = None) -> dict[str, Any]:
    if not 1 <= max_pages <= MAX_TASK_PAGES:
        raise CollectionError("Для одного запуска допускается от 1 до 40 страниц")
    roster, item_count = await _roster(client)
    technical, technical_verified = await _technical_accounts(client, roster)
    human = roster - technical if technical_verified else set()
    time_now = (now or datetime.now(timezone.utc)).astimezone(MOSCOW)  # noqa: UP017

    ids_seen: set[int] = set()
    statuses: Counter[str] = Counter()
    deadlines_present = 0
    no_deadline = 0
    invalid_deadlines = 0
    overdue_open = 0
    due_in_7 = 0
    with_roster = 0
    with_unknown_auditors = 0
    with_nontechnical = 0
    complete = False
    pages_checked = 0
    offset = 0
    for _ in range(max_pages):
        answer = await _call(client, "tasks.task.list", {
            "order": {"ID": "ASC"}, "filter": {"GROUP_ID": GROUP_ID},
            "select": ["ID", "GROUP_ID", "STATUS", "DEADLINE", "AUDITORS"],
            "start": offset,
        })
        records, nxt, total = _unwrap(answer, collection="tasks")
        page_ids: set[int] = set()
        for record in records:
            tid = _id(_field(record, "ID"))
            group = _id(_field(record, "GROUP_ID"))
            if tid is None or group != GROUP_ID or tid in page_ids or tid in ids_seen:
                raise CollectionError("В выборке найден повтор или задача вне группы 734")
            page_ids.add(tid)
            status = _field(record, "STATUS")
            if status is None or str(status) not in {"1", "2", "3", "4", "5", "6", "7"}:
                raise CollectionError("Неизвестный статус задачи – сводка не сохранена")
            statuses[str(status)] += 1
            raw_due = _field(record, "DEADLINE")
            if raw_due is None or not str(raw_due).strip():
                no_deadline += 1
            else:
                deadlines_present += 1
                due = _date_moscow(raw_due)
                if due is None:
                    invalid_deadlines += 1
                elif str(status) != "5":
                    if due < time_now:
                        overdue_open += 1
                    elif due <= time_now + timedelta(days=7):
                        due_in_7 += 1
            auditors = _parse_members(_field(record, "AUDITORS"))
            if auditors is None:
                with_unknown_auditors += 1
            elif auditors & roster:
                with_roster += 1
                if technical_verified and auditors & human:
                    with_nontechnical += 1
        ids_seen.update(page_ids)
        pages_checked += 1
        if total is not None and total < len(ids_seen):
            raise CollectionError("REST вернул противоречивый total задач")
        if nxt is None:
            if total is not None and len(ids_seen) < total:
                raise CollectionError("REST не подтвердил конец списка задач")
            if len(records) == PAGE_SIZE and total is None:
                # With no next, REST v2 convention states this is the last page.
                # An exactly-full final page cannot be distinguished from a
                # truncated response without total, so do not claim completeness.
                complete = False
            else:
                complete = True
            break
        if nxt != offset + PAGE_SIZE or len(records) != PAGE_SIZE:
            raise CollectionError("Постраничный ответ задач неполон или некорректен")
        offset = nxt
    if not ids_seen:
        raise CollectionError("В группе 734 нет доступных задач")
    payload = {
        "schema": 1, "group_id": GROUP_ID, "list_id": LIST_ID,
        "collected_at_utc": time_now.astimezone(timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017
        "pages_checked": pages_checked, "tasks_checked": len(ids_seen),
        "pagination_complete": complete, "list_scan_complete": True,
        "technical_exclusions_verified": technical_verified,
        "status_codes": dict(sorted(statuses.items())),
        "deadlines_present": deadlines_present, "no_deadline": no_deadline,
        "invalid_deadlines": invalid_deadlines,
        "overdue_open_count": overdue_open,
        "due_in_7_days_count": due_in_7,
        "list91_item_count": item_count, "list91_employee_count": len(roster),
        "tasks_with_list91_auditor": with_roster,
        "tasks_with_unknown_auditors": with_unknown_auditors,
        "tasks_with_nontechnical_roster_auditor": with_nontechnical if technical_verified else None,
    }
    validate_snapshot(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Безопасный снимок статусов группы 734")
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--write", action="store_true", help="Явно сохранить обезличенную сводку")
    args = parser.parse_args()
    try:
        from tools.tools import fast_bitrix
        data = asyncio.run(collect(fast_bitrix, max_pages=args.max_pages))
        if args.write:
            atomic_write(data)
        # Show only aggregated data and no user/task IDs.
        import json
        output = validate_snapshot(data)
        output["snapshot_saved"] = args.write
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (CollectionError, ValueError, OSError) as exc:
        import json
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    except Exception as exc:
        import json
        print(json.dumps({"ok": False, "error": "Неожиданная ошибка", "kind": type(exc).__name__},
                         ensure_ascii=False))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
