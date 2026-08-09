from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db.base import Base
from app.db.models.domain import (
    Employee,
    Project,
    Protocol,
    ProtocolSection,
    ProtocolTask,
    ProtocolTaskAssignment,
)
from app.db.session import SessionLocal, engine
from app.main import app


def make_protocol():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        project = Project(name="Editor", code="EDITOR-MVP")
        employee = Employee(full_name="Иванов Иван Иванович", is_active=True)
        db.add_all([project, employee])
        db.flush()
        protocol = Protocol(project_id=project.id, title="Протокол редактора", number="E-1")
        db.add(protocol)
        db.flush()
        sections = [
            ProtocolSection(protocol_id=protocol.id, title="Первый", sort_order=1),
            ProtocolSection(protocol_id=protocol.id, title="Второй", sort_order=2),
        ]
        db.add_all(sections)
        db.flush()
        for number in range(1, 10):
            task = ProtocolTask(
                protocol_id=protocol.id,
                section_id=sections[number % 2].id,
                number=str(number),
                title=f"Поручение {number}",
                deadline=date(2027, 1, number),
            )
            db.add(task)
            db.flush()
            db.add(ProtocolTaskAssignment(protocol_task_id=task.id, employee_id=employee.id))
        db.commit()
        return protocol.id, employee.id, [section.id for section in sections]


def teardown_protocol():
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == "EDITOR-MVP"))
        if project:
            protocol_ids = select(Protocol.id).where(Protocol.project_id == project.id)
            task_ids = select(ProtocolTask.id).where(ProtocolTask.protocol_id.in_(protocol_ids))
            db.execute(
                delete(ProtocolTaskAssignment).where(
                    ProtocolTaskAssignment.protocol_task_id.in_(task_ids)
                )
            )
            db.execute(delete(ProtocolTask).where(ProtocolTask.protocol_id.in_(protocol_ids)))
            db.execute(delete(ProtocolSection).where(ProtocolSection.protocol_id.in_(protocol_ids)))
            db.execute(delete(Protocol).where(Protocol.project_id == project.id))
            db.execute(delete(Project).where(Project.id == project.id))
            db.commit()


def test_editor_integration_workflow():
    teardown_protocol()
    protocol_id, employee_id, sections = make_protocol()
    client = TestClient(app)
    page = client.get(f"/protocols/{protocol_id}/editor")
    assert page.status_code == 200
    assert page.text.count('class="task-row') == 9
    assert 'class="protocol-editor-table"' not in page.text
    assert 'class="editor-commandbar' in page.text
    assert "MEMO совместимый" in page.text

    with SessionLocal() as db:
        protocol = db.get(Protocol, protocol_id)
        first, second = protocol.tasks[:2]
        first_id, second_id = first.id, second.id
    response = client.post(
        f"/protocols/{protocol_id}/editor/save",
        json={
            "sections": [{"id": sections[0], "title": "Переименованный"}],
            "tasks": [
                {
                    "id": first_id,
                    "number": "1.1",
                    "title": "Измененный текст",
                    "description": "Полный измененный текст",
                    "deadline": "2027-06-15",
                    "section_id": sections[0],
                    "priority": "high",
                    "task_mode": "subtasks",
                    "is_controlled": True,
                    "employee_ids": [],
                }
            ],
        },
    )
    assert response.json() == {"saved": True}
    client.post(
        f"/protocols/{protocol_id}/editor/bulk",
        json={
            "task_ids": [first_id, second_id],
            "changes": {
                "deadline": "2027-12-31",
                "section_id": sections[1],
                "task_mode": "independent",
                "employee_id": employee_id,
            },
        },
    )
    added = client.post(
        f"/protocols/{protocol_id}/editor/tasks",
        json={
            "title": "Добавленное",
            "section_id": sections[0],
            "deadline": "2027-10-10",
            "employee_ids": [employee_id],
        },
    ).json()["id"]
    assert client.delete(f"/protocols/{protocol_id}/editor/tasks/{added}").status_code == 200

    reloaded = client.get(f"/protocols/{protocol_id}/editor").text
    assert "Измененный текст" in reloaded
    assert "Переименованный" in reloaded
    with SessionLocal() as db:
        first = db.get(ProtocolTask, first_id)
        assert first.deadline == date(2027, 12, 31)
        assert first.section_id == sections[1]
        assert len(first.assignments) == 1
        assert db.get(ProtocolTask, added) is None

    client.post(
        f"/protocols/{protocol_id}/editor/save",
        json={"tasks": [{"id": first_id, "employee_ids": [], "deadline": ""}]},
    )
    blocked = client.get(f"/protocols/{protocol_id}/editor/publication", follow_redirects=False)
    assert blocked.status_code == 303
    assert blocked.headers["location"].endswith("/editor?filter=errors")
    teardown_protocol()


def test_editor_layout_and_validation_reason_are_rendered():
    teardown_protocol()
    protocol_id, _, _ = make_protocol()
    client = TestClient(app)
    page = client.get(f"/protocols/{protocol_id}/editor")
    assert page.status_code == 200
    assert 'id="publish-editor" class="btn btn-primary disabled"' not in page.text
    css = client.get("/static/css/app.css").text
    assert ".task-row{display:grid" in css
    assert ".sortable-ghost" in css
    assert ".section-body.drop-active" in css
    publication_plan = client.get(f"/protocols/{protocol_id}/publication-plan")
    assert (
        "Исполнитель не сопоставлен с пользователем Битрикс24, "
        "будет создана задача без назначения" in publication_plan.text
    )
    with SessionLocal() as db:
        task = db.get(Protocol, protocol_id).tasks[0]
        task.title = ""
        db.commit()
    invalid_page = client.get(f"/protocols/{protocol_id}/editor")
    assert 'class="task-row has-errors"' in invalid_page.text
    assert "Не заполнено поручение" in invalid_page.text
    assert "workflow-draft" in invalid_page.text
    teardown_protocol()


def test_editor_preserves_draft_creates_section_and_saves_parent():
    teardown_protocol()
    protocol_id, _, sections = make_protocol()
    client = TestClient(app)
    with SessionLocal() as db:
        tasks = db.scalars(
            select(ProtocolTask)
            .where(ProtocolTask.protocol_id == protocol_id)
            .order_by(ProtocolTask.id)
        ).all()
        draft_id, parent_id = tasks[0].id, tasks[1].id

    saved = client.post(
        f"/protocols/{protocol_id}/editor/save",
        json={
            "tasks": [
                {
                    "id": draft_id,
                    "title": "Несохранённый текст секретаря",
                    "task_mode": "subtasks",
                    "parent_task_id": parent_id,
                }
            ]
        },
    )
    assert saved.status_code == 200
    assert client.post(f"/protocols/{protocol_id}/editor/tasks", json={}).status_code == 200
    created_section = client.post(
        f"/protocols/{protocol_id}/editor/sections", json={"title": "Решения комиссии"}
    )
    assert created_section.status_code == 200
    with SessionLocal() as db:
        draft = db.get(ProtocolTask, draft_id)
        section = db.get(ProtocolSection, created_section.json()["id"])
        assert draft.title == "Несохранённый текст секретаря"
        assert draft.parent_task_id == parent_id
        assert draft.create_as_subtasks is True
        assert section.title == "Решения комиссии"
        assert section.protocol_id == protocol_id
    assert sections
    teardown_protocol()
