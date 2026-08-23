from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.domain import (
    Project,
    Protocol,
    ProtocolSection,
    ProtocolTask,
    ProtocolTaskAssignment,
)
from app.db.session import get_db
from app.main import app
from app.services.imports.service import _task_assignees
from app.services.tasks.gateway import FakeBitrixGateway
from app.services.tasks.publication import PublicationNotAllowedError, PublicationService
from app.services.validation import ProtocolValidationService


def validation_protocol(db: Session) -> tuple[Protocol, ProtocolTask]:
    project = Project(name="Валидация", code="VALIDATION")
    protocol = Protocol(
        project=project,
        title="Импортированный протокол",
        status="approved",
        source_type="docx_import",
    )
    db.add(protocol)
    db.flush()
    section = ProtocolSection(protocol_id=protocol.id, title="Решили")
    db.add(section)
    db.flush()
    task = ProtocolTask(
        protocol=protocol,
        section_id=section.id,
        number="1",
        title="Подготовить отчёт",
        deadline=date(2030, 1, 1),
    )
    db.add(task)
    db.flush()
    task.assignments.append(
        ProtocolTaskAssignment(employee_id=None, individual_title="Неизвестный Сотрудник")
    )
    db.commit()
    return protocol, task


def test_unknown_imported_assignee_keeps_only_name_snapshot():
    assignees = _task_assignees(
        {
            "assignee_resolution": [
                {"raw": "Неизвестный Сотрудник", "status": "not_found"}
            ]
        }
    )

    assert assignees == [
        {
            "employee_id": None,
            "employee_list_id": None,
            "raw_name": "Неизвестный Сотрудник",
        }
    ]


def test_employee_not_found_is_aggregated_and_increases_error_statistics():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        protocol, task = validation_protocol(db)
        result = ProtocolValidationService().validate(protocol)
        assert [issue.code for issue in result.errors] == ["employee_not_found"]
        assert task.assignments[0].employee is None
        assert task.assignments[0].name_snapshot == "Неизвестный Сотрудник"

        task.assignments.clear()
        db.flush()
        increased = ProtocolValidationService().validate(protocol)
        assert len(increased.errors) == len(result.errors)
        assert increased.errors[0].code == "assignee_required"


def test_protocol_card_displays_aggregated_unresolved_error():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    protocol, _ = validation_protocol(db)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get(f"/protocols/{protocol.id}")
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()

    assert response.status_code == 200
    assert "Нерешённые ошибки и предупреждения" in response.text
    assert "employee_not_found" in response.text
    assert "Ошибок" in response.text


def test_publication_is_blocked_by_critical_protocol_error():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        protocol, _ = validation_protocol(db)
        with pytest.raises(PublicationNotAllowedError, match="Пользователь не найден"):
            PublicationService(db, FakeBitrixGateway()).publish(protocol)
