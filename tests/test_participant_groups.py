from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.domain import Employee, Project, Protocol, ProtocolTask
from app.services.demo_publication import protocol_plan
from app.services.protocols.editor import apply_task_data
from app.services.protocols.participants import copy_members, create_group, replace_members


def setup_data():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine)
    project = Project(name="Project", code="P", bitrix_group_id=101)
    employees = [
        Employee(full_name="Анна Иванова", bitrix_user_id=11),
        Employee(full_name="Борис Петров", bitrix_user_id=12),
    ]
    db.add_all([project, *employees])
    db.flush()
    protocol = Protocol(project_id=project.id, title="Совещание")
    db.add(protocol)
    db.flush()
    return db, project, protocol, employees


def test_protocol_gets_attendees_and_can_create_list():
    db, _, protocol, employees = setup_data()
    assert [group.name for group in protocol.participant_groups] == ["Присутствовали"]
    group = create_group(db, protocol, "Руководители")
    replace_members(db, group, [employees[0].id])
    assert group.members[0].name_snapshot == "Анна Иванова"


def test_copy_attendees_members_without_duplicates():
    db, _, protocol, employees = setup_data()
    attendees = protocol.participant_groups[0]
    replace_members(db, attendees, [employee.id for employee in employees])
    target = create_group(db, protocol, "Команда")
    copy_members(db, attendees, target)
    copy_members(db, attendees, target)
    assert [member.employee_id for member in target.members] == [e.id for e in employees]
    assert all(member.source == "attendees_copy" for member in target.members)


def test_group_assignment_is_expanded_for_editor_and_publication():
    db, project, protocol, employees = setup_data()
    group = create_group(db, protocol, "Проектная команда")
    replace_members(db, group, [employee.id for employee in employees])
    task = ProtocolTask(
        protocol_id=protocol.id,
        number="1",
        title="Подготовить отчёт",
        deadline=date(2026, 8, 20),
    )
    db.add(task)
    db.flush()
    apply_task_data(db, task, {"employee_ids": [], "participant_group_id": group.id})
    assert {assignment.employee_id for assignment in task.assignments} == {e.id for e in employees}
    assert all(assignment.source_participant_group_id == group.id for assignment in task.assignments)

    rows, errors, _ = protocol_plan(db, protocol)
    assert not errors
    assert {planned.responsible_id for _, planned in rows} == {11, 12}
