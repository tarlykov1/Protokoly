from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from starlette.datastructures import Headers

from app.core.config import Settings
from app.db.base import Base
from app.db.models.domain import (
    Employee,
    IntegrationSettings,
    Project,
    Protocol,
    ProtocolDocumentVersion,
    ProtocolSection,
    ProtocolSignatory,
    ProtocolTask,
)
from app.db.session import get_db
from app.main import app
from app.services.imports.service import _validate_upload
from app.services.tasks.gateway import Bitrix24RestGateway, BitrixAPIError


@pytest.fixture
def editor_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="Audit", code="AUDIT")
        first = Protocol(project=project, title="Original", number="Ф-42")
        second = Protocol(project=project, title="Other")
        employee = Employee(full_name="Подписант")
        first.signatories.append(
            ProtocolSignatory(role="Председатель", name_snapshot="Подписант", employee=employee)
        )
        first.tasks.extend(
            [ProtocolTask(number="1", title="First"), ProtocolTask(number="2", title="Second")]
        )

        second.tasks.append(ProtocolTask(number="1", title="Other task"))
        db.add_all([first, second])
        db.flush()
        foreign_section = ProtocolSection(protocol_id=second.id, title="Foreign")
        db.add(foreign_section)
        db.commit()
        ids = {
            "protocol": first.id,
            "tasks": [task.id for task in first.tasks],
            "foreign_task": second.tasks[0].id,
            "foreign_section": foreign_section.id,
            "signatory": first.signatories[0].id,
            "employee": employee.id,
        }

    def session_override():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = session_override
    try:
        with TestClient(app) as client:
            yield client, engine, ids
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_inline_patch_preserves_signatory_identity_and_employee(editor_client):
    client, engine, ids = editor_client
    result = client.post(
        f"/protocols/{ids['protocol']}/editor/save",
        json={"version": 1, "signatory_updates": [{"id": ids["signatory"], "role": "Секретарь"}]},
    )
    assert result.status_code == 200
    assert result.json()["version"] == 2
    with Session(engine) as db:
        item = db.get(ProtocolSignatory, ids["signatory"])
        assert (item.role, item.employee_id, item.name_snapshot) == (
            "Секретарь",
            ids["employee"],
            "Подписант",
        )
    # Full editor round-trip preserves the same identity, too.
    result = client.post(
        f"/protocols/{ids['protocol']}/editor/save",
        json={
            "version": 2,
            "signatories": [
                {
                    "id": ids["signatory"],
                    "role": "Секретарь",
                    "name_snapshot": "Подписант",
                    "position_snapshot": "Начальник",
                }
            ],
        },
    )
    assert result.status_code == 200
    with Session(engine) as db:
        assert db.get(ProtocolSignatory, ids["signatory"]).employee_id == ids["employee"]


def test_stale_editor_cannot_overwrite_saved_changes(editor_client):
    client, engine, ids = editor_client
    url = f"/protocols/{ids['protocol']}/editor/save"
    assert client.post(url, json={"version": 1, "protocol": {"title": "New"}}).status_code == 200
    response = client.post(url, json={"version": 1, "protocol": {"title": "Stale"}})
    assert response.status_code == 409
    assert "другим пользователем" in response.json()["detail"]
    with Session(engine) as db:
        assert db.get(Protocol, ids["protocol"]).title == "New"


@pytest.mark.parametrize(
    "payload",
    [
        {"protocol": {"title": "Must rollback", "meeting_date": "bad-date"}},
        {"protocol": {"meeting_time": "25:90"}},
        {"tasks": "wrong-type"},
        {"tasks": [{"id": "invalid"}]},
    ],
)
def test_invalid_editor_payload_is_422_and_atomic(editor_client, payload):
    client, engine, ids = editor_client
    response = client.post(f"/protocols/{ids['protocol']}/editor/save", json=payload)
    assert response.status_code == 422
    with Session(engine) as db:
        protocol = db.get(Protocol, ids["protocol"])
        assert protocol.title == "Original" and protocol.version == 1


def test_foreign_task_section_and_cycles_rejected(editor_client):
    client, engine, ids = editor_client
    url = f"/protocols/{ids['protocol']}/editor/save"
    assert (
        client.post(url, json={"tasks": [{"id": ids["foreign_task"], "title": "bad"}]}).status_code
        == 404
    )
    assert (
        client.post(
            url, json={"tasks": [{"id": ids["tasks"][0], "section_id": ids["foreign_section"]}]}
        ).status_code
        == 422
    )
    a, b = ids["tasks"]
    assert (
        client.post(
            url,
            json={
                "tasks": [
                    {"id": a, "task_mode": "subtasks", "parent_task_id": b},
                    {"id": b, "task_mode": "subtasks", "parent_task_id": a},
                ]
            },
        ).status_code
        == 422
    )
    with Session(engine) as db:
        assert db.get(ProtocolTask, a).parent_task_id is None
        assert db.get(Protocol, ids["protocol"]).version == 1


