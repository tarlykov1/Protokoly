from collections import Counter, defaultdict
from datetime import date

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.db.models.domain import (
    Employee,
    Protocol,
    ProtocolSection,
    ProtocolTask,
    ProtocolTaskAssignment,
    ProtocolTaskControl,
)
from app.services.reporting.metrics import (
    DEFERRED_STATUSES,
    days_overdue,
    execution_on_time,
    include_in_weekly_report,
    is_completed,
)
from app.services.reporting.models import ReportDataset, ReportQuery, TaskReportRow


class ReportService:
    """The single selection and calculation boundary used by dashboard, web and Excel."""

    def __init__(self, session: Session, today: date | None = None):
        self.session = session
        self.today = today or date.today()

    def _statement(self, query: ReportQuery):
        stmt = select(ProtocolTask).join(ProtocolTask.protocol)
        if query.project_ids:
            stmt = stmt.where(Protocol.project_id.in_(query.project_ids))
        if query.document_type and query.document_type != "all":
            stmt = stmt.where(Protocol.protocol_type == query.document_type)
        if query.protocol_status:
            stmt = stmt.where(Protocol.status == query.protocol_status)
        if query.task_status:
            stmt = stmt.where(ProtocolTask.status == query.task_status)
        if query.section_id:
            stmt = stmt.where(ProtocolTask.section_id == query.section_id)
        if query.meeting_from:
            stmt = stmt.where(Protocol.meeting_date >= query.meeting_from)
        if query.meeting_to:
            stmt = stmt.where(Protocol.meeting_date <= query.meeting_to)
        if query.deadline_from:
            stmt = stmt.where(ProtocolTask.deadline >= query.deadline_from)
        if query.deadline_to:
            stmt = stmt.where(ProtocolTask.deadline <= query.deadline_to)
        if query.controlled is not None:
            stmt = stmt.where(ProtocolTask.is_controlled.is_(query.controlled))
        if query.no_deadline_only:
            stmt = stmt.where(ProtocolTask.deadline.is_(None))
        if query.reportable_only:
            stmt = stmt.where(ProtocolTask.include_in_report.is_(True))
        if query.unassigned_only:
            stmt = stmt.where(~ProtocolTask.assignments.any())
        if query.assignee_ids or query.department_names:
            stmt = stmt.join(ProtocolTask.assignments).join(ProtocolTaskAssignment.employee)
            if query.assignee_ids:
                stmt = stmt.where(Employee.id.in_(query.assignee_ids))
            if query.department_names:
                stmt = stmt.where(Employee.department.in_(query.department_names))
        if query.closed_from or query.closed_to:
            stmt = stmt.join(ProtocolTask.control)
            if query.closed_from:
                stmt = stmt.where(ProtocolTaskControl.actual_date >= query.closed_from)
            if query.closed_to:
                stmt = stmt.where(ProtocolTaskControl.actual_date <= query.closed_to)
        if query.completed_only:
            stmt = stmt.where(ProtocolTask.status.in_(("completed", "done", "closed")))
        if query.active_only:
            stmt = stmt.where(
                ~ProtocolTask.status.in_(tuple({"completed", "done", "closed"} | DEFERRED_STATUSES))
            )
        if query.overdue is True:
            stmt = stmt.outerjoin(ProtocolTask.control).where(
                or_(
                    and_(
                        ~ProtocolTask.status.in_(("completed", "done", "closed")),
                        ProtocolTask.deadline < self.today,
                    ),
                    and_(
                        ProtocolTask.status.in_(("completed", "done", "closed")),
                        ProtocolTaskControl.actual_date > ProtocolTask.deadline,
                    ),
                )
            )
        elif query.overdue is False:
            stmt = stmt.where(
                or_(ProtocolTask.deadline.is_(None), ProtocolTask.deadline >= self.today)
            )
        if query.weekly and query.period_start and query.period_end:
            stmt = stmt.outerjoin(ProtocolTask.control).where(
                or_(
                    ProtocolTask.deadline.between(query.period_start, query.period_end),
                    ProtocolTaskControl.actual_date.between(query.period_start, query.period_end),
                    and_(
                        ProtocolTask.deadline < query.period_start,
                        ~ProtocolTask.status.in_(("completed", "done", "closed")),
                    ),
                )
            )
            if not query.include_deferred:
                stmt = stmt.where(~ProtocolTask.status.in_(tuple(DEFERRED_STATUSES)))
        return stmt.options(
            joinedload(ProtocolTask.protocol).joinedload(Protocol.project),
            selectinload(ProtocolTask.assignments).joinedload(ProtocolTaskAssignment.employee),
            joinedload(ProtocolTask.control),
            selectinload(ProtocolTask.external_links),
            selectinload(ProtocolTask.bitrix_links),
        ).distinct()

    def build(self, query: ReportQuery) -> ReportDataset:
        tasks = self.session.scalars(self._statement(query)).unique().all()
        rows = []
        section_ids = {task.section_id for task in tasks if task.section_id}
        sections = (
            {
                s.id: s.title
                for s in self.session.scalars(
                    select(ProtocolSection).where(ProtocolSection.id.in_(section_ids))
                ).all()
            }
            if section_ids
            else {}
        )
        for task in tasks:
            closed = task.control.actual_date if task.control else None
            if (
                query.weekly
                and query.period_start
                and query.period_end
                and not include_in_weekly_report(
                    deadline=task.deadline,
                    closed_at=closed,
                    status=task.status,
                    period_start=query.period_start,
                    period_end=query.period_end,
                    deferred=task.status in DEFERRED_STATUSES,
                    include_deferred=query.include_deferred,
                    is_subtask=task.parent_task_id is not None,
                    include_in_report=task.include_in_report,
                )
            ):
                continue
            if task.parent_task_id and not task.include_in_report:
                continue
            assignees = [a for a in task.assignments if a.assignee_name]
            external = task.external_links[0] if task.external_links else None
            bitrix_id = (
                str(external.external_task_id)
                if external
                else next(
                    (str(x.bitrix_task_id) for x in task.bitrix_links if x.bitrix_task_id), ""
                )
            )
            overdue_days = days_overdue(task.deadline, closed, task.status, self.today)
            kind = (
                "В срок"
                if execution_on_time(task.deadline, closed, task.status)
                else (
                    "Выполнено с опозданием"
                    if is_completed(task.status) and overdue_days
                    else ("Просрочено" if overdue_days else "")
                )
            )
            rows.append(
                TaskReportRow(
                    task.id,
                    task.number,
                    task.protocol_id,
                    task.protocol.title,
                    task.protocol.protocol_type,
                    task.protocol.meeting_date,
                    task.protocol.project.name,
                    sections.get(task.section_id, ""),
                    task.title,
                    assignees[0].assignee_name if assignees else "",
                    ", ".join(a.assignee_name for a in assignees[1:]),
                    assignees[0].employee.department
                    if assignees and assignees[0].employee and assignees[0].employee.department
                    else "",
                    task.original_deadline or task.deadline,
                    task.deadline,
                    closed,
                    task.status,
                    task.control.result_comment
                    if task.control and task.control.result_comment
                    else "",
                    overdue_days,
                    kind,
                    bitrix_id,
                    external.external_task_url if external and external.external_task_url else "",
                    f"/protocols/{task.protocol_id}",
                    assignees[0].employee_id if assignees else None,
                )
            )
        return self._dataset(query, rows)

    def _dataset(self, query, rows):
        total = len(rows)
        completed = sum(is_completed(r.status) for r in rows)
        overdue = sum(r.overdue_kind == "Просрочено" for r in rows)
        on_time = sum(r.overdue_kind == "В срок" for r in rows)
        late = sum(r.overdue_kind == "Выполнено с опозданием" for r in rows)
        protocol_ids = {r.protocol_id for r in rows}
        protocols = {r.protocol_id: r for r in rows}
        kpis = {
            "events": len(protocol_ids),
            "protocols": sum(protocols[i].document_type == "protocol" for i in protocol_ids),
            "memos": sum(protocols[i].document_type == "memo" for i in protocol_ids),
            "tasks": total,
            "completed": completed,
            "in_progress": total - completed,
            "overdue": overdue,
            "unassigned": sum(not r.responsible for r in rows),
            "no_deadline": sum(r.deadline is None for r in rows),
            "completion_percent": round(completed * 100 / total, 1) if total else 0,
            "on_time_percent": round(on_time * 100 / completed, 1) if completed else 0,
        }
        discipline = {}
        categories = {
            "on_time": on_time,
            "late": late,
            "overdue_open": overdue,
            "in_progress": total - completed - overdue,
        }
        for key, count in categories.items():
            discipline[key] = {
                "count": count,
                "percent": round(count * 100 / total, 1) if total else 0,
            }
        statuses = dict(Counter(r.status for r in rows))
        assignees = self._group(rows, "responsible")
        departments = self._group(rows, "department")
        projects = self._group(rows, "project")
        protocol_rows = []
        for pid, group in self._groups(rows, "protocol_id").items():
            first = group[0]
            done = sum(is_completed(x.status) for x in group)
            protocol_rows.append(
                {
                    "id": pid,
                    "name": first.protocol,
                    "date": first.meeting_date,
                    "type": first.document_type,
                    "project": first.project,
                    "total": len(group),
                    "completed": done,
                    "overdue": sum(x.overdue_kind == "Просрочено" for x in group),
                    "readiness": round(done * 100 / len(group)),
                }
            )
        return ReportDataset(
            query, rows, kpis, discipline, statuses, assignees, departments, projects, protocol_rows
        )

    @staticmethod
    def _groups(rows, attr):
        result = defaultdict(list)
        for row in rows:
            result[getattr(row, attr)].append(row)
        return result

    def _group(self, rows, attr):
        result = []
        for name, group in self._groups(rows, attr).items():
            if not name:
                continue
            done = sum(is_completed(x.status) for x in group)
            on_time = sum(x.overdue_kind == "В срок" for x in group)
            late = sum(x.overdue_kind == "Выполнено с опозданием" for x in group)
            overdue = sum(x.overdue_kind == "Просрочено" for x in group)
            result.append(
                {
                    "name": name,
                    "total": len(group),
                    "completed": done,
                    "on_time": on_time,
                    "late": late,
                    "in_progress": len(group) - done,
                    "overdue": overdue,
                    "on_time_percent": round(on_time * 100 / done, 1) if done else 0,
                    "completion_percent": round(done * 100 / len(group), 1),
                }
            )
        return sorted(result, key=lambda x: (-x["overdue"], x["name"]))
