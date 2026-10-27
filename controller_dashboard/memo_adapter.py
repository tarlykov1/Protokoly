"""Pure adapter for actual rows in memo_activity_dashboard.py (October 2026).

No network access and no authentication shortcuts. Apply authorization and
Bitrix group filtering BEFORE passing rows into this adapter.
"""
from collections import defaultdict
from datetime import datetime
from typing import Any

DONE_STATUSES = {"Завершена", "Завершено", "5"}
OBSOLETE_STATUSES = {"Неактуально", "Неактуальная", "Отменена", "Отменено"}


def _stamp(value: Any) -> str:
    return str(value or "")


def _day(value: Any) -> str:
    return _stamp(value)[:10]


def normalize_memo_rows(rows: list[dict], group_name: str = "МЕМО") -> list[dict]:
    """One task per responsible executor, not one row per participant."""
    by_task: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("task_id"):
            by_task[str(row["task_id"])].append(row)

    items = []
    for task_id, participants in by_task.items():
        primary = next((r for r in participants if r.get("role") == "executor"), None)
        if primary is None:
            # Without the responsible row we cannot reliably calculate ID.
            continue
        status = str(primary.get("status") or "")
        obsolete = status in OBSOLETE_STATUSES
        done = status in DONE_STATUSES
        due = _day(primary.get("deadline"))
        closed = _day(primary.get("closed_at"))
        controllers = [r for r in participants if r.get("role") == "controller"]
        activities = [
            _stamp(a) for r in participants for a in (r.get("activity_times") or []) if a
        ]
        items.append({
            "id": task_id,
            "source": "memo",
            "type": "МЕМО",
            "document": primary.get("memo") or "МЕМО",
            "event": primary.get("event") or "",
            "group": group_name,
            "title": primary.get("task") or "",
            "responsible": primary.get("fio") or "",
            "responsible_id": primary.get("employee_id"),
            "accomplices": [r.get("fio") for r in participants if r.get("role") == "accomplice" and r.get("fio")],
            "assistants": [r.get("fio") for r in participants if r.get("role") == "assistant" and r.get("fio")],
            "controllers": [r.get("fio") for r in controllers if r.get("fio")],
            "controller_reaction": any(bool(r.get("controller_action")) or int(r.get("controller_comment_count") or 0) > 0 for r in controllers),
            "controller_comment_count": sum(int(r.get("controller_comment_count") or 0) for r in controllers),
            "stage": primary.get("stage") or "",
            "due": due,
            "status": "Неактуально" if obsolete else ("Исполнено" if done else "В работе"),
            "closed_at": closed,
            "closed_on_time": bool(done and due and closed and closed <= due),
            "assigned_at": primary.get("assigned_at"),
            "started_at": primary.get("started_at"),
            "last_activity_at": max(activities, default=""),
            "revision_returns": max((int(r.get("revision_returns") or 0) for r in participants), default=0),
            "link": primary.get("task_url") or "",
            "deadline_history_available": False,
            "new_comment_since_view": None,
        })
    return items


def calculate_kpis(items: list[dict]) -> dict:
    actual = [x for x in items if x.get("status") != "Неактуально"]
    finished = [x for x in actual if x.get("status") == "Исполнено"]
    on_time = [x for x in finished if x.get("closed_on_time")]
    return {
        "actual": len(actual),
        "obsolete": len(items) - len(actual),
        "completed": len(finished),
        "id_percent": round(100 * len(finished) / len(actual), 1) if actual else None,
        "completed_on_time_percent": round(100 * len(on_time) / len(finished), 1) if finished else None,
    }
