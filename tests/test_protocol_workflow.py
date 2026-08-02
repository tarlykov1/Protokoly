from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.domain import (
    Employee,
    Project,
    Protocol,
    ProtocolComment,
    ProtocolHistory,
    ProtocolSection,
    ProtocolTask,
    ProtocolTaskAssignment,
)
from app.services.protocols.workflow import WorkflowValidationError, transition_protocol


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session


def make_protocol(db: Session, *, valid: bool = True) -> Protocol:
    project = Project(name="Проект", code="WF")
    employee = Employee(full_name="Иванов И.И.", bitrix_user_id=101)
    db.add_all([project, employee])
    db.flush()
    protocol = Protocol(
        project_id=project.id,
        title="Протокол мероприятия",
        number="П-1" if valid else None,
        meeting_date=date(2026, 8, 2) if valid else None,
        created_by="Автор",
    )
    db.add(protocol)
    db.flush()
    section = ProtocolSection(protocol_id=protocol.id, title="Решения")
    db.add(section)
    db.flush()
    task = ProtocolTask(
        protocol_id=protocol.id,
        section_id=section.id,
        number="1",
        title="Исполнить решение",
        deadline=date(2026, 8, 10) if valid else None,
    )
    db.add(task)
    db.flush()
    if valid:
        db.add(ProtocolTaskAssignment(protocol_task_id=task.id, employee_id=employee.id))
    db.commit()
    return protocol


def test_protocol_is_created_as_draft(db):
    protocol = make_protocol(db)
    assert protocol.status == "draft"
    assert protocol.created_by == "Автор"


def test_all_allowed_status_transitions_create_history(db):
    protocol = make_protocol(db)
    chain = ["review", "approved", "published", "control", "completed"]
    for status in chain:
        transition_protocol(db, protocol, status, user="Секретарь", comment=f"В {status}")
    assert protocol.status == "completed"
    history = db.scalars(select(ProtocolHistory).order_by(ProtocolHistory.id)).all()
    assert [item.to_status for item in history] == chain
    assert history[0].user == "Секретарь"
    assert history[0].comment == "В review"
    assert history[0].created_at is not None


def test_invalid_transition_is_rejected_without_history(db):
    protocol = make_protocol(db)
    with pytest.raises(WorkflowValidationError, match="недопустим"):
        transition_protocol(db, protocol, "published", user="Автор")
    assert protocol.status == "draft"
    assert db.scalar(select(ProtocolHistory)) is None


def test_comment_is_persisted(db):
    protocol = make_protocol(db)
    comment = ProtocolComment(protocol=protocol, user="Рецензент", text="Нужно уточнение")
    db.add(comment)
    db.commit()
    saved = db.scalar(select(ProtocolComment))
    assert saved.text == "Нужно уточнение"
    assert saved.user == "Рецензент"
    assert saved.created_at is not None


def test_approval_is_blocked_when_protocol_or_tasks_have_errors(db):
    protocol = make_protocol(db, valid=False)
    transition_protocol(db, protocol, "review", user="Автор")
    with pytest.raises(WorkflowValidationError) as error:
        transition_protocol(db, protocol, "approved", user="Рецензент")
    assert "номер" in str(error.value)
    assert "Не выбран исполнитель" in str(error.value)
    assert "Не указан срок" in str(error.value)
    assert protocol.status == "review"
