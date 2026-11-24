"""Append-only snapshots of comments read from the controller pilot timeline.

Uses a SEPARATE SQLite file. The existing pilot history DB remains read-only.
No REST calls are made here; callers provide normalized, authorized Bitrix output.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

VALID_SOURCES = ("legacy", "chat")
SCHEMA_VERSION = 1


def archive_path(history_path: Path) -> Path:
    explicit = os.getenv("CONTROLLER_PILOT_COMMENT_ARCHIVE_DB_PATH")
    return Path(explicit).resolve() if explicit else history_path.parent / "pilot_comment_snapshots.sqlite"


def _open(path: Path, writable: bool) -> sqlite3.Connection | None:
    path = path.resolve()
    if writable:
        if not path.parent.is_dir():
            raise OSError("Каталог тестового архива отсутствует")
        if not path.exists():
            # Create the database file with private access (no global umask changes).
            try:
                fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
                os.close(fd)
            except FileExistsError:
                pass
        conn = sqlite3.connect(str(path), timeout=5)
    else:
        if not path.is_file():
            return None
        uri = f"file:{quote(str(path), safe='/')}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=3)
        conn.execute("PRAGMA query_only=ON")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
      CREATE TABLE IF NOT EXISTS comment_archive_items (
        task_id INTEGER NOT NULL CHECK(task_id>0),
        source TEXT NOT NULL CHECK(source IN ('legacy','chat')),
        comment_id TEXT NOT NULL,
        author_id TEXT,
        author_name TEXT,
        original_created_at TEXT,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        availability TEXT NOT NULL DEFAULT 'available',
        missing_since TEXT,
        PRIMARY KEY(task_id, source, comment_id)
      );
      CREATE TABLE IF NOT EXISTS comment_archive_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        source TEXT NOT NULL CHECK(source IN ('legacy','chat')),
        comment_id TEXT NOT NULL,
        version_no INTEGER NOT NULL CHECK(version_no>0),
        observed_at TEXT NOT NULL,
        body TEXT NOT NULL,
        body_sha256 TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        edited INTEGER,
        deleted INTEGER,
        UNIQUE(task_id, source, comment_id, version_no),
        FOREIGN KEY(task_id, source, comment_id) REFERENCES comment_archive_items(task_id, source, comment_id)
      );
      CREATE INDEX IF NOT EXISTS archive_versions_task ON comment_archive_versions(task_id, observed_at);
      CREATE TABLE IF NOT EXISTS comment_archive_presence (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        source TEXT NOT NULL CHECK(source IN ('legacy','chat')),
        comment_id TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('first_seen','not_returned','returned')),
        note TEXT NOT NULL
      );
      CREATE INDEX IF NOT EXISTS archive_presence_task ON comment_archive_presence(task_id, observed_at);
      CREATE TABLE IF NOT EXISTS comment_archive_checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        source TEXT NOT NULL CHECK(source IN ('legacy','chat')),
        checked_at TEXT NOT NULL,
        result TEXT NOT NULL CHECK(result IN ('complete','partial','unavailable')),
        received INTEGER NOT NULL,
        note TEXT NOT NULL DEFAULT ''
      );
      CREATE INDEX IF NOT EXISTS archive_checks_task ON comment_archive_checks(task_id, checked_at);
      PRAGMA user_version=1;
    """)


def _as_text(value: Any, maxlen: int) -> str:
    return str(value if value is not None else "")[:maxlen]


def _flag(value: Any) -> int | None:
    return None if value is None else int(bool(value))


