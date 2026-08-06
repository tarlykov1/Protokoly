from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.domain import (
    Employee,
    ParticipantGroupTemplate,
    Protocol,
    ProtocolParticipantGroup,
    ProtocolParticipantGroupMember,
    ProtocolTask,
    ProtocolTaskAssignment,
)


def create_group(db: Session, protocol: Protocol, name: str, *, group_type: str = "custom"):
    name = name.strip()
    if not name:
        raise ValueError("Название списка обязательно")
    group = ProtocolParticipantGroup(protocol_id=protocol.id, name=name, type=group_type)
    db.add(group)
    db.flush()
    return group


def replace_members(
    db: Session, group: ProtocolParticipantGroup, employee_ids: list[int], *, source="manual"
):
    employees = {
        employee.id: employee
        for employee in db.scalars(
            select(Employee).where(Employee.id.in_({int(value) for value in employee_ids} or {0}))
        )
    }
    group.members.clear()
    db.flush()
    seen = set()
    for value in employee_ids:
        employee_id = int(value)
        if employee_id in seen or employee_id not in employees:
            continue
        employee = employees[employee_id]
        group.members.append(
            ProtocolParticipantGroupMember(
                employee_id=employee.id, name_snapshot=employee.full_name, source=source
            )
        )
        seen.add(employee_id)
    return group


def copy_members(db: Session, source: ProtocolParticipantGroup, target: ProtocolParticipantGroup):
    current = {member.employee_id for member in target.members}
    for member in source.members:
        if member.employee_id not in current:
            target.members.append(
                ProtocolParticipantGroupMember(
                    employee_id=member.employee_id,
                    name_snapshot=member.name_snapshot,
                    source="attendees_copy",
                )
            )
            current.add(member.employee_id)
    db.flush()
    return target


def copy_template(db: Session, protocol: Protocol, template: ParticipantGroupTemplate):
    group = create_group(db, protocol, template.name, group_type="template_copy")
    for member in template.members:
        group.members.append(
            ProtocolParticipantGroupMember(
                employee_id=member.employee_id,
                name_snapshot=member.name_snapshot,
                source="template",
            )
        )
    db.flush()
    return group


def expand_group_assignment(db: Session, task: ProtocolTask, group_id: int | None) -> None:
    """Materialize the selected group into employee assignments for task publication."""
    for assignment in list(task.assignments):
        if assignment.source_participant_group_id:
            db.delete(assignment)
            task.assignments.remove(assignment)
    if not group_id:
        return
    group = db.get(ProtocolParticipantGroup, int(group_id))
    if not group or group.protocol_id != task.protocol_id:
        raise ValueError("Список участников не принадлежит протоколу")
    existing = {item.employee_id for item in task.assignments if item.employee_id}
    for member in group.members:
        if member.employee_id not in existing:
            assignment = ProtocolTaskAssignment(
                protocol_task_id=task.id,
                employee_id=member.employee_id,
                source_participant_group_id=group.id,
                sort_order=len(task.assignments),
            )
            db.add(assignment)
            task.assignments.append(assignment)
            existing.add(member.employee_id)


def refresh_protocol_group_assignments(db: Session, protocol: Protocol) -> None:
    for task in protocol.tasks:
        group_id = next(
            (
                item.source_participant_group_id
                for item in task.assignments
                if item.source_participant_group_id
            ),
            None,
        )
        if group_id:
            expand_group_assignment(db, task, group_id)
    db.flush()
