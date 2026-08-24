import re
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
            stmt = stmt.where(Protocol.document_type == query.document_type)
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
            event = self._clean_event(
                task.protocol.event_title or task.protocol.title or (parent.title if parent else "")
            )
            assignment_links = []
            for position, assignment in enumerate(assignments):
                link = next((x for x in task.bitrix_links if x.assignment_id == assignment.id), None)
                url = ""
                if link and link.bitrix_task_id:
                    url = self._bitrix_url(external.external_task_url if external else "", link.bitrix_task_id)
                elif position == 0 and external:
                    url = external.external_task_url or ""
                assignment_links.append((assignment.assignee_name.strip(), url))
            report_items = tuple(
                (name, closed, task.control.result_comment or "")
                for name in names
                if task.control and task.control.result_comment
            )
            row = TaskReportRow(
                task.id, task.number, task.protocol_id, task.protocol.title or "",
                task.protocol.document_type, task.protocol.meeting_date,
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
                logical_key=self._logical_key(task, parent),
                completed_parts=(len(assignments) or 1) if normalized in {"completed_in_time", "completed_late"} else 0,
                required_parts=len(assignments) or 1,
                assignee_links=tuple(assignment_links), assignee_reports=report_items,
                assignment_root_id=task.id, assignment_root_url=external.external_task_url or "" if external else "",
                control_state=self._control_state(task, normalized),
            )
            if self._matches(row, query):
                rows.append(row)
        rows = self._merge_logical_rows(rows)
        rows.sort(key=lambda r: (r.deadline or date.max, r.protocol_id, r.number))
        return self._dataset(query, rows)

    @staticmethod
    def _clean_event(value: str | None) -> str:
        value = "" if value is None or str(value).strip().lower() in {"none", "null", "undefined"} else str(value)
        return re.sub(r"^[\s☆★⭐📅📌]+|[\s☆★⭐📅📌]+$", "", value).strip()

    @staticmethod
    def _logical_key(task: ProtocolTask, parent: ProtocolTask | None = None) -> str:
        """Keep 06 and 06.1 distinct, but fold published copies 06.1/1… into 06.1."""
        number = re.sub(r"/\d+$", "", ((parent.number if parent else task.number) or "").strip())
        root_id = task.parent_task_id or task.id
        # Imported copies often have no ORM parent; protocol + normalized number is stable fallback.
        if re.search(r"/\d+$", task.number or ""):
            root_id = number
        return f"{task.protocol_id}:{root_id}:{number}"

    @staticmethod
    def _bitrix_url(base: str, task_id: int) -> str:
        if not base:
            return ""
        return re.sub(r"/tasks/task/view/\d+/?(?:\?.*)?$", f"/tasks/task/view/{task_id}/", base)

    @staticmethod
    def _control_state(task, normalized):
        if task.control:
            value = task.control.status.lower()
            if value in {"rejected", "returned", "revision"}:
                return "returned"
            if value in COMPLETED_STATUSES:
                return "accepted"
            return "on_control"
        return "accepted" if normalized.startswith("completed") else "not_submitted"

    @staticmethod
    def _merge_logical_rows(rows: list[TaskReportRow]) -> list[TaskReportRow]:
        groups = defaultdict(list)
        for row in rows:
            groups[row.logical_key or f"{row.protocol_id}:{row.task_id}"].append(row)
        merged = []
        for group in groups.values():
            root = next((r for r in group if r.parent_task_id is None), group[0])
            if len(group) == 1:
                merged.append(root)
                continue
            names = tuple(dict.fromkeys(name for r in group for name in r.assignees if name))
            departments = tuple(dict.fromkeys(name for r in group for name in r.departments if name))
            links = tuple(dict.fromkeys(item for r in group for item in r.assignee_links if item[0]))
            reports = tuple(dict.fromkeys(item for r in group for item in r.assignee_reports if item[2]))
            deadlines = [r.deadline for r in group if r.deadline]
            closed_dates = [r.closed_at for r in group if r.closed_at]
            required = sum(r.required_parts for r in group)
            done = sum(r.completed_parts for r in group)
            root.number = re.sub(r"/\d+$", "", root.number)
            root.assignees, root.departments = names, departments
            root.responsible = names[0] if names else ""
            root.other_assignees = ", ".join(names[1:])
            root.deadline = max(deadlines) if deadlines else None
            root.closed_at = max(closed_dates) if closed_dates else None
            root.completed_parts, root.required_parts = done, required
            root.assignee_links, root.assignee_reports = links, reports
            root.tags = tuple(dict.fromkeys(tag for r in group for tag in r.tags if tag.strip()))
            root.result = "\n\n————————————————————————\n\n".join(
                f"{name} — {when.strftime('%d.%m.%Y') if when else ''}\n{text}".strip()
                for name, when, text in reports
            )
            if done == required:
                root.normalized_status = "completed_late" if any(r.completed_late for r in group) else "completed_in_time"
            elif any(r.overdue for r in group):
                root.normalized_status = "overdue"
            else:
                root.normalized_status = "in_progress"
            root.status_label = STATUS_LABELS[root.normalized_status]
            root.overdue = root.normalized_status == "overdue"
            root.completed_in_time = root.normalized_status == "completed_in_time"
            root.completed_late = root.normalized_status == "completed_late"
            merged.append(root)
        return merged

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
        # Formal discipline is defined only for protocols; MEMO remains visible in management totals.
        formal = [r for r in rows if r.document_type == "protocol"]
        formal_completed = [r for r in formal if r.completed_in_time or r.completed_late]
        formal_open = [r for r in formal if not (r.completed_in_time or r.completed_late)]
        on_time = sum(r.completed_in_time for r in formal)
        late = sum(r.completed_late for r in formal)
        protocol_ids = {r.protocol_id for r in rows}
        kpis = {"events": len({r.event for r in rows if r.event}), "protocols": sum(
            next(r for r in rows if r.protocol_id == pid).document_type == "protocol" for pid in protocol_ids),
            "memos": sum(next(r for r in rows if r.protocol_id == pid).document_type == "memo" for pid in protocol_ids),
            "tasks": total, "assignments": total, "completed": completed,
            "in_progress": sum(r.normalized_status == "in_progress" for r in rows),
            "on_control": sum(r.control_state == "on_control" for r in rows),
            "overdue": overdue, "formal_overdue": sum(r.overdue for r in formal), "unassigned": sum(not r.assignees for r in rows),
            "no_deadline": sum(not r.deadline for r in rows),
            "unknown_employee": sum(r.unknown_employee for r in rows), "sync_error": sum(r.sync_error for r in rows),
            "completion_percent": round(completed * 100 / total, 1) if total else 0,
            "on_time_percent": round(on_time * 100 / len(formal_completed), 1) if formal_completed else None,
            "current_overdue_percent": round(sum(r.overdue for r in formal_open) * 100 / len(formal_open), 1) if formal_open else None}
        formal_total = len(formal)
        counts = {"on_time": on_time, "late": late,
                  "overdue_open": sum(r.overdue for r in formal),
                  "in_progress": sum(r.normalized_status == "in_progress" for r in formal)}
        discipline = {k: {"count": v, "percent": round(v * 100 / formal_total, 1) if formal_total else 0}
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
