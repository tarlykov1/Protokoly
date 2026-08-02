import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.domain import IntegrationLog, IntegrationSettings
from app.services.tasks.gateway import (
    Bitrix24RestGateway,
    BitrixAPIError,
    FakeBitrixGateway,
    get_bitrix_gateway,
)


@pytest.fixture
def integration_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'integration.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def test_integration_settings_are_saved(integration_db):
    settings = IntegrationSettings(type="bitrix24", mode="rest", portal_url="https://portal.test")
    integration_db.add(settings)
    integration_db.commit()

    stored = integration_db.scalar(select(IntegrationSettings))
    assert stored.mode == "rest"
    assert stored.portal_url == "https://portal.test"


def test_gateway_selection_defaults_to_fake(integration_db):
    assert isinstance(get_bitrix_gateway(integration_db), FakeBitrixGateway)

    integration_db.add(
        IntegrationSettings(
            type="bitrix24", mode="rest", webhook_url="https://portal.test/rest/1/token"
        )
    )
    integration_db.commit()
    assert isinstance(get_bitrix_gateway(integration_db), Bitrix24RestGateway)


def test_rest_gateway_checks_connection_and_logs_call(integration_db):
    def handler(request):
        assert request.url.path.endswith("/user.current.json")
        return httpx.Response(200, json={"result": {"ID": "7", "NAME": "Иван"}})

    settings = IntegrationSettings(
        type="bitrix24", mode="rest", webhook_url="https://portal.test/rest/1/token"
    )
    integration_db.add(settings)
    integration_db.commit()
    client = httpx.Client(transport=httpx.MockTransport(handler))

    assert Bitrix24RestGateway(settings, integration_db, client).check_connection()["ID"] == "7"
    log = integration_db.scalar(select(IntegrationLog))
    assert (log.operation, log.status) == ("user.current", "success")


def test_rest_gateway_converts_api_error_and_logs_it(integration_db):
    settings = IntegrationSettings(
        type="bitrix24", mode="rest", webhook_url="https://portal.test/rest/1/token"
    )
    integration_db.add(settings)
    integration_db.commit()
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"error": "INVALID_CREDENTIALS", "error_description": "Bad token"}
            )
        )
    )

    with pytest.raises(BitrixAPIError, match="Bad token"):
        Bitrix24RestGateway(settings, integration_db, client).get_task("42")
    assert integration_db.scalar(select(IntegrationLog)).status == "error"


def test_rest_gateway_creates_task_with_bitrix_payload(integration_db):
    def handler(request):
        assert request.url.path.endswith("/tasks.task.add.json")
        assert b'"RESPONSIBLE_ID":17' in request.content
        return httpx.Response(200, json={"result": {"task": {"id": "321"}}})

    settings = IntegrationSettings(
        type="bitrix24",
        mode="rest",
        portal_url="https://portal.test",
        webhook_url="https://portal.test/rest/1/token",
    )
    integration_db.add(settings)
    integration_db.commit()
    gateway = Bitrix24RestGateway(
        settings, integration_db, httpx.Client(transport=httpx.MockTransport(handler))
    )

    result = gateway.create_task({"title": "Подготовить отчёт", "responsible_id": 17})
    assert result["id"] == "321"
    assert result["url"].endswith("/tasks/task/view/321/")
