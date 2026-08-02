from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db.base import Base
from app.db.models.domain import Project, Protocol, ProtocolSection, ProtocolTask
from app.db.session import SessionLocal, engine
from app.main import app


@pytest.fixture(autouse=True)
def clean_flow_data():
    yield
    with SessionLocal() as db:
        projects = db.scalars(select(Project).where(Project.code.like("FLOW-UI%"))).all()
        for project in projects:
            for protocol in list(project.protocols):
                for task in list(protocol.tasks):
                    db.delete(task)
                db.execute(
                    delete(ProtocolSection).where(ProtocolSection.protocol_id == protocol.id)
                )
                db.delete(protocol)
            db.delete(project)
        db.commit()


def setup_flow(code):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.execute(delete(Project).where(Project.code == code))
        project = Project(name="Workflow UI", code=code)
        db.add(project)
        db.commit()
        return project.id


def test_create_protocol_and_change_status_through_ui():
    project_id = setup_flow("FLOW-UI")
    client = TestClient(app)
    page = client.get("/protocols/new")
    assert page.status_code == 200 and "Инициатор" in page.text
    response = client.post(
        "/protocols",
        data={
            "project_id": project_id,
            "number": "UI-1",
            "title": "Совещание",
            "meeting_date": "2026-08-02",
            "initiator": "Иванов",
            "responsible": "Петров",
            "participants": "Сидоров",
            "description": "Описание",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303 and "created=1" in response.headers["location"]
    protocol_id = int(response.headers["location"].split("/")[2].split("?")[0])
    card = client.get(response.headers["location"])
    assert "Протокол создан" in card.text and "Отправить на проверку" in card.text
    client.post(f"/protocols/{protocol_id}/workflow", data={"action": "submit_review"})
    assert "Утвердить" in client.get(f"/protocols/{protocol_id}").text
    client.post(f"/protocols/{protocol_id}/workflow", data={"action": "approve"})
    with SessionLocal() as db:
        protocol = db.get(Protocol, protocol_id)
        assert protocol.status == "approved" and protocol.meeting_date == date(2026, 8, 2)


def test_manual_task_order_and_section_move_survive_reload():
    project_id = setup_flow("FLOW-UI-ORDER")
    client = TestClient(app)
    with SessionLocal() as db:
        protocol = Protocol(project_id=project_id, title="Порядок")
        db.add(protocol)
        db.flush()
        first = ProtocolSection(protocol_id=protocol.id, title="Первый", sort_order=1)
        second = ProtocolSection(protocol_id=protocol.id, title="Второй", sort_order=2)
        db.add_all([first, second])
        db.flush()
        protocol_id = protocol.id
        first_id, second_id = first.id, second.id
        db.commit()
    one = client.post(
        f"/protocols/{protocol_id}/editor/tasks", json={"title": "Один", "section_id": first_id}
    ).json()["id"]
    two = client.post(
        f"/protocols/{protocol_id}/editor/tasks", json={"title": "Два", "section_id": first_id}
    ).json()["id"]
    client.post(
        f"/protocols/{protocol_id}/editor/save",
        json={
            "tasks": [
                {"id": two, "position": 0, "section_id": second_id},
                {"id": one, "position": 1, "section_id": first_id},
            ]
        },
    )
    page = client.get(f"/protocols/{protocol_id}/editor")
    assert "Два" in page.text and "Один" in page.text
    with SessionLocal() as db:
        moved = db.get(ProtocolTask, two)
        assert moved.position == 0 and moved.section_id == second_id
