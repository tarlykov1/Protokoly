import importlib
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app


def test_version_endpoint():
    r = TestClient(app).get('/version')
    assert r.status_code == 200
    assert {'version', 'commit', 'build_date'} <= set(r.json())


def test_health_headers_and_request_id():
    r = TestClient(app).get('/health', headers={'x-request-id': 'rid-test'})
    assert r.headers['x-request-id'] == 'rid-test'
    assert r.headers['x-content-type-options'] == 'nosniff'
    assert r.headers['x-frame-options'] == 'DENY'
    assert 'Content-Security-Policy' in r.headers


def test_trusted_host_blocks_unknown():
    r = TestClient(app).get('/health', headers={'host': 'evil.example'})
    assert r.status_code == 400


def test_secret_validation_production_like():
    settings = Settings(app_env='demo', secret_key='change-me')
    with pytest.raises(RuntimeError):
        settings.validate_runtime_security()


def test_public_base_url_setting():
    settings = Settings(public_base_url='https://demo.example.ru')
    assert settings.public_base_url == 'https://demo.example.ru'


def test_csrf_required_for_post():
    r = TestClient(app).post('/demo/seed')
    assert r.status_code == 403


def test_uploads_not_mounted_directly():
    r = TestClient(app).get('/uploads/demo.docx')
    assert r.status_code == 404


def test_shell_scripts_syntax():
    for script in Path('scripts').glob('*.sh'):
        subprocess.run(['bash', '-n', str(script)], check=True)


def test_ready_success():
    r = TestClient(app).get('/ready')
    assert r.status_code in {200, 503}
    assert 'checks' in r.json()


def test_ready_db_error(monkeypatch):
    main = importlib.import_module('app.main')
    class BadDB:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError('db down')
    response = main.ready(BadDB())
    assert response.status_code == 503
