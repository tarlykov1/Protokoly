from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.domain import (
    Employee,
    EmployeeAlias,
    Protocol,
    ProtocolTask,
    ProtocolTaskAssignment,
)


def editor_errors(task: ProtocolTask) -> list[str]:
    errors = []
    if not task.number.strip():
        errors.append("Не указан номер")
    if not task.title.strip():
        errors.append("Не заполнено поручение")
    if not task.assignments:
        errors.append("Не выбран исполнитель")
    if not task.deadline:
        errors.append("Не указан срок")
    if not task.section_id:
        errors.append("Не выбран раздел")
    return errors


def apply_task_data(db: Session, task: ProtocolTask, data: dict) -> ProtocolTask:
    for field in ("number", "title", "description", "priority"):
        if field in data:
            setattr(task, field, data[field] or ("" if field in {"number", "title"} else None))
    if "deadline" in data:
        task.deadline = date.fromisoformat(data["deadline"]) if data["deadline"] else None
    if "section_id" in data:
        task.section_id = int(data["section_id"]) if data["section_id"] else None
    if "task_mode" in data:
        task.create_as_subtasks = data["task_mode"] == "subtasks"
    if "create_as_subtasks" in data:
        task.create_as_subtasks = bool(data["create_as_subtasks"])
    if "is_controlled" in data:
        task.is_controlled = bool(data["is_controlled"])
    if "employee_ids" in data:
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
