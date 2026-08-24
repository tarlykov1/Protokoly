from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class ReportQuery:
    period_start: date | None = None
    period_end: date | None = None
    meeting_from: date | None = None
    meeting_to: date | None = None
    deadline_from: date | None = None
    deadline_to: date | None = None
    closed_from: date | None = None
    closed_to: date | None = None
    document_type: str | None = None
    project_ids: tuple[int, ...] = ()
    department_names: tuple[str, ...] = ()
    assignee_ids: tuple[int, ...] = ()
    section_id: int | None = None
    protocol_status: str | None = None
    task_status: str | None = None
    overdue: bool | None = None
    controlled: bool | None = None
    completed_only: bool = False
    active_only: bool = False
    unassigned_only: bool = False
    no_deadline_only: bool = False
    reportable_only: bool = False
    weekly: bool = False
    include_deferred: bool = False
    event: str | None = None
    project: str | None = None
    assignee: str | None = None
    department: str | None = None
    problem_only: bool = False
    data_issue: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result = {}
        for key, value in self.__dict__.items():
            if value not in (None, False, (), ""):
                result[key] = value.isoformat() if isinstance(value, date) else value
        return result


@dataclass
class TaskReportRow:
    task_id: int
    number: str
    protocol_id: int
    protocol: str
    document_type: str
    meeting_date: date | None
    project: str
    section: str
    text: str
    responsible: str
    other_assignees: str
    department: str
    original_deadline: date | None
    deadline: date | None
    closed_at: date | None
    status: str
    result: str
    days_overdue: int
    overdue_kind: str
    bitrix_task_id: str
    bitrix_url: str
    protocol_url: str
    assignee_id: int | None = None
    protocol_number: str = ""
    event: str = ""
    description: str = ""
    assignees: tuple[str, ...] = ()
    departments: tuple[str, ...] = ()
    parent_task_id: int | None = None
    normalized_status: str = "in_progress"
    status_label: str = "В работе"
    overdue: bool = False
    completed_in_time: bool = False
    completed_late: bool = False
    carried_over: bool = False
    is_root: bool = False
    included: bool = True
    tags: tuple[str, ...] = ()
    unknown_employee: bool = False
    missing_bitrix_user_id: bool = False
    sync_error: bool = False


@dataclass
class ReportDataset:
    query: ReportQuery
    rows: list[TaskReportRow]
    kpis: dict[str, int | float]
    discipline: dict[str, dict[str, int | float]] = field(default_factory=dict)
    statuses: dict[str, int] = field(default_factory=dict)
    assignees: list[dict[str, Any]] = field(default_factory=list)
    departments: list[dict[str, Any]] = field(default_factory=list)
    projects: list[dict[str, Any]] = field(default_factory=list)
    protocols: list[dict[str, Any]] = field(default_factory=list)
    dynamics: list[dict[str, Any]] = field(default_factory=list)
    data_quality: dict[str, int] = field(default_factory=dict)
