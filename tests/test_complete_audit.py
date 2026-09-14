from datetime import date

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import Base
from app.db.models.domain import (
    Employee,
    IntegrationOperation,
    IntegrationSettings,
    Project,
    Protocol,
    ProtocolTask,
    ProtocolTaskAssignment,
    ProtocolTaskLink,
    PublicationSettings,
)
from app.services.project_access import configure_scope
from app.services.tasks.gateway import Bitrix24RestGateway, FakeBitrixGateway
from app.services.tasks.publication import PublicationService
from app.services.tasks.sync import BitrixTaskSyncService


@pytest.fixture
def sample(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'audit.db'}")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        employee = Employee(full_name="Главный", bitrix_user_id=11)
        other = Employee(full_name="Соисполнитель", bitrix_user_id=12)
        protocol = Protocol(project=Project(name="Доступен", code="A", bitrix_group_id=21), title="Протокол", status="approved")
        task = ProtocolTask(protocol=protocol, number="1", title="Результат", deadline=date(2030, 1, 1))
        task.assignments = [ProtocolTaskAssignment(employee=employee, sort_order=0), ProtocolTaskAssignment(employee=other, sort_order=1)]
        db.add(protocol)
        db.flush()
        task.primary_employee_id = employee.id
        db.commit()
        yield db, protocol, task


def test_primary_controls_completion_root_and_coperformer_do_not(sample):
    db, protocol, task = sample
    protocol.publication_settings = PublicationSettings(bitrix_project_id=21, parent_task_mode="root", default_responsible_id=99)
    gateway = FakeBitrixGateway()
    links = PublicationService(db, gateway).publish(protocol).links
    for link in links:
        gateway.update_task(link.external_task_id, {"status": "5" if link.responsible_id != 11 else "3"})
    BitrixTaskSyncService(db, gateway).sync(protocol)
    assert task.control.status == "in_progress"
    assert task.control.actual_date is None
    for link in links:
        gateway.update_task(link.external_task_id, {"status": "5" if link.responsible_id == 11 else "3"})
    BitrixTaskSyncService(db, gateway).sync(protocol)
    assert task.control.status == "completed"


def test_publication_recovers_timeout_after_remote_commit_without_duplicate(sample):
    db, protocol, task = sample
    class InterruptedGateway(FakeBitrixGateway):
        interrupted = False
        def create_task(self, payload):
            result = super().create_task(payload)
            if payload["responsible_id"] == 12 and not self.interrupted:
                self.interrupted = True
                raise TimeoutError("after remote commit")
            return result
    gateway = InterruptedGateway()
    service = PublicationService(db, gateway)
    with pytest.raises(TimeoutError):
        service.publish(protocol)
    assert len(db.scalars(select(ProtocolTaskLink)).all()) == 1
    assert protocol.status == "approved"
    assert db.scalar(select(IntegrationOperation).where(IntegrationOperation.status == "unknown"))
    result = service.publish(protocol)
    assert len(result.links) == 2
    assert len(gateway._tasks) == 2
    assert protocol.status == "published"


def test_gateway_does_not_commit_callers_transaction(sample):
    db, protocol, _ = sample
    settings = IntegrationSettings(type="bitrix24", webhook_url="https://example.test/rest/1/secret", mode="rest")
    db.add(settings)
    db.commit()
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"result": {"ID": 11}})))
    protocol.title = "Must rollback"
    Bitrix24RestGateway(settings, db, client).check_connection()
    db.rollback()
    assert db.get(Protocol, protocol.id).title == "Протокол"
    client.close()


def test_secrets_are_encrypted_at_rest(sample, tmp_path, monkeypatch):
    db, _, _ = sample
    key = tmp_path / "key"
    key.write_bytes(Fernet.generate_key())
    monkeypatch.setenv("SECRETS_KEY_FILE", str(key))
    get_settings.cache_clear()
    try:
        settings = IntegrationSettings(type="bitrix24", webhook_url="https://example.test/rest/1/secret", encrypted_token="token")
        db.add(settings)
        db.commit()
        raw = db.execute(text("SELECT webhook_url, encrypted_token FROM integration_settings")).one()
        assert all(value.startswith("fernet:v1:") for value in raw)
        db.expire_all()
        assert settings.encrypted_token == "token"
    finally:
        get_settings.cache_clear()


