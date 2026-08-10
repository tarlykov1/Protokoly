from contextlib import suppress

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.security import REDACTED, mask_secret, sanitize_payload
from app.db.base import Base
from app.db.models.domain import IntegrationLog, IntegrationSettings
from app.main import app
from app.services.tasks.gateway import Bitrix24RestGateway, BitrixAPIError


def test_secret_masking_is_recursive_and_masks_webhook_path():
    result = sanitize_payload({"access_token": "top-secret", "Authorization": "Bearer secret", "nested": {"password": "db-pass"}, "url": "https://portal.test/rest/1/token/tasks.json?access_token=x"})
    assert mask_secret("secret") == REDACTED
    rendered = str(result)
    for secret in ("top-secret", "Bearer secret", "db-pass", "/1/token", "access_token=x"):
        assert secret not in rendered


def test_bitrix_retry_and_sanitized_integration_log(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    attempts = 0

    def timeout(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("timeout")

    with Session(engine) as db:
        settings = IntegrationSettings(type="bitrix24", webhook_url="https://portal.test/rest/1/secret-token")
        gateway = Bitrix24RestGateway(settings, db)
        monkeypatch.setattr(gateway.client, "post", timeout)
        monkeypatch.setattr("app.services.tasks.gateway.time.sleep", lambda _: None)
        with suppress(BitrixAPIError):
            gateway.check_connection()
        assert attempts == 3
        log = db.scalar(select(IntegrationLog))
        assert log.attempts == 3
        assert "secret-token" not in str(log.request) + str(log.response)


def test_request_id_is_preserved_and_diagnostics_is_admin_only():
    client = TestClient(app)
    response = client.get("/health", headers={"X-Request-ID": "pilot-check"})
    assert response.headers["X-Request-ID"] == "pilot-check"
    assert client.get("/system/diagnostics", headers={"X-User-Role": "observer"}).status_code == 403
