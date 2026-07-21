from fastapi.testclient import TestClient
from sqlalchemy import select

from app.cli.reset_demo import reset
from app.cli.seed_demo import seed
from app.core.config import get_settings
from app.db.base import Base
from app.db.models.domain import Protocol
from app.db.session import SessionLocal, engine
from app.main import app


def client(monkeypatch):
    Base.metadata.create_all(bind=engine)
    monkeypatch.setenv("DEMO_MODE", "true")
    get_settings.cache_clear()
    return TestClient(app)


def test_dashboard_metrics_badges_and_readiness(monkeypatch):
    reset()
    seed()
    c = client(monkeypatch)
    html = c.get("/dashboard").text
    assert c.get("/dashboard").status_code == 200
    for label in ["Проектов", "Протоколов", "Поручений", "Готово к публикации", "Требуют проверки", "Тестовых публикаций"]:
        assert label in html
    assert "readiness-track" in html
    assert "status-badge" in html
    assert "Технический ID" not in html


def test_protocol_filters_keep_query_and_active_navigation(monkeypatch):
    reset()
    seed()
    c = client(monkeypatch)
    html = c.get("/protocols?sort=title").text
    assert "name=\"q\"" in html
    assert "aria-current=\"page\"" in html
    assert "Реестр протоколов" in html
    assert "readiness-track" in html
    assert "Технический ID" not in html


def test_main_ui_pages_and_empty_states(monkeypatch):
    reset()
    c = client(monkeypatch)
    for path in [
        "/",
        "/dashboard",
        "/demo",
        "/demo/dashboard",
        "/projects",
        "/protocols",
        "/protocols/import",
        "/protocols/imports",
        "/publication-runs",
        "/health",
        "/ready",
    ]:
        response = c.get(path)
        assert response.status_code == 200
    assert "Нет протоколов" in c.get("/protocols").text
    assert "Нет импортов" in c.get("/protocols/imports").text


def test_protocol_card_and_guided_demo_use_shared_readiness(monkeypatch):
    reset()
    seed()
    c = client(monkeypatch)
    with SessionLocal() as db:
        protocol = db.scalar(select(Protocol).where(Protocol.number == "DEMO-001"))
    card = c.get(f"/protocols/{protocol.id}").text
    guided = c.get("/demo/guided?step=3").text
    assert "Готовность протокола" in card
    assert "Быстрые фильтры" in card
    assert "AI:" in card
    assert "Готовность демонстрационного протокола" in guided
    assert "readiness-track" in guided
