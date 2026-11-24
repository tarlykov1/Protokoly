"""Timeline v6.6: read-only pilot history plus separate opt-in comment snapshots.

The original pilot_history_events remains read-only. Only a separate archive DB
is created upon explicit POST. Both old forum and new task chat APIs remain.
"""
from __future__ import annotations

import asyncio
import hmac
import inspect
import json
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import FileResponse

router = APIRouter(prefix="/controller-pilot-test", tags=["controller-pilot-timeline-v6"])

ROOT = Path(__file__).resolve().parent
# The script is intended to be copied into /webapp/app/controller_dashboard_test/.
DEFAULT_DB = ROOT / "data" / "pilot.sqlite"
TABLE = "pilot_history_events"
ALLOWED_JSON_KEYS = (
    "value_json", "payload_json", "details_json", "data_json", "raw_json",
    "value", "payload", "details", "data",
)
HIDDEN_NAME_RE = re.compile(r"(password|passwd|secret|access.?token|refresh.?token|authorization|api.?key|webhook)", re.I)


def _authorize(authorization: str | None) -> None:
    expected = os.getenv("CONTROLLER_PILOT_TOKEN", "")
    # Fail closed: never allow the endpoint if the token is not configured.
    if not expected:
        raise HTTPException(503, "CONTROLLER_PILOT_TOKEN не настроен в окружении сервиса")
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise HTTPException(401, "Требуется токен Bearer", headers={"WWW-Authenticate": "Bearer"})
    received = authorization[len(prefix):].strip()
    if not hmac.compare_digest(received, expected):
        raise HTTPException(403, "Неверный токен")


def _db_path() -> Path:
    return Path(os.getenv("CONTROLLER_PILOT_DB_PATH", str(DEFAULT_DB))).resolve()


def _connect() -> sqlite3.Connection:
    db = _db_path()
    if not db.is_file():
        raise HTTPException(503, "База истории поручений не найдена")
    # Read-only URI prevents accidental writes to the live pilot database.
    uri = f"file:{quote(str(db), safe='/')}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA busy_timeout=2000")
        return conn
    except sqlite3.Error:
        raise HTTPException(503, "Не удалось открыть базу истории в режиме чтения") from None


def _identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _fields(conn: sqlite3.Connection) -> list[str]:
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone()
    if not exists:
        raise HTTPException(503, "В базе отсутствует таблица pilot_history_events")
    return [x[1] for x in conn.execute(f"PRAGMA table_info({_identifier(TABLE)})")]


def _column(fields: list[str], *candidates: str) -> str | None:
    lookup = {f.lower(): f for f in fields}
    for name in candidates:
        if name.lower() in lookup:
            return lookup[name.lower()]
    return None


def _deep_filter(value: Any, depth: int = 0) -> Any:
    """Minimize accidental disclosure of integration credentials in raw payloads."""
    if depth > 6:
        return "[вложенные данные скрыты]"
    if isinstance(value, dict):
        return {str(k): _deep_filter(v, depth + 1) for k, v in value.items()
                if not HIDDEN_NAME_RE.search(str(k))}
    if isinstance(value, list):
        return [_deep_filter(x, depth + 1) for x in value[:100]]
    if isinstance(value, str):
        return value[:10000] + ("…" if len(value) > 10000 else "")
    return value if value is None or isinstance(value, (bool, int, float)) else str(value)


