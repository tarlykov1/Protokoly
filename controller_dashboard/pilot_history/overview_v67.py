"""Read-only controller pilot overview built from the existing task-event SQLite.

This is NOT a source of execution discipline, task completion, overdue counts, or
project membership. Those need current Bitrix24 task/group data and methodology.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _read_only(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=3)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA query_only=ON')
    con.execute('PRAGMA busy_timeout=3000')
    return con


def _column(cols: list[str], *candidates: str) -> str | None:
    keys = {c.casefold(): c for c in cols}
    for x in candidates:
        if x.casefold() in keys:
            return keys[x.casefold()]
    return None


def overview_data(history_db: Path, snapshot_db: Path, limit: int = 250) -> dict:
    """Aggregate existing pilot events, no Bitrix24 network calls and no writes."""
    if not 1 <= limit <= 250:
        raise ValueError('Invalid overview limit')
    if not history_db.is_file():
        raise HTTPException(503, 'Пилотная база истории недоступна')
    try:
        con = _read_only(history_db)
    except sqlite3.Error as exc:
        raise HTTPException(503, 'Не удалось открыть пилотную историю') from exc
    try:
        table_exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pilot_history_events'"
        ).fetchone()
        if not table_exists:
            raise HTTPException(503, 'В пилотной БД отсутствует журнал событий')
        cols = [r['name'] for r in con.execute('PRAGMA table_info("pilot_history_events")')]
        task = _column(cols, 'task_id', 'taskid', 'task')
        field = _column(cols, 'field', 'field_name', 'event_type', 'type', 'code')
        ts = _column(cols, 'occurred_at', 'event_date', 'created_at', 'date', 'timestamp')
        if not task:
            raise HTTPException(503, 'В журнале нет столбца ID задачи')
        task_sql = _quote(task)
        type_sql = f'UPPER(CAST({_quote(field)} AS TEXT))' if field else "''"
        time_sql = f'MAX(COALESCE(CAST({_quote(ts)} AS TEXT), \'\'))' if ts else "''"
        where = f"{task_sql} IS NOT NULL AND CAST({task_sql} AS TEXT) != ''"
        totals = con.execute(f'''SELECT COUNT(*) AS event_count,
                     COUNT(DISTINCT {task_sql}) AS task_count,
                     SUM(CASE WHEN {type_sql}='DEADLINE' THEN 1 ELSE 0 END) AS deadlines,
                     SUM(CASE WHEN {type_sql} LIKE 'COMMENT%' THEN 1 ELSE 0 END) AS comment_actions
                  FROM "pilot_history_events" WHERE {where}''').fetchone()
        rows = con.execute(f'''SELECT {task_sql} AS task_id, COUNT(*) AS events,
                   {time_sql} AS last_event_at,
                   SUM(CASE WHEN {type_sql}='DEADLINE' THEN 1 ELSE 0 END) AS deadlines,
                   SUM(CASE WHEN {type_sql} LIKE 'COMMENT%' THEN 1 ELSE 0 END) AS comment_actions
                   FROM "pilot_history_events" WHERE {where}
                   GROUP BY {task_sql} ORDER BY last_event_at DESC, task_id DESC LIMIT ?''', (limit,)).fetchall()
    except sqlite3.Error as exc:
        raise HTTPException(503, 'Не удалось построить тестовую сводку') from exc
    finally:
        con.close()

    snapshots = {}
    archive_error = None
    archive_available = False
    if snapshot_db.resolve() == history_db.resolve():
        archive_error = 'Некорректный путь отдельного архива'
    elif snapshot_db.is_file():
        try:
            ac = _read_only(snapshot_db)
            try:
                exists = ac.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='comment_archive_items'"
                ).fetchone()
                if exists:
                    archive_available = True
                    for item in ac.execute('SELECT task_id, COUNT(*) AS n FROM comment_archive_items GROUP BY task_id'):
                        snapshots[int(item['task_id'])] = int(item['n'])
            finally:
                ac.close()
        except (sqlite3.Error, OSError, ValueError):
            archive_error = 'Отдельный архив снимков временно недоступен'
    tasks = []
    for r in rows:
        try:
            task_id = int(r['task_id'])
        except (ValueError, TypeError):
            continue
        if task_id <= 0:
            continue
        tasks.append({
            'task_id': task_id,
            'event_count': int(r['events']),
            'last_event_at': str(r['last_event_at'] or ''),
            'deadline_changes': int(r['deadlines'] or 0),
            'comment_actions': int(r['comment_actions'] or 0),
            'saved_comments': snapshots.get(task_id, 0),
        })
    return {
        'ok': True,
        'source': 'pilot_history_events (read-only)',
        'totals': {
            'tasks_in_history': int(totals['task_count'] or 0),
            'history_events': int(totals['event_count'] or 0),
            'deadline_changes': int(totals['deadlines'] or 0),
            'comment_actions': int(totals['comment_actions'] or 0),
            'saved_comments': sum(snapshots.values()),
        },
        'tasks': tasks,
        'shown': len(tasks),
        'limit': limit,
        'capped': int(totals['task_count'] or 0) > limit,
        'archive_available': archive_available,
        'archive_warning': archive_error,
        'kpi_availability': {
            'execution_discipline': False,
            'overdue': False,
            'week_over_week_execution': False,
            'protocol_memo_group_access': False,
        },
        'notice': (
            'Это только объём сохранённой пилотной истории. Текущие статусы, просрочка, ИД, '
            'членство в группах МЕМО/протоколов и недельная динамика исполнения не рассчитаны.'
        ),
    }
