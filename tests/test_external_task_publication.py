from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.domain import (
    Employee,
    Project,
    Protocol,
    ProtocolTask,
    ProtocolTaskAssignment,
    ProtocolTaskLink,
)
from app.services.tasks.gateway import FakeTaskGateway
from app.services.tasks.publication import PublicationNotAllowedError, PublicationService


@pytest.fixture
def publication_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'publication.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="Project", code="PUB", bitrix_group_id=10)
        employee = Employee(full_name="Прокофьев Д.Ю.", bitrix_user_id=20)
        protocol = Protocol(project=project, title="Протокол М-026/26", status="approved")
        task = ProtocolTask(
            protocol=protocol,
            number="1",
            title="Подготовить отчёт",
            deadline=date(2026, 8, 10),
        )
        task.assignments.append(ProtocolTaskAssignment(employee=employee))
        db.add(protocol)
        db.commit()
        yield db, protocol, task


def test_protocol_task_link_relationship(publication_db):
    db, _, task = publication_db
    link = ProtocolTaskLink(
        protocol_task=task,
        external_system="BITRIX24",
        external_task_id="TASK-10001",
        external_task_url="https://fake.tasks.local/TASK-10001",
    )
    db.add(link)
    db.commit()

    assert db.get(ProtocolTaskLink, link.id).protocol_task is task
    assert task.external_links == [link]


def test_approved_protocol_is_published_once(publication_db):
    db, protocol, _ = publication_db
    gateway = FakeTaskGateway()
    service = PublicationService(db, gateway)

    first = service.publish(protocol)
    second = service.publish(protocol)

    assert protocol.status == "published"
    assert [link.external_task_id for link in first.links] == ["TASK-10001"]
    assert second.reused is True
    assert db.scalars(select(ProtocolTaskLink)).all() == first.links
    assert gateway.get_status("TASK-10001") == "created"


@pytest.mark.parametrize("status", ["draft", "review"])
def test_unapproved_protocol_cannot_be_published(publication_db, status):
    db, protocol, _ = publication_db
    protocol.status = status
    db.commit()

    with pytest.raises(PublicationNotAllowedError):
        PublicationService(db, FakeTaskGateway()).publish(protocol)

    assert db.scalars(select(ProtocolTaskLink)).all() == []