def _parse(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


def _get(mapping: dict[str, Any], *names: str) -> Any:
    if not isinstance(mapping, dict):
        return None
    lookup = {str(k).casefold(): v for k, v in mapping.items()}
    for name in names:
        value = lookup.get(name.casefold())
        if value is not None and value != "":
            return value
    return None


def _change_from_payload(payload: Any) -> tuple[Any, Any]:
    """Only report values actually present; never synthesize a change."""
    candidates = []
    if isinstance(payload, dict):
        candidates.append(payload)
        for name in ("changes", "change", "event", "data", "details", "history", "value"):
            child = _get(payload, name)
            if isinstance(child, dict):
                candidates.append(child)
    for obj in candidates:
        old = _get(obj, "old_value", "oldValue", "old", "from", "value_from", "previous_value", "previous", "prev")
        new = _get(obj, "new_value", "newValue", "new", "to", "value_to", "current_value", "current")
        if old is not None or new is not None:
            return old, new
    return None, None


def _event(row: sqlite3.Row, fields: list[str]) -> dict[str, Any]:
    data = dict(row)
    fld = _column(fields, "field", "field_name", "event_type", "type", "code")
    ts = _column(fields, "occurred_at", "event_date", "created_at", "date", "timestamp")
    actor = _column(fields, "actor_id", "author_id", "user_id", "created_by")
    eid = _column(fields, "event_id", "history_id", "id", "event_key")
    payload = None
    for name in ALLOWED_JSON_KEYS:
        col = _column(fields, name)
        if col and data.get(col) is not None:
            payload = _parse(data[col])
            break
    if payload is None:
        # If no payload field is known, represent only non-internal extra columns.
        reserved = set(filter(None, (fld, ts, actor, eid, _column(fields, "task_id", "taskid", "task"))))
        payload = {k: _parse(v) for k, v in data.items() if k not in reserved}
    payload = _deep_filter(payload)
    old, new = _change_from_payload(payload)
    # Some deployments store change values in separate columns.
    if old is None:
        old = _get(data, "old_value", "oldValue", "old")
    if new is None:
        new = _get(data, "new_value", "newValue", "new")
    event_type = str(data.get(fld) or _get(payload, "field", "type", "event_type") or "OTHER")
    actor_id = data.get(actor) if actor else _get(payload, "actor_id", "author_id", "user_id")
    occurred_at = str(data.get(ts) or _get(payload, "occurred_at", "created_at", "date") or "")
    return {
        "id": str(data.get(eid) if eid else ""),
        "field": event_type,
        "occurred_at": occurred_at,
        "actor_id": actor_id,
        "old_value": _deep_filter(old),
        "new_value": _deep_filter(new),
        "details": payload,
    }


def _fetch(task_id: int, limit: int, offset: int) -> tuple[int, list[dict[str, Any]], list[str]]:
    conn = _connect()
    try:
        fields = _fields(conn)
        key = _column(fields, "task_id", "taskid", "task")
        if not key:
            raise HTTPException(503, "В истории отсутствует поле ID задачи")
        ts = _column(fields, "occurred_at", "event_date", "created_at", "date", "timestamp")
        eid = _column(fields, "event_id", "history_id", "id", "event_key")
        order_cols = [f"{_identifier(ts)} DESC"] if ts else []
        if eid and eid != ts:
            order_cols.append(f"{_identifier(eid)} DESC")
        order = " ORDER BY " + ", ".join(order_cols) if order_cols else ""
        count = conn.execute(
            f"SELECT COUNT(*) FROM {_identifier(TABLE)} WHERE {_identifier(key)} = ?", (task_id,)
        ).fetchone()[0]
        # All interpolated column names come only from schema introspection; values are bound.
        rows = conn.execute(
            f"SELECT * FROM {_identifier(TABLE)} WHERE {_identifier(key)} = ?{order} LIMIT ? OFFSET ?",
            (task_id, limit, offset),
        ).fetchall()
        return count, [_event(row, fields) for row in rows], fields
    except sqlite3.Error as exc:
        raise HTTPException(503, "Ошибка чтения истории; проверьте структуру базы") from exc
    finally:
        conn.close()


@router.get("/history/{task_id}/events")
def timeline_events(
    task_id: int,
    authorization: str | None = Header(default=None),
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    _authorize(authorization)
    if task_id <= 0:
        raise HTTPException(422, "ID задачи должен быть положительным")
    total, events, fields = _fetch(task_id, limit, offset)
    return {
        "ok": True, "task_id": task_id, "total": total,
        "returned": len(events), "limit": limit, "offset": offset,
        "events": events,
        "has_more": offset + len(events) < total,
        "notice": "Хронология включает только события, фактически сохранённые при синхронизации.",
    }


@router.get("/history/{task_id}/diagnostics")
def timeline_diagnostics(task_id: int, authorization: str | None = Header(default=None)):
    _authorize(authorization)
    if task_id <= 0:
        raise HTTPException(422, "ID задачи должен быть положительным")
    # Check entire set (up to 1000) without publishing confidential content.
    total, events, fields = _fetch(task_id, 1000, 0)
    return {
        "ok": True, "task_id": task_id, "total": total,
        "sampled": len(events), "columns": fields,
        "by_field": dict(Counter(e["field"] for e in events)),
        "with_actor": sum(e["actor_id"] not in (None, "") for e in events),
        "with_timestamp": sum(bool(e["occurred_at"]) for e in events),
        "with_old_new": sum(e["old_value"] is not None or e["new_value"] is not None for e in events),
        "partial": total > len(events),
    }


# Optional, on-demand people lookup. No credentials or names are stored.
# The same Bitrix adapter already used by /webapp/app/main.py is reused.
def _ids_in_value(value: Any) -> set[int]:
    """Return only explicit numeric user IDs; never interpret comment IDs as people."""
    if isinstance(value, bool):
        return set()
    if isinstance(value, int):
        return {value} if 0 < value < 1_000_000_000 else set()
    if isinstance(value, str) and re.fullmatch(r"[0-9,;\s]+", value.strip()):
        return {int(v) for v in re.split(r"[,;\s]+", value.strip()) if v and int(v) > 0}
    if isinstance(value, (tuple, list)):
        result: set[int] = set()
        for v in value[:100]:
            result.update(_ids_in_value(v))
        return result
    return set()


def _relevant_people(events: list[dict[str, Any]]) -> list[int]:
    result: set[int] = set()
    person_fields = {"AUDITORS", "ACCOMPLICES", "RESPONSIBLE_ID", "CREATED_BY"}
    for e in events:
        result.update(_ids_in_value(e.get("actor_id")))
        if str(e.get("field", "")).upper() in person_fields:
            result.update(_ids_in_value(e.get("old_value")))
            result.update(_ids_in_value(e.get("new_value")))
    return sorted(result)


def _one_user(response: Any, expected_id: int) -> str | None:
    """Extract a verified Bitrix user, never mismatch it with the requested ID."""
    if isinstance(response, dict) and "result" in response:
        response = response["result"]
    if isinstance(response, dict) and "users" in response:
        response = response["users"]
    if isinstance(response, dict) and "items" in response:
        response = response["items"]
    if isinstance(response, dict):
        response = [response]
    if not isinstance(response, list):
        return None
    for user in response:
        if not isinstance(user, dict):
            continue
        try:
            uid = int(user.get("ID") or user.get("id") or 0)
        except (ValueError, TypeError):
            continue
        if uid != expected_id:
            continue
        name = " ".join(str(user.get(part) or "").strip() for part in ("LAST_NAME", "NAME", "SECOND_NAME")).strip()
        name = " ".join(name.split())
        if name:
            # Keep only moderate-length plain text; frontend uses textContent.
            return name[:200]
    return None


@router.get("/history/{task_id}/people")
async def timeline_people(task_id: int, authorization: str | None = Header(default=None)):
    """Read-only and opt-in: resolve only real user IDs present in the saved task history."""
    _authorize(authorization)
    if task_id <= 0:
        raise HTTPException(422, "ID задачи должен быть положительным")
    total, events, _ = await asyncio.to_thread(_fetch, task_id, 1000, 0)
    ids = _relevant_people(events)
    if len(ids) > 60:
        raise HTTPException(422, "Слишком много участников; требуется ограничить запрос")
    if not ids:
        return {"ok": True, "task_id": task_id, "names": {}, "resolved": 0, "requested": 0}
    try:
        from tools.tools import fast_bitrix
        method = getattr(fast_bitrix, "call", None)
        if not callable(method):
            raise AttributeError("call")
    except (ImportError, AttributeError):
        raise HTTPException(503, "Адаптер Битрикс24 не поддерживает user.get через call; история остаётся доступна") from None

    # Cap parallelism to avoid heavy load on the corporate REST gateway.
    semaphore = asyncio.Semaphore(3)
    async def resolve(uid: int) -> tuple[int, str | None]:
        async with semaphore:
            try:
                call_result = method("user.get", {"ID": uid})
                if inspect.isawaitable(call_result):
                    call_result = await asyncio.wait_for(call_result, timeout=7)
                return uid, _one_user(call_result, uid)
            except Exception:
                return uid, None

    pairs = await asyncio.gather(*(resolve(uid) for uid in ids))
    names = {str(uid): name for uid, name in pairs if name}
    return {
        "ok": True, "task_id": task_id, "names": names,
        "requested": len(ids), "resolved": len(names),
        "unresolved": [uid for uid in ids if str(uid) not in names],
        "partial_history": total > len(events),
        "notice": "Получены только подтверждённые имена; события и БД не менялись.",
    }


@router.get("/timeline/", include_in_schema=False)
def timeline_page():
    return FileResponse(ROOT / "timeline_v6.html", media_type="text/html", headers={
        "Cache-Control": "no-store",
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'self'",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    })


@router.get("/timeline/timeline_v6.js", include_in_schema=False)
def timeline_javascript():
    return FileResponse(ROOT / "timeline_v6.js", media_type="application/javascript", headers={"Cache-Control": "no-store"})


@router.get("/timeline/timeline_v6.css", include_in_schema=False)
def timeline_css():
    return FileResponse(ROOT / "timeline_v6.css", media_type="text/css", headers={"Cache-Control": "no-store"})

# v6.4: Optional union of legacy task-forum comments and new task-chat messages.
# Old comments are NOT migrated to a new task chat. Both read APIs must be kept.
# This endpoint is opt-in, uses the already configured read adapter, and never
# writes, deletes, synchronizes or caches comment content in the pilot SQLite.


def _api_result(raw: Any) -> Any:
    """Unwrap the standard Bitrix REST envelope, rejecting explicit REST errors."""
    if isinstance(raw, dict) and raw.get("error"):
        raise ValueError("Bitrix REST returned an error")
    if isinstance(raw, dict) and "result" in raw:
        return raw["result"]
    return raw


def _legacy_comments(raw: Any) -> list[dict[str, Any]]:
    """Never interpret a success or message string as a comment record."""
    body = _api_result(raw)
    if isinstance(body, dict):
        body = body.get("comments") or body.get("items") or body.get("list") or []
    if not isinstance(body, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in body:
        if not isinstance(entry, dict):
            continue
        cid = _get(entry, "ID", "id")
        if cid is None:
            continue
        text = _get(entry, "POST_MESSAGE", "post_message")
        # Avoid rendering Bitrix-provided HTML; UI uses textContent.
        out.append({
            "source": "legacy", "id": str(cid),
            "author_id": _get(entry, "AUTHOR_ID", "author_id"),
            "author_name": str(_get(entry, "AUTHOR_NAME", "author_name") or "")[:200],
            "created_at": str(_get(entry, "POST_DATE", "post_date") or ""),
            "text": str(text or "")[:10000],
            "edited": None, "deleted": None,
        })
    return out


def _chat_comments(raw: Any) -> tuple[list[dict[str, Any]], int | None]:
    body = _api_result(raw)
    if not isinstance(body, dict):
        return [], None
    messages = body.get("messages", [])
    users = body.get("users", [])
    names = {str(u.get("id")): str(u.get("name") or "")[:200]
             for u in users if isinstance(u, dict) and u.get("id") is not None} if isinstance(users, list) else {}
    if not isinstance(messages, list):
        return [], None
    out: list[dict[str, Any]] = []
    smallest: int | None = None
    for message in messages:
        if not isinstance(message, dict):
            continue
        mid = _get(message, "id")
        if mid is None:
            continue
        try:
            number = int(mid)
            smallest = min(smallest, number) if smallest is not None else number
        except (ValueError, TypeError):
            pass
        author = _get(message, "author_id", "AUTHOR_ID")
        params = message.get("params") or {}
        code = _get(params, "CODE") if isinstance(params, dict) else None
        # Do not present system/administrative chat events as user comments.
        if str(author or "0") == "0" or code:
            continue
        deleted = _get(params, "IS_DELETED") if isinstance(params, dict) else None
        edited = _get(params, "IS_EDITED") if isinstance(params, dict) else None
        out.append({
            "source": "chat", "id": str(mid), "author_id": author,
            "author_name": names.get(str(author), ""),
            "created_at": str(_get(message, "date", "DATE") or ""),
            "text": str(_get(message, "text", "TEXT") or "")[:10000],
            "edited": str(edited or "").upper() == "Y",
            "deleted": str(deleted or "").upper() == "Y",
        })
    return out, smallest


def _chat_id(raw: Any) -> int | None:
    body = _api_result(raw)
    if not isinstance(body, dict):
        return None
    task = body.get("task") or body.get("item") or body
    if not isinstance(task, dict):
        return None
    obj = task.get("chat")
    value = _get(task, "chatId", "CHAT_ID")
    if value is None and isinstance(obj, dict):
        value = _get(obj, "id")
    try:
        num = int(value)
        return num if num > 0 else None
    except (ValueError, TypeError):
        return None


def _comment_ids(events: list[dict[str, Any]]) -> list[int]:
    ids: set[int] = set()
    for e in events:
        if str(e.get("field") or "").upper() not in {"COMMENT", "COMMENT_EDIT", "COMMENT_DEL"}:
            continue
        for val in (e.get("new_value"), e.get("old_value")):
            if isinstance(val, (str, int)) and str(val).isdigit():
                number = int(val)
                if number > 0:
                    ids.add(number)
    return sorted(ids)[:50]


def _comment_sort_key(item: dict[str, Any]) -> tuple[float, str, str]:
    raw = str(item.get("created_at") or "")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)  # noqa: UP017 – server Python 3.10
        stamp = dt.timestamp()
    except ValueError:
        stamp = 0.0
    return stamp, str(item.get("source")), str(item.get("id"))


def _merge_comments(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedup only within one namespace; a forum ID is not a chat message ID."""
    by_id: dict[tuple[str, str], dict[str, Any]] = {}
    for group in groups:
        for item in group:
            key = (str(item["source"]), str(item["id"]))
            if key not in by_id or (not by_id[key].get("text") and item.get("text")):
                by_id[key] = item
    return sorted(by_id.values(), key=_comment_sort_key)


@router.get("/history/{task_id}/comments")
async def timeline_comments(task_id: int, authorization: str | None = Header(default=None)):
    """Explicit read-only fetch from *both* stores; partial failures remain visible."""
    _authorize(authorization)
    if task_id <= 0:
        raise HTTPException(422, "ID задачи должен быть положительным")
    total_events, events, _ = await asyncio.to_thread(_fetch, task_id, 1000, 0)
    # Only inspect a task already present in the pilot history. Not a generic
    # proxy for extracting task-chat content from unrelated company projects.
    if total_events == 0:
        raise HTTPException(404, "Задача отсутствует в сохранённой истории пилота")
    try:
        from tools.tools import fast_bitrix
        method = getattr(fast_bitrix, "call", None)
        if not callable(method):
            raise AttributeError("call")
    except (ImportError, AttributeError):
        raise HTTPException(503, "Адаптер Битрикс24 не поддерживает чтение комментариев через call") from None

    async def call_api(name: str, params: Any, *, raw: bool = False) -> Any:
        # The fast_bitrix24 client batches normal calls. Legacy task.commentitem
        # methods require positional parameters; raw=True preserves the list and
        # sends one REST request. Chat and task calls remain in their existing mode.
        response = method(name, params, raw=True) if raw else method(name, params)
        if inspect.isawaitable(response):
            response = await asyncio.wait_for(response, timeout=10)
        return response

    errors: dict[str, str] = {}
    limits = {"legacy": False, "chat": False}
    archive: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    known = _comment_ids(events)
    known_found: set[str] = set()

    # Legacy archive: raw=True is essential for old positional REST methods.
    # No attempt to page via batching: preserve the first page and mark partial
    # if Bitrix returns its 50-record page limit. Missing history-linked IDs
    # are queried individually, preserving the old method alongside new chat.
    try:
        raw = await call_api(
            "task.commentitem.getlist", [task_id, {"ID": "asc"}, {}], raw=True,
        )
        batch = _legacy_comments(raw)
        archive.extend(batch)
        known_found.update(c["id"] for c in batch)
        if len(batch) >= 50:
            limits["legacy"] = True
            errors["legacy_page"] = (
                "Архивный REST вернул 50 комментариев; остальная история может быть неполной"
            )
    except Exception:
        errors["legacy_list"] = (
            "Список старых комментариев недоступен даже в raw-режиме; "
            "проверяем отдельные комментарии из журнала по ID"
        )

    for comment_id in known:
        if str(comment_id) in known_found:
            continue
        try:
            response = await call_api(
                "task.commentitem.get", [task_id, comment_id], raw=True,
            )
            records = _legacy_comments([_api_result(response)])
            archive.extend(c for c in records if c["id"] == str(comment_id))
        except Exception:
            continue

    archive = _merge_comments(archive)
    missing_legacy = sorted(set(map(str, known)) - {c["id"] for c in archive})

    # New task card: the chat identifier is attached to tasks.task.get.
    chat_id = None
    try:
        raw_task = await call_api("tasks.task.get", {"taskId": task_id, "select": ["CHAT_ID"]})
        chat_id = _chat_id(raw_task)
    except Exception:
        errors["chat_lookup"] = "Не удалось получить ID чата задачи"

    if chat_id:
        seen: set[str] = set()
        def collect(batch: list[dict[str, Any]]) -> None:
            for c in batch:
                if c["id"] not in seen:
                    current.append(c)
                    seen.add(c["id"])
        try:
            base_params = {"DIALOG_ID": f"chat{chat_id}", "LIMIT": 50}
            initial = await call_api("im.dialog.messages.get", base_params)
            batch, smallest = _chat_comments(initial)
            collect(batch)
            envelope = _api_result(initial)
            messages = envelope.get("messages", []) if isinstance(envelope, dict) else []
            values = [int(m["id"]) for m in messages if isinstance(m, dict) and str(m.get("id", "")).isdigit()]
            newest = max(values) if values else None
            if len(messages) >= 50 and smallest is not None:
                cursor = smallest
                for page in range(5):
                    page_data = await call_api("im.dialog.messages.get", {**base_params, "LAST_ID": cursor})
                    sub, next_cursor = _chat_comments(page_data)
                    collect(sub)
                    envelope = _api_result(page_data)
                    msgs = envelope.get("messages", []) if isinstance(envelope, dict) else []
                    if not msgs or next_cursor is None or next_cursor >= cursor:
                        break
                    cursor = next_cursor
                    if page == 4:
                        limits["chat"] = True
            # A chat can return its first unread messages instead of the newest.
            # Walk the newer side too, so we do not silently omit comments.
            if newest is not None:
                cursor = newest
                for page in range(3):
                    page_data = await call_api("im.dialog.messages.get", {**base_params, "FIRST_ID": cursor})
                    sub, _ = _chat_comments(page_data)
                    collect(sub)
                    envelope = _api_result(page_data)
                    msgs = envelope.get("messages", []) if isinstance(envelope, dict) else []
                    ids_newer = [int(m["id"]) for m in msgs if isinstance(m, dict) and str(m.get("id", "")).isdigit()]
                    if not ids_newer or max(ids_newer) <= cursor:
                        break
                    cursor = max(ids_newer)
                    if page == 2:
                        limits["chat"] = True
        except Exception:
            errors["chat_messages"] = "Чат задачи недоступен или истёк срок запроса"
    else:
        errors.setdefault("chat", "У задачи нет доступного идентификатора чата")

    records = _merge_comments(archive, current)
    return {
        "ok": True,
        "task_id": task_id,
        "comments": records,
        "total": len(records),
        "counts": {"legacy": sum(x["source"] == "legacy" for x in records),
                   "chat": sum(x["source"] == "chat" for x in records)},
        "sources": {"legacy": "task.commentitem.getlist/get", "chat": "im.dialog.messages.get"},
        "missing_legacy_ids": missing_legacy,
        "partial": bool(errors) or bool(missing_legacy) or any(limits.values()) or total_events > len(events),
        "limits": limits,
        "warnings": list(errors.values()),
        "source_status": {
            "legacy": "partial" if ("legacy_list" in errors or limits["legacy"]) else "complete",
            "chat": (
                "unavailable" if chat_id is None else
                "partial" if ("chat_messages" in errors or limits["chat"]) else "complete"
            ),
        },
        "notice": "Тексты получены из API без сохранения; доступна отдельная явная фиксация снимков",
    }


# v6.6: separate append-only snapshots. The existing timeline and pilot DB stay read-only.
if __package__:
    from .comment_archive_v66 import read_archive, save_observation
else:  # Local standalone tests, not the deployed package import.
    from comment_archive_v66 import read_archive, save_observation


@router.get("/history/{task_id}/comment-archive")
async def timeline_comment_archive(task_id: int, authorization: str | None = Header(default=None)):
    """Read cached snapshots; NEVER refresh from Bitrix or create a SQLite file."""
    _authorize(authorization)
    if task_id <= 0:
        raise HTTPException(422, "ID задачи должен быть положительным")
    total, _, _ = await asyncio.to_thread(_fetch, task_id, 1, 0)
    if not total:
        raise HTTPException(404, "Задача отсутствует в истории пилота")
    try:
        return await asyncio.to_thread(read_archive, _db_path(), task_id)
    except (sqlite3.Error, OSError, ValueError):
        raise HTTPException(503, "Архив снимков недоступен для чтения") from None


@router.post("/history/{task_id}/comments/snapshot")
async def timeline_comment_snapshot(task_id: int, authorization: str | None = Header(default=None)):
    """On-demand Bitrix read and append-only capture. Never write the history DB."""
    _authorize(authorization)
    if task_id <= 0:
        raise HTTPException(422, "ID задачи должен быть положительным")
    # Existing endpoint enforces that the task is in pilot history and retrieves
    # both source namespaces. No user-supplied comment text is accepted.
    fetched = await timeline_comments(task_id, authorization=authorization)
    try:
        stats = await asyncio.to_thread(
            save_observation,
            _db_path(), task_id, fetched["comments"], fetched["source_status"],
        )
    except (sqlite3.Error, OSError, ValueError) as exc:
        import logging
        logging.getLogger(__name__).exception("Unable to save pilot comment snapshots")
        raise HTTPException(
            503, "Не удалось записать отдельную тестовую базу снимков. "
                 "Проверьте доступ на запись к каталогу data; история не изменена."
        ) from exc
    return {"ok": True, "task_id": task_id, "saved": stats,
            "fetched": fetched,
            "notice": "Записаны только реально прочитанные снимки; дата создания не равна дате фиксации"}


# v6.7: isolated read-only pilot overview, reusing the existing authorized router.
if __package__:
    from .comment_archive_v66 import archive_path
    from .overview_v67 import overview_data
else:
    from comment_archive_v66 import archive_path
    from overview_v67 import overview_data


@router.get("/overview/data")
def controller_overview_data(authorization: str | None = Header(default=None)):
    _authorize(authorization)
    return overview_data(_db_path(), archive_path(_db_path()))


@router.get("/overview/")
def controller_overview_page():
    return FileResponse(ROOT / "overview_v67.html", media_type="text/html",
                        headers={"Cache-Control": "no-store"})


@router.get("/overview/overview_v67.js")
def controller_overview_js():
    return FileResponse(ROOT / "overview_v67.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-store"})


@router.get("/overview/overview_v67.css")
def controller_overview_css():
    return FileResponse(ROOT / "overview_v67.css", media_type="text/css",
                        headers={"Cache-Control": "no-store"})