def _normalized_comments(comments: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for item in comments[:5000]:
        if not isinstance(item, dict):
            continue
        source = _as_text(item.get("source"), 16)
        cid = _as_text(item.get("id"), 48)
        if source not in VALID_SOURCES or not cid.isdigit() or not (0 < int(cid) < 2**63):
            continue
        # Never treat identical numeric IDs across old forum and new chat as one comment.
        result[(source, cid)] = {
            "source": source, "comment_id": cid,
            "text": _as_text(item.get("text"), 10000),
            "author_id": _as_text(item.get("author_id"), 40),
            "author_name": _as_text(item.get("author_name"), 200),
            "created_at": _as_text(item.get("created_at"), 80),
            "edited": _flag(item.get("edited")),
            "deleted": _flag(item.get("deleted")),
        }
    return result


def save_observation(
    history_path: Path,
    task_id: int,
    comments: list[dict[str, Any]],
    source_status: dict[str, str],
) -> dict[str, Any]:
    """Snapshot one explicit REST read. Incomplete sources MUST NOT signal deletion.

    An absent item after a complete read is *not returned*, never 'deleted'.
    Versions are appended only if the text or remote edited/deleted marker changes.
    """
    if task_id <= 0:
        raise ValueError("task_id must be positive")
    normalized = _normalized_comments(comments)
    state = {name: status if status in ("complete", "partial", "unavailable") else "partial"
             for name, status in ((name, source_status.get(name)) for name in VALID_SOURCES)}
    stamp = datetime.now(timezone.utc).isoformat(timespec="microseconds")  # noqa: UP017 – deployed on Python 3.10
    path = archive_path(history_path)
    if path.resolve() == history_path.resolve():
        raise ValueError("Путь архива совпадает с существующей базой истории")
    conn = _open(path, writable=True)
    if conn is None:
        raise OSError("Не удалось создать тестовый архив")
    result: dict[str, Any] = {
        "task_id": task_id, "checked_at": stamp, "archive_initialized": True,
        "new_comments": 0, "new_versions": 0, "unchanged": 0,
        "now_not_returned": 0, "returned": 0, "source_status": state,
        "database_name": path.name,
    }
    try:
        # Fail closed on an accidentally reused history/database path.
        existing = conn.execute("SELECT 1 FROM sqlite_master WHERE name='pilot_history_events' AND type='table'").fetchone()
        if existing:
            raise ValueError("Выбранная база содержит историю поручений; запись запрещена")
        _ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        for source in VALID_SOURCES:
            matching = [x for (src, _), x in normalized.items() if src == source]
            conn.execute("""INSERT INTO comment_archive_checks
                  (task_id, source, checked_at, result, received, note)
                  VALUES (?, ?, ?, ?, ?, ?)""",
                (task_id, source, stamp, state[source], len(matching),
                 "Не делать вывод об удалении при неполном ответе" if state[source] != "complete" else ""))

        for (source, cid), item in normalized.items():
            last = conn.execute("""SELECT availability FROM comment_archive_items
                WHERE task_id=? AND source=? AND comment_id=?""", (task_id, source, cid)).fetchone()
            if last is None:
                result["new_comments"] += 1
                conn.execute("""INSERT INTO comment_archive_items
                  (task_id, source, comment_id, author_id, author_name, original_created_at,
                   first_seen_at, last_seen_at, availability)
                  VALUES (?,?,?,?,?,?,?,?, 'available')""",
                  (task_id, source, cid, item["author_id"], item["author_name"],
                   item["created_at"], stamp, stamp))
                conn.execute("""INSERT INTO comment_archive_presence
                  (task_id, source, comment_id, observed_at, state, note)
                  VALUES(?,?,?,?,'first_seen',?)""",
                  (task_id, source, cid, stamp, "Впервые получен из API"))
            else:
                if last["availability"] == "not_returned":
                    result["returned"] += 1
                    conn.execute("""INSERT INTO comment_archive_presence
                      (task_id, source, comment_id, observed_at, state, note)
                      VALUES(?,?,?,?,'returned',?)""",
                      (task_id, source, cid, stamp, "Снова доступен в API"))
                conn.execute("""UPDATE comment_archive_items SET
                  author_id=?, author_name=?, original_created_at=?,
                  last_seen_at=?, availability='available', missing_since=NULL
                  WHERE task_id=? AND source=? AND comment_id=?""",
                  (item["author_id"], item["author_name"], item["created_at"],
                   stamp, task_id, source, cid))
            body = item["text"]
            body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
            flags = json.dumps([item["edited"], item["deleted"]], separators=(",", ":"))
            fingerprint = hashlib.sha256(f"{body_hash}|{flags}".encode()).hexdigest()
            prior = conn.execute("""SELECT version_no, fingerprint FROM comment_archive_versions
              WHERE task_id=? AND source=? AND comment_id=? ORDER BY version_no DESC LIMIT 1""",
              (task_id, source, cid)).fetchone()
            if prior is None or prior["fingerprint"] != fingerprint:
                number = (prior["version_no"] + 1) if prior else 1
                conn.execute("""INSERT INTO comment_archive_versions
                   (task_id,source,comment_id,version_no,observed_at,body,body_sha256,
                    fingerprint,edited,deleted) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                   (task_id,source,cid,number,stamp,body,body_hash,fingerprint,item["edited"],item["deleted"]))
                result["new_versions"] += 1
            else:
                result["unchanged"] += 1

        for source in VALID_SOURCES:
            # Can only claim not-returned if that particular source was fully enumerated.
            if state[source] != "complete":
                continue
            found = {cid for src,cid in normalized if src == source}
            previous = conn.execute("""SELECT comment_id FROM comment_archive_items
                WHERE task_id=? AND source=? AND availability='available'""",
                (task_id, source)).fetchall()
            for row in previous:
                cid = row["comment_id"]
                if cid in found:
                    continue
                conn.execute("""UPDATE comment_archive_items SET availability='not_returned',
                   missing_since=? WHERE task_id=? AND source=? AND comment_id=?""",
                   (stamp,task_id,source,cid))
                conn.execute("""INSERT INTO comment_archive_presence
                   (task_id,source,comment_id,observed_at,state,note)
                   VALUES(?,?,?,?,'not_returned',?)""",
                   (task_id,source,cid,stamp,
                    "Не вернулся при полном чтении источника; причина неизвестна"))
                result["now_not_returned"] += 1
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def read_archive(history_path: Path, task_id: int) -> dict[str, Any]:
    """Read without creating or modifying SQLite. No project history DB writes."""
    path = archive_path(history_path)
    base = {"ok": True, "task_id": task_id, "initialized": False,
            "items": [], "archive_events": [], "checks": [],
            "stats": {"comments": 0, "versions": 0, "not_returned": 0},
            "notice": "Снимки фиксируют наблюдение, а не первоначальную редакцию"}
    conn = _open(path, writable=False)
    if conn is None:
        return base
    try:
        # Existing file might be a not-yet-initialized database after interrupted installation.
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "comment_archive_items" not in tables:
            return base
        base["initialized"] = True
        rows = conn.execute("""SELECT task_id,source,comment_id,author_id,author_name,
             original_created_at,first_seen_at,last_seen_at,availability,missing_since
             FROM comment_archive_items WHERE task_id=?
             ORDER BY last_seen_at DESC, source, comment_id LIMIT 500""", (task_id,)).fetchall()
        versions = conn.execute("""SELECT id,source,comment_id,version_no,observed_at,body,
              body_sha256,edited,deleted FROM comment_archive_versions
              WHERE task_id=? ORDER BY id ASC LIMIT 5000""", (task_id,)).fetchall()
        by_key: dict[tuple[str,str], list[dict[str,Any]]] = {}
        events: list[dict[str,Any]] = []
        for v in versions:
            entry = dict(v)
            key = (entry["source"],entry["comment_id"])
            by_key.setdefault(key,[]).append(entry)
            events.append({"kind":"snapshot", "id":entry["id"],
                "source":entry["source"],"comment_id":entry["comment_id"],
                "observed_at":entry["observed_at"], "version_no":entry["version_no"],
                "text":entry["body"]})
        base["items"] = [{**dict(item), "versions": by_key.get((item["source"],item["comment_id"]),[])} for item in rows]
        logs = conn.execute("""SELECT id,source,comment_id,observed_at,state,note
                  FROM comment_archive_presence WHERE task_id=? AND state!='first_seen'
                  ORDER BY id LIMIT 5000""",(task_id,)).fetchall()
        for row in logs:
            d=dict(row)
            events.append({"kind":d["state"], "id":d["id"], "source":d["source"],
                           "comment_id":d["comment_id"],"observed_at":d["observed_at"],
                           "text":"", "note":d["note"]})
        base["archive_events"] = sorted(events, key=lambda e:(e["observed_at"],e["id"]))
        checks = conn.execute("""SELECT source,checked_at,result,received,note
                    FROM comment_archive_checks WHERE task_id=? ORDER BY id DESC LIMIT 12""",(task_id,)).fetchall()
        base["checks"] = [dict(r) for r in checks]
        base["stats"] = {
          "comments": conn.execute("SELECT COUNT(*) FROM comment_archive_items WHERE task_id=?",(task_id,)).fetchone()[0],
          "versions": conn.execute("SELECT COUNT(*) FROM comment_archive_versions WHERE task_id=?",(task_id,)).fetchone()[0],
          "not_returned": conn.execute("SELECT COUNT(*) FROM comment_archive_items WHERE task_id=? AND availability='not_returned'",(task_id,)).fetchone()[0],
        }
        return base
    finally:
        conn.close()
