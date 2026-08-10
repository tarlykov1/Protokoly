import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db.base import Base
from app.db.models.domain import (
    Employee,
    Project,
    Protocol,
    ProtocolParticipantGroup,
    ProtocolSection,
    ProtocolTask,
)
from app.db.session import SessionLocal, engine
from app.main import app


@pytest.fixture(autouse=True)
def clean_wizard_data():
    yield
    with SessionLocal() as db:
        projects = db.scalars(select(Project).where(Project.code.like("WIZ%"))).all()
        for project in projects:
            protocol_ids = [item.id for item in project.protocols]
            if protocol_ids:
                db.execute(delete(ProtocolTask).where(ProtocolTask.protocol_id.in_(protocol_ids)))
                db.execute(
                    delete(ProtocolSection).where(ProtocolSection.protocol_id.in_(protocol_ids))
                )
                db.execute(
                    delete(ProtocolParticipantGroup).where(
                        ProtocolParticipantGroup.protocol_id.in_(protocol_ids)
                    )
                )
                db.execute(delete(Protocol).where(Protocol.id.in_(protocol_ids)))
            db.delete(project)
        db.commit()


def test_manual_wizard_creates_and_reloads_complete_protocol():
    Base.metadata.create_all(engine)
    client = TestClient(app)
    db_session = SessionLocal()
    project = Project(name="Мастер", code="WIZ")
    employees = [Employee(full_name="Анна Иванова"), Employee(full_name="Борис Петров")]
    db_session.add_all([project, *employees])
    db_session.commit()

    page = client.get("/protocols/create")
    assert page.status_code == 200
    assert 'data-testid="action-bar"' in page.text
    assert "Присутствовали" in page.text

    response = client.post(
        "/protocols/create",
        json={
            "project_id": project.id,
            "number": "М-1",
            "title": "Полностью ручной протокол",
            "meeting_date": "2026-08-08",
            "location": "Переговорная 2",
            "initiator": "Председатель",
            "responsible": "Секретарь",
            "description": "Описание",
            "groups": [
                {
                    "client_id": "att",
                    "name": "Присутствовали",
                    "type": "attendees",
                    "employee_ids": [employees[0].id, employees[1].id],
                },
                {
                    "client_id": "g1",
                    "name": "Список 1",
                    "type": "custom",
                    "employee_ids": [employees[0].id],
                },
                {
                    "client_id": "g2",
                    "name": "Список 2",
                    "type": "custom",
                    "employee_ids": [employees[1].id],
                },
            ],
            "sections": [{"client_id": "s1", "title": "Решения"}],
            "tasks": [
                {
                    "text": "Выполнить решение",
                    "group_id": "g1",
                    "deadline": "2026-09-01",
                    "section_id": "s1",
                    "priority": "high",
                    "task_mode": "subtasks",
                    "controlled": True,
                }
            ],
        },
    )
    assert response.status_code == 200
    protocol_id = response.json()["id"]
    db_session.expire_all()
    protocol = db_session.get(Protocol, protocol_id)
    assert (protocol.status, protocol.location) == ("draft", "Переговорная 2")
    assert [
        g.name
        for g in db_session.scalars(
            select(ProtocolParticipantGroup)
            .where(ProtocolParticipantGroup.protocol_id == protocol_id)
            .order_by(ProtocolParticipantGroup.id)
        )
    ] == ["Присутствовали", "Список 1", "Список 2"]
    assert (
        db_session.scalar(
            select(ProtocolSection).where(ProtocolSection.protocol_id == protocol_id)
        ).title
        == "Решения"
    )
    task = db_session.scalar(select(ProtocolTask).where(ProtocolTask.protocol_id == protocol_id))
    assert (
        task.create_as_subtasks
        and task.is_controlled
        and task.assignments[0].employee_id == employees[0].id
    )
    reloaded = client.get(f"/protocols/{protocol_id}")
    assert reloaded.status_code == 200
    assert "Полностью ручной протокол" in reloaded.text

    local_group = db_session.scalar(
        select(ProtocolParticipantGroup).where(
            ProtocolParticipantGroup.protocol_id == protocol_id,
            ProtocolParticipantGroup.name == "Список 1",
        )
    )
    copied = client.post(
        f"/protocols/{protocol_id}/participant-groups/{local_group.id}/duplicate"
    )
    assert copied.status_code == 200
    assert copied.json()["name"] == "Список 1 — копия"
    renamed = client.put(
        f"/protocols/{protocol_id}/participant-groups/{copied.json()['id']}",
        json={"name": "Рабочая группа", "employee_ids": [employees[1].id]},
    )
    assert renamed.status_code == 200
    db_session.expire_all()
    changed_group = db_session.get(ProtocolParticipantGroup, copied.json()["id"])
    assert changed_group.name == "Рабочая группа"
    assert [member.employee_id for member in changed_group.members] == [employees[1].id]


def test_workflow_action_bar_only_shows_current_actions():
    Base.metadata.create_all(engine)
    client = TestClient(app)
    with SessionLocal() as db:
        project = Project(name="Action bar", code="WIZ-ACTIONS")
        db.add(project)
        db.flush()
        protocol = Protocol(project_id=project.id, title="Статусы", status="draft")
        db.add(protocol)
        db.commit()
        protocol_id = protocol.id
    page = client.get(f"/protocols/{protocol_id}").text
    action_bar = page.split('data-testid="action-bar"', 1)[1].split("</header>", 1)[0]
    assert "Редактировать" in action_bar and "Отправить на проверку" in action_bar
    assert "Утвердить" not in action_bar and "Контроль исполнения" not in action_bar


def test_editor_renders_searchable_assignee_selector_and_participant_list_actions():
    Base.metadata.create_all(engine)
    client = TestClient(app)
    with SessionLocal() as db:
        project = Project(name="Enterprise editor", code="WIZ-SELECTOR")
        employee = Employee(full_name="Мария Соколова")
        db.add_all([project, employee])
        db.flush()
        protocol = Protocol(project_id=project.id, title="Selector", status="draft")
        db.add(protocol)
        db.flush()
        task = ProtocolTask(protocol_id=protocol.id, number="1", title="Поручение")
        db.add(task)
        db.commit()
        protocol_id = protocol.id

    page = client.get(f"/protocols/{protocol_id}/editor")
    assert page.status_code == 200
    assert 'class="task-employees form-select" multiple' in page.text
    assert 'class="duplicate-participant-group' in page.text
    assert 'id="edit-group-name"' in page.text
    selector_script = client.get("/static/js/protocol-editor.js").text
    assert "mountMultiSelector" in selector_script
    assert "selector-chip" in selector_script