@pytest.mark.parametrize(
    "path,method",
    [
        ("/protocols/1/editor/tasks", "post"),
        ("/protocols/1/publish", "post"),
        ("/employee-lists/1", "delete"),
        ("/settings/integrations", "get"),
    ],
)
def test_observer_cannot_use_legacy_write_routes(editor_client, path, method):
    client, _, _ = editor_client
    assert getattr(client, method)(path, headers={"X-User-Role": "observer"}).status_code == 403


def test_production_requires_trusted_proxy_and_identity(editor_client, monkeypatch):
    client, _, _ = editor_client
    monkeypatch.setattr(
        "app.services.auth.get_settings",
        lambda: Settings(environment="production", auth_proxy_secret="proxy-secret"),
    )
    assert client.get("/health").status_code == 200
    assert client.get("/protocols", headers={"X-User-Role": "administrator"}).status_code == 401
    assert (
        client.get(
            "/protocols",
            headers={
                "X-Auth-Proxy-Secret": "proxy-secret",
                "X-User": "test",
                "X-User-Role": "observer",
            },
        ).status_code
        == 200
    )


def test_docx_version_is_immutable_and_cyrillic_number_downloads(editor_client):
    client, engine, ids = editor_client
    url = f"/protocols/{ids['protocol']}/export/docx"
    first = client.get(url)
    assert first.status_code == 200
    assert "filename*=UTF-8''" in first.headers["content-disposition"]
    with Session(engine) as db:
        db.get(Protocol, ids["protocol"]).title = "Changed later"
        db.commit()
    assert client.get(url + "?version=1").content == first.content
    assert client.get(url).content != first.content
    assert client.get(url + "?version=999").status_code == 404
    with Session(engine) as db:
        legacy = db.scalar(
            select(ProtocolDocumentVersion).where(ProtocolDocumentVersion.version == 1)
        )
        legacy.content = None
        db.commit()
    assert client.get(url + "?version=1").status_code == 410


def test_compressed_docx_expansion_limit():
    data = BytesIO()
    with ZipFile(data, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"x" * (51 * 1024 * 1024))
    upload = UploadFile(
        file=BytesIO(data.getvalue()),
        filename="large.docx",
        headers=Headers({"content-type": "application/zip"}),
    )
    with pytest.raises(HTTPException) as caught:
        _validate_upload(upload, data.getvalue())
    assert caught.value.status_code == 413


def test_gateway_does_not_retry_uncertain_creations(editor_client):
    _, engine, _ = editor_client
    calls = []

    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("response lost")

    with Session(engine) as db, httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        gateway = Bitrix24RestGateway(
            IntegrationSettings(webhook_url="https://portal.test/rest/1/token"), db, client
        )
        with pytest.raises(BitrixAPIError):
            gateway.create_task({"title": "One task"})
        assert len(calls) == 1


def test_gateway_paginates_users_and_flattens_custom_fields(editor_client):
    import json

    _, engine, _ = editor_client
    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        if "user.get" in request.url.path:
            return httpx.Response(
                200,
                json={"result": [{"ID": "2"}]}
                if body.get("start") == 50
                else {"result": [{"ID": "1"}], "next": 50},
            )
        return httpx.Response(200, json={"result": True})

    with Session(engine) as db, httpx.Client(transport=httpx.MockTransport(respond)) as client:
        gateway = Bitrix24RestGateway(
            IntegrationSettings(webhook_url="https://portal.test/rest/1/token"), db, client
        )
        assert gateway.list_users() == [{"ID": "1"}, {"ID": "2"}]
        gateway.update_task(
            "1", {"title": "New", "assignee_raw": "Internal", "custom_fields": {"UF_TEST": "value"}}
        )
        assert calls[-1]["fields"] == {"TITLE": "New", "UF_TEST": "value"}


def test_cross_site_mutation_is_rejected(editor_client):
    client, _, ids = editor_client
    response = client.post(f"/protocols/{ids['protocol']}/editor/save", json={"protocol": {"title": "Forged"}}, headers={"Origin": "https://foreign.test"})
    assert response.status_code == 403
