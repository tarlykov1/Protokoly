"""Private v8 service. Portal verifies group and task ACL before requesting observations."""

import hmac
import json
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

TZ = ZoneInfo("Europe/Moscow")
CAL = json.loads(Path(__file__).with_name("calendar.json").read_text())


def minutes(start, end):
    if not start or not end or end < start:
        return None
    day = start.date()
    result = 0
    while day <= end.date():
        year = CAL.get(str(day.year))
        if year is None:
            return None
        kind = year.get(day.strftime("%m-%d"), 0 if day.weekday() < 5 else 1)
        if kind != 1:
            for a, b in [(9, 13), (14, 17 if kind == 2 else 18)]:
                begin = max(start, datetime.combine(day, time(a), TZ))
                finish = min(end, datetime.combine(day, time(b), TZ))
                result += max(0, (finish - begin).total_seconds())
        day += timedelta(days=1)
    return result / 60


def elapsed_days(start, end):
    if not start or end < start:
        return None
    count = 0
    day = start.date()
    while day < end.date():
        day += timedelta(days=1)
        year = CAL.get(str(day.year))
        if year is None:
            return None
        count += year.get(day.strftime("%m-%d"), 0 if day.weekday() < 5 else 1) != 1
    return count


def stamp(value):
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("timestamp requires offset")
    return dt.astimezone(TZ)


def database():
    con = sqlite3.connect(os.environ["V8_DB"], timeout=15)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS seen(uid INTEGER, task INTEGER, channel TEXT, marker INTEGER NOT NULL,
      PRIMARY KEY(uid,task,channel));
    CREATE TABLE IF NOT EXISTS snapshot(uid INTEGER, grp INTEGER, day TEXT, values_json TEXT,
      PRIMARY KEY(uid,grp,day));
    """)
    return con


def identity(x_dashboard_token: str = Header(""), x_bitrix_user: str = Header("")):
    expected = os.environ.get("V8_TOKEN", "")
    if len(expected) < 32 or not hmac.compare_digest(expected.encode(), x_dashboard_token.encode()):
        raise HTTPException(403)
    if not x_bitrix_user.isascii() or not x_bitrix_user.isdecimal() or int(x_bitrix_user) <= 0:
        raise HTTPException(401)
    return int(x_bitrix_user)


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.post("/view")
def mark(body: dict, uid: int = Depends(identity)):
    task, marker = body.get("task"), body.get("marker")
    if type(task) is not int or task < 1 or type(marker) is not int or marker < 0:
        raise HTTPException(422)
    with closing(database()) as db, db:
        db.execute(
            """INSERT INTO seen VALUES(?,?,?,?) ON CONFLICT(uid,task,channel)
        DO UPDATE SET marker=max(marker,excluded.marker)""",
            (uid, task, body.get("channel", "unknown"), marker),
        )
    return {"ok": True}


@app.post("/observe")
def observe(body: dict, uid: int = Depends(identity)):
    group, rows = body.get("group"), body.get("rows")
    if type(group) is not int or group < 1 or not isinstance(rows, list):
        raise HTTPException(422)
    now = datetime.now(TZ)
    today = now.date().isoformat()
    extra, states = {}, {}
    with closing(database()) as db, db:
        seen = dict(
            db.execute(
                "SELECT task,marker FROM seen WHERE uid=? AND channel=?",
                (uid, body.get("channel", "unknown")),
            )
        )
        for row in rows:
            task = str(int(row["id"]))
            if task in extra:
                raise HTTPException(422)
            latest = row.get("last_comment")
            marker = seen.get(int(task))
            assigned, started = stamp(row.get("assigned")), stamp(row.get("started"))
            duration = minutes(assigned, started or now) if row.get("history_known") else None
            inactivity = elapsed_days(stamp(row.get("activity")), now)
            extra[task] = {
                "late_start": None if duration is None else duration > 48 * 60,
                "inactive": None if inactivity is None else inactivity > 7,
                "unread": None if latest is None or marker is None else latest > marker,
            }
            states[task] = row.get("state")
        db.execute(
            """INSERT INTO snapshot VALUES(?,?,?,?) ON CONFLICT(uid,grp,day)
          DO UPDATE SET values_json=excluded.values_json""",
            (uid, group, today, json.dumps(states)),
        )
        history = {}
        for day, raw in db.execute(
            "SELECT day,values_json FROM snapshot WHERE uid=? AND grp=? ORDER BY day", (uid, group)
        ):
            history[day] = {k: v for k, v in json.loads(raw).items() if k in states}
    return JSONResponse(
        {"extra": extra, "history": history, "at": now.isoformat()},
        headers={"Cache-Control": "no-store"},
    )


@app.post("/source")
def source(body: dict, uid: int = Depends(identity)):
    group = body.get("group")
    if type(group) is not int or group < 1:
        raise HTTPException(422)
    if body.get("source") == "memo":
        if group != int(os.getenv("V8_MEMO_GROUP", "671")):
            raise HTTPException(403)
        try:
            cache = json.loads(Path(os.environ["V8_MEMO_CACHE"]).read_text())
            if int(cache["group_id"]) != group:
                raise ValueError
            return candidates(cache["rows"], cache.get("generated_at"), True)
        except (ValueError, KeyError, OSError, TypeError):
            raise HTTPException(503, "Недоступен срез МЕМО") from None
    if body.get("source") != "protocol":
        raise HTTPException(422)
    from protocol_dashboard import service, store
    from shared.router_v3_18 import _REPORT_CACHE_LOCK, _find_reusable_report

    pending = body.get("report")
    if pending:
        if not isinstance(pending, str) or not re.fullmatch("[a-f0-9]{32}", pending):
            raise HTTPException(400)
        meta = store.load(pending)
        params = meta.get("params") or {}
        if (
            meta.get("user_id") != uid
            or params.get("group_ids") != [group]
            or params.get("report_type") != "eos"
            or params.get("mode") != "assignments"
        ):
            raise HTTPException(403)
        if meta.get("status") == "ready":
            return candidates(store.load_data(pending)["rows"], meta.get("generated_at"), False)
        if meta.get("status") not in ("queued", "processing"):
            raise HTTPException(503, "Ошибка протокольного отчёта")
        return {"status": meta["status"], "report": pending}
    with _REPORT_CACHE_LOCK:
        report = _find_reusable_report(store, uid, {group}, datetime.now(TZ))
        if not report:
            rid = store.new_report(
                dict(
                    report_type="eos",
                    mode="assignments",
                    group_ids=[group],
                    user_ids=[],
                    event_filter=None,
                    date_from=None,
                    date_to=None,
                ),
                uid,
            )
            service.enqueue_dashboard(rid)
            return {"status": "queued", "report": rid}
    rid, status = report
    if status != "ready":
        return {"status": status, "report": rid}
    return candidates(store.load_data(rid)["rows"], store.load(rid).get("generated_at"), False)


def candidates(rows, at, memo):
    if not isinstance(rows, list):
        raise ValueError("rows")
    result = {}
    for row in rows:
        task = int(row.get("task_id") or row["id"])
        if task < 1:
            raise ValueError("task")
        if task in result and memo and row.get("role") != "executor":
            continue
        result[task] = {
            "document": row.get("memo" if memo else "document") or row.get("number"),
            "event": row.get("event"),
            "leader": row.get("leader_id"),
            "stage": row.get("stage"),
            "source_status": row.get("status"),
        }
    return {"status": "ready", "at": at, "tasks": result}
