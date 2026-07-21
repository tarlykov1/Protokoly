from fastapi.testclient import TestClient
from sqlalchemy import select

from app.cli.reset_demo import reset
from app.cli.seed_demo import seed
from app.core.config import get_settings
from app.db.base import Base
from app.db.models.domain import Protocol
from app.db.session import SessionLocal, engine
from app.main import app


def ensure_schema():
    Base.metadata.create_all(bind=engine)


def client_with_demo(monkeypatch, enabled=True):
    ensure_schema()
    monkeypatch.setenv("DEMO_MODE", "true" if enabled else "false")
    get_settings.cache_clear()
    return TestClient(app)


def test_demo_business_pages_and_empty_states(monkeypatch):
    ensure_schema()
    reset()
    client = client_with_demo(monkeypatch)
    for path in ["/demo", "/demo/dashboard", "/demo/guided", "/demo/complete"]:
        response = client.get(path)
        assert response.status_code == 200
        assert "Кабинет протокольных мероприятий" in response.text
    assert "Нет протоколов" in client.get("/protocols").text
    assert "Нет публикаций" in client.get("/demo/dashboard").text


def test_demo_seed_reset_docx_over_http(monkeypatch):
    client = client_with_demo(monkeypatch)
    token = client.get("/demo").text.split('name="csrf_token" value="')[1].split('"')[0]
    response = client.post("/demo/seed", data={"csrf_token": token}, follow_redirects=False)
    assert response.status_code == 303
    assert client.get("/demo/docx").status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(Protocol).where(Protocol.number == "DEMO-001")) is not None
    token = client.get("/demo").text.split('name="csrf_token" value="')[1].split('"')[0]
    response = client.post("/demo/reset", data={"confirm": "yes", "csrf_token": token}, follow_redirects=False)
    assert response.status_code == 303
    with SessionLocal() as db:
        assert db.scalar(select(Protocol).where(Protocol.number == "DEMO-001")) is None


def test_demo_actions_disabled_when_demo_mode_false(monkeypatch):
    client = client_with_demo(monkeypatch, enabled=False)
    token = client.get("/demo").text.split('name="csrf_token" value="')[1].split('"')[0]
    assert client.post("/demo/seed", data={"csrf_token": token}).status_code == 404
    assert client.post("/demo/reset", data={"confirm": "yes", "csrf_token": token}).status_code == 404
    assert client.get("/demo/docx").status_code == 404


def test_core_pages_render_and_mark_test_publication(monkeypatch):
    ensure_schema()
    reset()
    seed()
    client = client_with_demo(monkeypatch)
    for path in ["/", "/protocols", "/protocols/import", "/publication-runs", "/health"]:
        assert client.get(path).status_code == 200
    with SessionLocal() as db:
        protocol = db.scalar(select(Protocol).where(Protocol.number == "DEMO-001"))
        task = protocol.tasks[0]
    edit_html = client.get(f"/protocol-tasks/{task.id}/edit").text
    assert "Технический ID" not in edit_html
    assert "Основная информация" in edit_html
    plan_html = client.get(f"/protocols/{protocol.id}/publication-plan").text
    assert "Создать тестовые задачи" in plan_html
    assert "реальные задачи в Bitrix24 не создаются" in plan_html
    for width in [1440, 1024, 768, 390]:
        assert client.get(f"/demo/guided?viewport={width}").status_code == 200
