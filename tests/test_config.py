import pytest
from pydantic import ValidationError

from app.core.config import DEFAULT_ALLOWED_HOSTS, Settings


def test_allowed_hosts_accepts_comma_separated_string():
    settings = Settings(_env_file=None, allowed_hosts="demo.example.ru,localhost,127.0.0.1")

    assert settings.allowed_hosts == ["demo.example.ru", "localhost", "127.0.0.1"]


def test_allowed_hosts_accepts_json_array_from_environment(monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", '["demo.example.ru","localhost","127.0.0.1"]')

    settings = Settings(_env_file=None)

    assert settings.allowed_hosts == ["demo.example.ru", "localhost", "127.0.0.1"]


def test_allowed_hosts_accepts_ready_list():
    settings = Settings(_env_file=None, allowed_hosts=["demo.example.ru", "localhost"])

    assert settings.allowed_hosts == ["demo.example.ru", "localhost"]


def test_allowed_hosts_trims_spaces_and_removes_empty_values():
    settings = Settings(_env_file=None, allowed_hosts=" demo.example.ru, , localhost ,127.0.0.1, ")

    assert settings.allowed_hosts == ["demo.example.ru", "localhost", "127.0.0.1"]


def test_allowed_hosts_empty_string_uses_safe_default(monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", "")

    settings = Settings(_env_file=None)

    assert settings.allowed_hosts == DEFAULT_ALLOWED_HOSTS


def test_allowed_hosts_includes_localhost_in_demo_mode():
    settings = Settings(_env_file=None, demo_mode=True, allowed_hosts="")

    assert "localhost" in settings.allowed_hosts


def test_allowed_hosts_rejects_wildcard_in_production_like_mode():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="production", allowed_hosts="*")
