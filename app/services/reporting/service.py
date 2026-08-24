from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.db.models.domain import Protocol, ProtocolSection, ProtocolTask, ProtocolTaskAssignment
from app.services.reporting.metrics import (
    COMPLETED_STATUSES,
    DEFERRED_STATUSES,
    STATUS_LABELS,
    days_overdue,
    include_in_weekly_report,
    reporting_status,
)
from app.services.reporting.models import ReportDataset, ReportQuery, TaskReportRow


class ReportService:
    """Canonical task dataset used unchanged by dashboard, tables and exports.

    Database predicates intentionally only limit immutable dimensions. Reporting state,
    period membership and drill-down predicates are applied to normalized rows here, so
    no consumer can accidentally use a second definition of overdue or completion.
    """

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
        if query.meeting_from:
            stmt = stmt.where(Protocol.meeting_date >= query.meeting_from)
        if query.meeting_to:
            stmt = stmt.where(Protocol.meeting_date <= query.meeting_to)
        if query.controlled is not None:
            stmt = stmt.where(ProtocolTask.is_controlled.is_(query.controlled))
        if query.section_id:
            stmt = stmt.where(ProtocolTask.section_id == query.section_id)
        return stmt.options(
            joinedload(ProtocolTask.protocol).joinedload(Protocol.project),
            selectinload(ProtocolTask.assignments).joinedload(ProtocolTaskAssignment.employee),
            joinedload(ProtocolTask.control),
            selectinload(ProtocolTask.external_links),
            selectinload(ProtocolTask.bitrix_links),
        )

    def build(self, query: ReportQuery) -> ReportDataset:
        tasks = self.session.scalars(self._statement(query)).unique().all()
        task_by_id = {task.id: task for task in tasks}
        section_ids = {task.section_id for task in tasks if task.section_id}
        sections = {s.id: s.title for s in self.session.scalars(
            select(ProtocolSection).where(ProtocolSection.id.in_(section_ids))
        ).all()} if section_ids else {}
        control_date = query.period_end or self.today
        rows: list[TaskReportRow] = []
        seen: set[int] = set()
        for task in tasks:
            if task.id in seen:
                continue
            seen.add(task.id)
            effective_status = task.status.lower()
            if task.control and task.control.actual_date:
                effective_status = "completed"
            elif task.control and task.control.status.lower() in COMPLETED_STATUSES:
                effective_status = task.control.status.lower()
            # A synced external status is authoritative when the control row has not yet
            # been created by older installations.
            if not task.control and task.external_links and task.external_links[0].external_status:
                effective_status = task.external_links[0].external_status.lower()
            deferred = effective_status in DEFERRED_STATUSES or task.status.lower() in DEFERRED_STATUSES
            if deferred and not query.include_deferred:
                continue
            is_legacy_root = any(link.task_type in {"root", "event", "container"} for link in task.bitrix_links)
            if is_legacy_root:
                continue
            if task.parent_task_id and not task.include_in_report:
                continue
            closed = task.control.actual_date if task.control else None
            if query.period_start and query.period_end and not include_in_weekly_report(
                deadline=task.deadline, closed_at=closed, status=effective_status,
                period_start=query.period_start, period_end=query.period_end,
                deferred=deferred, include_deferred=query.include_deferred,
                is_subtask=task.parent_task_id is not None,
                include_in_report=task.include_in_report,
            ):
                continue
            assignments = [a for a in task.assignments if a.assignee_name]
            names = tuple(dict.fromkeys(a.assignee_name.strip() for a in assignments if a.assignee_name))
            departments = tuple(dict.fromkeys(
                a.employee.department.strip() for a in assignments
                if a.employee and a.employee.department
            ))
            external = next((x for x in task.external_links if x.external_system.upper() == "BITRIX24"), None)
            bitrix_link = next((x for x in task.bitrix_links if x.bitrix_task_id), None)
            bitrix_id = str(external.external_task_id) if external else (
                str(bitrix_link.bitrix_task_id) if bitrix_link else ""
            )
            normalized = reporting_status(task.deadline, closed, effective_status, control_date)
            overdue_days = days_overdue(task.deadline, closed, effective_status, control_date)
            parent = task_by_id.get(task.parent_task_id)
            event = (task.protocol.title or (parent.title if parent else "") or "").strip()
            row = TaskReportRow(
                task.id, task.number, task.protocol_id, task.protocol.title or "",
                task.protocol.protocol_type, task.protocol.meeting_date,
                task.protocol.project.name if task.protocol.project else "",
                sections.get(task.section_id, ""), task.title or "", names[0] if names else "",
                ", ".join(names[1:]), departments[0] if departments else "",
                task.original_deadline or task.deadline, task.deadline, closed, effective_status,
                task.control.result_comment if task.control and task.control.result_comment else "",
                overdue_days,
                {"completed_in_time": "В срок", "completed_late": "Выполнено с опозданием",
                 "overdue": "Просрочено", "in_progress": ""}[normalized],
                bitrix_id, external.external_task_url if external and external.external_task_url else "",
                f"/protocols/{task.protocol_id}", assignments[0].employee_id if assignments else None,
                protocol_number=task.protocol.number or "", event=event,
                description=task.description or "", assignees=names, departments=departments,
                parent_task_id=task.parent_task_id, normalized_status=normalized,
                status_label=STATUS_LABELS[normalized], overdue=normalized == "overdue",
                completed_in_time=normalized == "completed_in_time",
                completed_late=normalized == "completed_late",
                carried_over=bool(task.deadline and query.period_start and task.deadline < query.period_start),
                is_root=False, included=True,
                tags=("В отчёт",) if task.include_in_report else (),
                unknown_employee=any(a.employee is None for a in assignments),
                missing_bitrix_user_id=any(a.employee and not a.employee.bitrix_user_id for a in assignments),
                sync_error=any(x.sync_status == "error" for x in task.bitrix_links),
            )
            if self._matches(row, query):
                rows.append(row)
        rows.sort(key=lambda r: (r.deadline or date.max, r.protocol_id, r.number))
        return self._dataset(query, rows)

    @staticmethod
    def _matches(row: TaskReportRow, query: ReportQuery) -> bool:
        if query.task_status and query.task_status not in {row.status, row.normalized_status}:
            return False
        if query.deadline_from and (not row.deadline or row.deadline < query.deadline_from):
            return False
        if query.deadline_to and (not row.deadline or row.deadline > query.deadline_to):
            return False
        if query.closed_from and (not row.closed_at or row.closed_at < query.closed_from):
            return False
        if query.closed_to and (not row.closed_at or row.closed_at > query.closed_to):
            return False
        if query.overdue is True and not row.overdue:
            return False
        if query.overdue is False and row.overdue:
            return False
        if query.completed_only and row.normalized_status not in {"completed_in_time", "completed_late"}:
            return False
        if query.active_only and row.normalized_status not in {"in_progress", "overdue"}:
            return False
        if query.unassigned_only and row.assignees:
            return False
        if query.no_deadline_only and row.deadline:
            return False
        if query.reportable_only and not row.included:
            return False
        if query.event and query.event.casefold() not in row.event.casefold():
            return False
        if query.project and query.project != row.project:
            return False
        if query.assignee and query.assignee not in row.assignees:
            return False
        if query.department and query.department not in row.departments:
            return False
        if query.problem_only and not (row.overdue or not row.assignees or not row.deadline or row.sync_error):
            return False
        issues = {"unassigned": not row.assignees, "no_deadline": not row.deadline,
                  "unknown_employee": row.unknown_employee,
                  "missing_bitrix_user_id": row.missing_bitrix_user_id,
                  "no_project": not row.project, "no_event": not row.event,
                  "sync_error": row.sync_error}
        return not query.data_issue or issues.get(query.data_issue, False)

    def _dataset(self, query: ReportQuery, rows: list[TaskReportRow]) -> ReportDataset:
        total = len(rows)
        completed = sum(r.completed_in_time or r.completed_late for r in rows)
        overdue = sum(r.overdue for r in rows)
        on_time = sum(r.completed_in_time for r in rows)
        late = sum(r.completed_late for r in rows)
        protocol_ids = {r.protocol_id for r in rows}
        kpis = {"events": len({r.event for r in rows if r.event}), "protocols": sum(
            next(r for r in rows if r.protocol_id == pid).document_type == "protocol" for pid in protocol_ids),
            "memos": sum(next(r for r in rows if r.protocol_id == pid).document_type == "memo" for pid in protocol_ids),
            "tasks": total, "completed": completed,
            "in_progress": sum(r.normalized_status == "in_progress" for r in rows),
            "overdue": overdue, "unassigned": sum(not r.assignees for r in rows),
            "no_deadline": sum(not r.deadline for r in rows),
            "completion_percent": round(completed * 100 / total, 1) if total else 0,
            "on_time_percent": round(on_time * 100 / completed, 1) if completed else 0}
        counts = {"on_time": on_time, "late": late, "overdue_open": overdue,
                  "in_progress": total - completed - overdue}
        discipline = {k: {"count": v, "percent": round(v * 100 / total, 1) if total else 0}
                      for k, v in counts.items()}
        statuses = {STATUS_LABELS[key]: sum(r.normalized_status == key for r in rows)
                    for key in STATUS_LABELS}
        quality = {"unassigned": sum(not r.assignees for r in rows),
                   "no_deadline": sum(not r.deadline for r in rows),
                   "unknown_employee": sum(r.unknown_employee for r in rows),
                   "missing_bitrix_user_id": sum(r.missing_bitrix_user_id for r in rows),
                   "no_project": sum(not r.project for r in rows), "no_event": sum(not r.event for r in rows),
                   "sync_error": sum(r.sync_error for r in rows)}
        return ReportDataset(query, rows, kpis, discipline, statuses, self._group(rows, "assignees"),
                             self._group(rows, "departments"), self._group(rows, "project"),
                             self._protocols(rows), self._dynamics(rows), quality)

    @staticmethod
    def _group(rows, attr):
        groups = defaultdict(list)
        for row in rows:
            value = getattr(row, attr)
            for name in value if isinstance(value, tuple) else (value,):
                if name:
                    groups[name].append(row)
        result = []
        for name, group in groups.items():
            done = sum(r.completed_in_time or r.completed_late for r in group)
            on_time = sum(r.completed_in_time for r in group)
            result.append({"name": name, "total": len(group), "completed": done, "on_time": on_time,
                           "late": sum(r.completed_late for r in group),
                           "in_progress": sum(r.normalized_status == "in_progress" for r in group),
                           "overdue": sum(r.overdue for r in group),
                           "on_time_percent": round(on_time * 100 / done, 1) if done else 0,
                           "completion_percent": round(done * 100 / len(group), 1)})
        return sorted(result, key=lambda x: (-x["overdue"], x["name"]))

    @staticmethod
    def _protocols(rows):
        groups = defaultdict(list)
        for row in rows:
            groups[row.protocol_id].append(row)
        return [{"id": pid, "name": group[0].protocol, "date": group[0].meeting_date,
                 "type": group[0].document_type, "project": group[0].project, "total": len(group),
                 "completed": sum(r.completed_in_time or r.completed_late for r in group),
                 "overdue": sum(r.overdue for r in group)} for pid, group in groups.items()]

    @staticmethod
    def _dynamics(rows):
        groups = defaultdict(list)
        for row in rows:
            anchor = row.deadline or row.closed_at
            if anchor:
                monday = anchor - timedelta(days=anchor.weekday())
                groups[monday].append(row)
        return [{"period": key, "received": len(group),
                 "completed": sum(r.completed_in_time or r.completed_late for r in group),
                 "overdue": sum(r.overdue for r in group)} for key, group in sorted(groups.items())]
