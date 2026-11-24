"""Read-only inspection of a Bitrix24 controller roster and one task.

Looks only at an explicitly supplied universal list and task. Never exports
employee IDs, names, task content, credentials, or the raw REST response.
No writes, FastAPI integration, or service restart.
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
from typing import Any

PAGE_SIZE = 50
MAX_PAGES = 10


class ProbeError(RuntimeError):
    """Safe diagnostic error (no raw API details)."""


def positive_id(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str) and not value.strip().isdecimal():
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def unwrap(response: Any) -> Any:
    if isinstance(response, dict):
        if "error" in response:
            raise ProbeError("REST вернул признак ошибки (содержание скрыто)")
        if "result" in response:
            return response["result"]
    return response


def get_key(record: dict, name: str) -> Any:
    camel = name.lower().split("_")
    alias = camel[0] + "".join(piece.title() for piece in camel[1:])
    for key in (name, name.lower(), alias):
        if key in record:
            return record[key]
    return None


def user_fields(payload: Any) -> list[dict[str, Any]]:
    data = unwrap(payload)
    if not isinstance(data, dict):
        raise ProbeError("Структура полей списка не распознана")
    fields = []
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        fid = str(value.get("FIELD_ID") or key)
        if not fid.startswith("PROPERTY_") or not fid[9:].isdigit():
            continue
        dtype = str(value.get("TYPE") or "")
        usertype = str(value.get("PROPERTY_USER_TYPE") or "")
        usertype_settings = value.get("USER_TYPE_SETTINGS")
        kind = (dtype + " " + usertype).lower()
        is_employee = "employee" in kind or "userid" in kind
        # Expose only schema, never user data or value dictionaries.
        fields.append({
            "field_id": fid,
            "label": str(value.get("NAME") or "")[:100],
            "type": dtype[:40],
            "is_employee_binding": is_employee,
        })
    return sorted(fields, key=lambda entry: entry["field_id"])


def parse_employee_property(value: Any) -> set[int]:
    if value is None or value == "":
        return set()
    if not isinstance(value, dict):
        raise ProbeError("Неподтверждённый формат свойства сотрудника")
    result = set()
    for raw in value.values():
        person = positive_id(raw)
        if person is None:
            raise ProbeError("Нечисловое значение поля сотрудника")
        result.add(person)
    return result


def task_auditors(response: Any, *, expected_task: int, expected_group: int) -> set[int]:
    data = unwrap(response)
    if isinstance(data, dict) and "task" in data:
        data = data["task"]
    if not isinstance(data, dict):
        raise ProbeError("Задача не найдена в ответе")
    task_id = positive_id(get_key(data, "ID"))
    group_id = positive_id(get_key(data, "GROUP_ID"))
    if task_id != expected_task or group_id != expected_group:
        raise ProbeError("ID задачи или группа не совпадает с заданными")
    raw = get_key(data, "AUDITORS")
    if not isinstance(raw, list):
        raise ProbeError("Наблюдатели задачи не возвращены как список")
    result = set()
    for item in raw:
        if isinstance(item, dict):
            item = get_key(item, "USER_ID") or get_key(item, "ID")
        uid = positive_id(item)
        if uid is None:
            raise ProbeError("Неизвестный формат наблюдателя")
        result.add(uid)
    return result


async def invoke(client: Any, name: str, params: dict) -> Any:
    fn = getattr(client, "call", None)
    if not callable(fn):
        raise ProbeError("Клиент Битрикс24 не поддерживает .call")
    try:
        result = fn(name, params, raw=True)
        return await result if inspect.isawaitable(result) else result
    except Exception as exc:
        # Deliberately never display full response/URL/credentials or exception text.
        raise ProbeError(f"Ошибка метода {name} ({type(exc).__name__})") from None


async def probe(client: Any, *, list_id: int, task_id: int, group_id: int,
                field_id: str | None = None) -> dict[str, Any]:
    if not all(positive_id(v) == v for v in (list_id, task_id, group_id)):
        raise ProbeError("Неправильные ID списка, задачи или группы")
    list_type = unwrap(await invoke(client, "lists.get.iblock.type.id", {"IBLOCK_ID": list_id}))
    if not isinstance(list_type, str) or list_type not in ("lists", "bitrix_processes", "lists_socnet"):
        raise ProbeError("Не удалось подтвердить тип универсального списка")
    if list_type == "lists_socnet":
        raise ProbeError("Списки групп требуют SOCNET_GROUP_ID; проверка остановлена")

    fields = user_fields(await invoke(client, "lists.field.get", {
        "IBLOCK_TYPE_ID": list_type, "IBLOCK_ID": list_id,
    }))
    employees = [f for f in fields if f["is_employee_binding"]]
    base = {
        "list_id": list_id, "list_type": list_type,
        "schema_fields": fields,
        "candidate_employee_fields": len(employees),
        "task_id": task_id, "group_id": group_id,
        "data_saved": False, "acl_verified_for_controller": False,
    }
    if field_id is not None:
        if not any(f["field_id"] == field_id and f["is_employee_binding"] for f in employees):
            raise ProbeError("Указанное поле не подтверждено как привязка к сотруднику")
        selected = field_id
    elif len(employees) == 1:
        selected = employees[0]["field_id"]
    else:
        return {
            **base, "ok": True, "status": "needs_field_selection",
            "matched_controller_count": None,
            "note": "Укажите однозначное поле привязки к сотруднику через --employee-field; данные сотрудников не запрашивались",
        }

    auditor_ids = task_auditors(await invoke(client, "tasks.task.get", {
        "taskId": task_id, "select": ["ID", "GROUP_ID", "AUDITORS"],
    }), expected_task=task_id, expected_group=group_id)

    employee_ids: set[int] = set()
    total_read = 0
    complete = False
    for page in range(MAX_PAGES):
        params = {"IBLOCK_TYPE_ID": list_type, "IBLOCK_ID": list_id,
                  "SELECT": ["ID", selected], "start": page * PAGE_SIZE}
        payload = await invoke(client, "lists.element.get", params)
        records = unwrap(payload)
        if not isinstance(records, list) or len(records) > PAGE_SIZE or not all(isinstance(v, dict) for v in records):
            raise ProbeError("Невозможно проверить постраничный ответ списка")
        for entry in records:
            if positive_id(entry.get("ID")) is None:
                raise ProbeError("Элемент списка без ID")
            employee_ids.update(parse_employee_property(entry.get(selected)))
        total_read += len(records)
        declared_total = None
        if isinstance(payload, dict) and "total" in payload:
            declared_total = positive_id(payload["total"])
            if declared_total is None and payload["total"] not in (0, "0"):
                raise ProbeError("Неизвестный формат общего количества элементов")
            if declared_total is not None and declared_total < total_read:
                raise ProbeError("Число элементов не совпадает с итогом REST")
        if len(records) < PAGE_SIZE:
            if declared_total is not None and declared_total != total_read:
                raise ProbeError("REST вернул неполную страницу при большем total")
            complete = True
            break
        if declared_total is not None and declared_total == total_read:
            complete = True
            break
    matches = len(auditor_ids & employee_ids)
    return {
        **base, "ok": True, "status": "checked" if complete else "partial",
        "selected_employee_field": selected,
        "list_items_read": total_read, "list_scan_complete": complete,
        "controllers_found_in_list": len(employee_ids),
        "task_auditors_count": len(auditor_ids),
        "matched_controller_count": matches,
        "controller_in_task": (matches > 0 if matches or complete else None),
        "note": "Совпадение с наблюдателем – не доказательство прав в кабинете или реакции контролёра",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка списка контролёров и одной задачи, без персональных данных")
    parser.add_argument("--list-id", type=int, required=True)
    parser.add_argument("--group-id", type=int, required=True)
    parser.add_argument("--task-id", type=int, required=True)
    parser.add_argument("--employee-field", default=None)
    args = parser.parse_args()
    try:
        from tools.tools import fast_bitrix
        result = asyncio.run(probe(fast_bitrix, list_id=args.list_id,
                                   task_id=args.task_id, group_id=args.group_id,
                                   field_id=args.employee_field))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ProbeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps({"ok": False, "error": "Ошибка диагностики", "kind": type(exc).__name__},
                         ensure_ascii=False), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
