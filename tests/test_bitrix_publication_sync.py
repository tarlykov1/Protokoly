from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.domain import (
    Employee,
    Project,
    Protocol,
    ProtocolTask,
    ProtocolTaskAssignment,
    PublicationSettings,
)
from app.services.tasks.gateway import FakeBitrixGateway
from app.services.tasks.publication import PublicationService
from app.services.tasks.sync import BitrixTaskSyncService


def protocol_fixture(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'bitrix-publication.db'}")
    Base.metadata.create_all(engine)
    db = Session(engine)
    employee = Employee(full_name="Иванов И.И.", bitrix_user_id=17)
    protocol = Protocol(
        project=Project(name="Проект", code="B24", bitrix_group_id=44),
        number="7",
        title="Совещание",
        status="approved",
    )
    task = ProtocolTask(protocol=protocol, number="1", title="Сделать", deadline=date(2030, 1, 2))
    task.assignments.append(ProtocolTaskAssignment(employee=employee))
    db.add(protocol)
    db.commit()
    return db, protocol, task


def test_root_publication_passes_project_participants_and_is_idempotent(tmp_path):
    db, protocol, _ = protocol_fixture(tmp_path)
    protocol.publication_settings = PublicationSettings(
        bitrix_project_id=55,
        task_creator_id=9,
        parent_task_mode="root",
        default_responsible_id=21,
        accomplices=[22, 23],
        observers=[24],
    )
    db.commit()
    gateway = FakeBitrixGateway()
    service = PublicationService(db, gateway, "https://protocols.test/protocols")

    result = service.publish(protocol)
    repeated = service.publish(protocol)

    assert len(result.links) == 2
    root = gateway.get_task(result.links[0].external_task_id)
    child = gateway.get_task(result.links[1].external_task_id)
    assert child["parent_id"] == root["id"]
    assert child["group_id"] == 55
    assert child["created_by"] == 9
    assert child["responsible_id"] == 17  # instruction assignee wins over the default
    assert child["accomplices"] == [22, 23]
    assert child["auditors"] == [24]
    assert "https://protocols.test/protocols/1" in child["description"]
    assert repeated.reused is True
    assert len(gateway._tasks) == 2
    db.close()


def test_existing_task_can_be_updated(tmp_path):
    db, protocol, task = protocol_fixture(tmp_path)
    gateway = FakeBitrixGateway()
    service = PublicationService(db, gateway)
    first = service.publish(protocol)
    task.title = "Новое название"
    db.commit()

    result = service.publish(protocol, update_existing=True)

    assert result.updated_count == 1
    assert gateway.get_task(first.links[0].external_task_id)["title"] == "Новое название"
    db.close()


def test_sync_maps_completed_result_and_deadline(tmp_path):
    db, protocol, task = protocol_fixture(tmp_path)
    gateway = FakeBitrixGateway()
    link = PublicationService(db, gateway).publish(protocol).links[0]
    gateway.update_task(
        link.external_task_id,
        {"status": "5", "deadline": "2029-04-03", "closed_date": "2029-04-02", "result": "Готово"},
    )

    result = BitrixTaskSyncService(db, gateway).sync(protocol)

    assert (result.updated, result.errors) == (1, 0)
    assert task.control.status == "completed"
    assert task.control.actual_date == date(2029, 4, 2)
    assert task.control.result_comment == "Готово"
    assert link.external_status == "5"
    assert task.control.last_synced_at is not None
    db.close()


def test_sync_marks_overdue_and_reports_api_error(tmp_path):
    db, protocol, task = protocol_fixture(tmp_path)
    gateway = FakeBitrixGateway()
    link = PublicationService(db, gateway).publish(protocol).links[0]
    gateway.update_task(link.external_task_id, {"status": "3", "deadline": "2020-01-01"})
    assert BitrixTaskSyncService(db, gateway).sync(protocol).updated == 1
    assert task.control.status == "overdue"
    del gateway._tasks[link.external_task_id]
    failed = BitrixTaskSyncService(db, gateway).sync(protocol)
    assert failed.errors == 1
    db.close()
