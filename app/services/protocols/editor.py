from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.domain import (
    Employee,
    EmployeeAlias,
    Protocol,
    ProtocolSection,
    ProtocolTask,
    ProtocolTaskAssignment,
)
from app.services.protocols.participants import expand_group_assignment, set_group_assignments
from app.services.validation import ProtocolValidationService


def editor_errors(task: ProtocolTask) -> list[str]:
    return [issue.message for issue in ProtocolValidationService().validate_task(task)]


def apply_task_data(db: Session, task: ProtocolTask, data: dict) -> ProtocolTask:
    for field in ("number", "title", "description", "priority"):
        if field in data:
            setattr(task, field, data[field] or ("" if field in {"number", "title"} else None))
    if "deadline" in data:
        task.deadline = date.fromisoformat(data["deadline"]) if data["deadline"] else None
    if "section_id" in data:
        section_id = int(data["section_id"]) if data["section_id"] else None
        section = db.get(ProtocolSection, section_id) if section_id else None
        if section_id and (not section or section.protocol_id != task.protocol_id):
            raise ValueError("Раздел не принадлежит протоколу")
        task.section_id = section_id
    if "task_mode" in data:
        task.create_as_subtasks = data["task_mode"] == "subtasks"
    if "create_as_subtasks" in data:
        task.create_as_subtasks = bool(data["create_as_subtasks"])
    if "is_controlled" in data:
        task.is_controlled = bool(data["is_controlled"])
    if "parent_task_id" in data:
        parent_id = int(data["parent_task_id"]) if data["parent_task_id"] else None
        parent = db.get(ProtocolTask, parent_id) if parent_id else None
        if parent_id and (
            not parent or parent.protocol_id != task.protocol_id or parent.id == task.id
        ):
            raise ValueError("Родительское поручение не найдено")
        visited = {task.id}
        while parent:
            if parent.id in visited:
                raise ValueError("Циклическая связь поручений недопустима")
            visited.add(parent.id)
            parent = db.get(ProtocolTask, parent.parent_task_id) if parent.parent_task_id else None
        task.parent_task_id = parent_id if task.create_as_subtasks else None
    if not task.create_as_subtasks:
        task.parent_task_id = None
    if "employee_ids" in data:
        employee_ids = {int(value) for value in data["employee_ids"] or []}
        found = set(db.scalars(select(Employee.id).where(Employee.id.in_(employee_ids))))
        if employee_ids != found:
            raise ValueError("Сотрудник не найден")
        for assignment in list(task.assignments):
            db.delete(assignment)
        task.assignments.clear()
        db.flush()
        seen = set()
        for order, employee_id in enumerate(data["employee_ids"] or []):
            employee_id = int(employee_id)
            if employee_id not in seen:
                assignment = ProtocolTaskAssignment(
                    protocol_task_id=task.id, employee_id=employee_id, sort_order=order
                )
                db.add(assignment)
                task.assignments.append(assignment)
                seen.add(employee_id)
        if "participant_group_ids" in data:
            set_group_assignments(db, task, data.get("participant_group_ids") or [])
        elif data.get("participant_group_id"):
            expand_group_assignment(db, task, int(data["participant_group_id"]))
    elif "participant_group_ids" in data:
        set_group_assignments(db, task, data.get("participant_group_ids") or [])
    elif "participant_group_id" in data:
        expand_group_assignment(db, task, data["participant_group_id"] or None)
    employees = {a.employee_id for a in task.assignments if a.employee_id}
    if "primary_employee_id" in data:
        primary = int(data["primary_employee_id"]) if data["primary_employee_id"] else None
        if primary and primary not in employees:
            raise ValueError("Главный ответственный должен входить в состав исполнителей")
        task.primary_employee_id = primary or (next(iter(employees)) if len(employees) == 1 else None)
    elif task.primary_employee_id not in employees:
        task.primary_employee_id = next(iter(employees)) if len(employees) == 1 else None
    task.validation_status = "ready" if not editor_errors(task) else "validation_required"
    return task


def create_task(db: Session, protocol: Protocol, data: dict) -> ProtocolTask:
    next_position = max((task.position for task in protocol.tasks), default=-1) + 1
    task = ProtocolTask(
        protocol_id=protocol.id,
        number=data.get("number", str(len(protocol.tasks) + 1)),
        title=data.get("title", "Новое поручение"),
        description=data.get("description"),
        status="new",
        validation_status="draft",
        position=next_position,
    )
    db.add(task)
    db.flush()
    return apply_task_data(db, task, data)


def match_source_name(db: Session, task: ProtocolTask, source_name: str, employee_id: int):
    employee = db.get(Employee, employee_id)
    if not employee:
        raise ValueError("Сотрудник не найден")
    normalized = " ".join(source_name.lower().split())
    alias = db.scalar(select(EmployeeAlias).where(EmployeeAlias.normalized_alias == normalized))
    if not alias:
        db.add(
            EmployeeAlias(
                employee_id=employee.id,
                alias=source_name,
                normalized_alias=normalized,
                source="memo_editor",
            )
        )
    unresolved = next(
        (a for a in task.assignments if a.individual_title == source_name and not a.employee_id),
        None,
    )
    if unresolved:
        unresolved.employee_id = employee.id
    elif all(a.employee_id != employee.id for a in task.assignments):
        db.add(ProtocolTaskAssignment(protocol_task_id=task.id, employee_id=employee.id))
