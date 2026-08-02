from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.domain import Project, Protocol, ProtocolTask, ProtocolTaskStatusHistory
from app.db.session import get_db
from app.main import app
from app.services.protocols.control import (
    ControlActor,
    InvalidStatusTransition,
    ProtocolControlService,
)


@pytest.fixture
def control_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'control.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        project = Project(name="Контроль", code="CONTROL")
        protocol = Protocol(project=project, title="Контрольный протокол", created_by="owner")
        protocol.tasks = [
            ProtocolTask(number="1", title="Выполнить поручение"),
            ProtocolTask(number="2", title="Просроченное", deadline=date.today() - timedelta(days=1)),
        ]
        db.add(protocol)
        db.commit()
        yield factory, db, protocol


def test_new_status_transition_history_and_persistence(control_database):
    factory, db, protocol = control_database
    task = protocol.tasks[0]
    assert task.status == "new"

    ProtocolControlService(db).change_status(
        task, "in_progress", ControlActor("owner"), "Начали работу"
    )
    history = db.scalar(select(ProtocolTaskStatusHistory))
    assert (history.old_status, history.new_status, history.comment, history.changed_by) == (
        "new", "in_progress", "Начали работу", "owner"
    )

    task_id = task.id
    db.close()
    with factory() as restarted:
        assert restarted.get(ProtocolTask, task_id).status == "in_progress"


def test_invalid_transition_and_automatic_overdue(control_database):
    _, db, protocol = control_database
    service = ProtocolControlService(db)
    with pytest.raises(InvalidStatusTransition):
        service.change_status(protocol.tasks[0], "completed", ControlActor("operator", "operator"))

    assert service.mark_overdue(list(protocol.tasks)) == 1
    assert protocol.tasks[1].status == "overdue"
    assert service.progress(list(protocol.tasks)).overdue == 1


def test_control_page_and_progress(control_database):
    _, db, protocol = control_database

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get(f"/protocols/{protocol.id}/control")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert "Контроль исполнения" in response.text
    assert "Просрочено: 1" in response.text
    assert "Выполнить поручение" in response.text


def test_control_requires_comment_and_completes_protocol(control_database):
    _, db, protocol = control_database
    service = ProtocolControlService(db)

    with pytest.raises(ValueError, match="комментарий"):
        service.update_control(protocol.tasks[0], "completed")

    service.update_control(protocol.tasks[0], "completed", "Готово", date.today())
    service.update_control(protocol.tasks[1], "completed", "Исполнено", date.today())

    assert protocol.status == "completed"
    assert protocol.tasks[0].control.result_comment == "Готово"
