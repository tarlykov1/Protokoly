from datetime import date
from urllib.parse import parse_qs

from app.services.reporting.models import ReportQuery


def _date(value: str | None):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _bool(values: dict[str, list[str]], key: str):
    value = values.get(key, [None])[-1]
    return None if value is None else value.lower() in {"1", "true", "yes", "on"}


def parse_report_query(query_string: str) -> ReportQuery:
    q = parse_qs(query_string, keep_blank_values=False)
    def ints(key: str) -> tuple[int, ...]:
        return tuple(int(item) for value in q.get(key, []) for item in value.split(",") if item.isdigit())
    return ReportQuery(
        period_start=_date(q.get("period_start", [None])[-1]),
        period_end=_date(q.get("period_end", [None])[-1]),
        meeting_from=_date(q.get("meeting_from", [None])[-1]),
        meeting_to=_date(q.get("meeting_to", [None])[-1]),
        deadline_from=_date(q.get("deadline_from", [None])[-1]),
        deadline_to=_date(q.get("deadline_to", [None])[-1]),
        closed_from=_date(q.get("closed_from", [None])[-1]),
        closed_to=_date(q.get("closed_to", [None])[-1]),
        document_type=q.get("document_type", [None])[-1],
        project_ids=ints("project_id"),
        department_names=tuple(q.get("department", [])),
        assignee_ids=ints("assignee_id"),
        section_id=(ints("section_id") or (None,))[0],
        protocol_status=q.get("protocol_status", [None])[-1],
        task_status=q.get("task_status", [None])[-1],
        overdue=_bool(q, "overdue"),
        controlled=_bool(q, "controlled"),
        completed_only=bool(_bool(q, "completed_only")),
        active_only=bool(_bool(q, "active_only")),
        unassigned_only=bool(_bool(q, "unassigned_only")),
        no_deadline_only=bool(_bool(q, "no_deadline_only")),
        reportable_only=bool(_bool(q, "reportable_only")),
        weekly=bool(_bool(q, "weekly")),
        include_deferred=bool(_bool(q, "include_deferred")),
    )