def test_project_scope_hides_direct_reads_and_blocks_mutations(sample, monkeypatch):
    db, protocol, task = sample
    hidden = Protocol(project=Project(name="Закрыт", code="B", bitrix_group_id=22), title="Скрыт")
    hidden_task = ProtocolTask(protocol=hidden, title="Скрытое поручение", number="1")
    db.add(hidden)
    settings = IntegrationSettings(type="bitrix24", mode="rest", enabled=True, webhook_url="https://example.test/rest/1/key")
    db.add(settings)
    db.commit()
    visible_id, hidden_id, task_id, visible_task_id = protocol.id, hidden.id, hidden_task.id, task.id
    monkeypatch.setattr(Bitrix24RestGateway, "check_connection", lambda self: {"ID": 11})
    monkeypatch.setattr(Bitrix24RestGateway, "_list_all", lambda self, method, payload: [{"USER_ID": "11", "ROLE": "K"}] if payload["ID"] == 21 else [])
    configure_scope(db, username="local")
    assert [row.id for row in db.scalars(select(Protocol)).all()] == [visible_id]
    assert db.get(Protocol, hidden_id) is None
    assert db.get(ProtocolTask, task_id) is None
    assert db.get(ProtocolTask, visible_task_id) is not None
    visible = db.get(Protocol, visible_id)
    visible.title = "Forbidden"
    with pytest.raises(HTTPException) as error:
        db.commit()
    assert error.value.status_code == 403
    db.rollback()
    for client in db.info.pop("owned_http_clients", []):
        client.close()


def test_worker_executes_persisted_job(sample, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from app.db.models.domain import IntegrationJob
    from app.services.auth import CurrentUser, Role
    from app.services.tasks import jobs
    db, protocol, _ = sample
    monkeypatch.setattr(jobs, "SessionLocal", sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    gateway = FakeBitrixGateway()
    monkeypatch.setattr(jobs, "get_bitrix_gateway", lambda db: gateway)
    job = jobs.enqueue(db, protocol, "publish", CurrentUser("operator", Role.ADMIN))
    assert jobs.enqueue(db, protocol, "publish", CurrentUser("operator", Role.ADMIN)).id == job.id
    assert jobs.run_next() is True
    db.expire_all()
    assert db.get(IntegrationJob, job.id).status == "done"
    assert db.get(Protocol, protocol.id).status == "published"
    assert len(gateway._tasks) == 2
    assert jobs.run_next() is False


def test_legacy_control_endpoint_rejects_stale_version(sample):
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import app
    db, protocol, task = sample
    engine = db.get_bind()
    def override_db():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            url = f"/protocol-tasks/{task.id}/control"
            first = client.post(url, data={"status": "in_progress", "protocol_version": protocol.version}, follow_redirects=False)
            assert first.status_code == 303
            stale = client.post(url, data={"status": "pending", "protocol_version": protocol.version}, follow_redirects=False)
            assert stale.status_code == 409
        db.expire_all()
        assert task.control.status == "in_progress"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_explicit_bitrix_rejection_can_be_retried(sample):
    from app.services.tasks.gateway import BitrixRejectedError
    db, protocol, _ = sample
    class RejectOnce(FakeBitrixGateway):
        rejected = False
        def create_task(self, payload):
            if not self.rejected:
                self.rejected = True
                raise BitrixRejectedError("invalid field")
            return super().create_task(payload)
    gateway = RejectOnce()
    service = PublicationService(db, gateway)
    with pytest.raises(BitrixRejectedError):
        service.publish(protocol)
    assert db.scalar(select(IntegrationOperation)).status == "pending"
    assert len(service.publish(protocol).links) == 2
    assert len(gateway._tasks) == 2


def test_group_reader_can_preview_and_download_without_writes(sample, monkeypatch):
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import app
    db, protocol, _ = sample
    db.add(IntegrationSettings(type="bitrix24", mode="rest", enabled=True, webhook_url="https://example.test/rest/1/key"))
    db.commit()
    protocol_id = protocol.id
    monkeypatch.setattr(Bitrix24RestGateway, "check_connection", lambda self: {"ID": 11})
    monkeypatch.setattr(Bitrix24RestGateway, "_list_all", lambda self, method, payload: [{"USER_ID": "11", "ROLE": "K"}])
    configure_scope(db, username="local")
    def override_db():
        yield db
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            for suffix in ("publication-plan", "control", "export/docx"):
                response = client.get(f"/protocols/{protocol_id}/{suffix}")
                assert response.status_code == 200, response.text[:200]
        assert db.get(Protocol, protocol_id).publication_settings is None
    finally:
        app.dependency_overrides.pop(get_db, None)
        for client in db.info.pop("owned_http_clients", []):
            client.close()
