"""Encrypt integration credentials with a key held outside the application DB."""
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.core.config import LOCAL_ENVIRONMENTS, get_settings

PREFIX = "fernet:v1:"


def cipher():
    settings = get_settings()
    if settings.secrets_key_file:
        return Fernet(Path(settings.secrets_key_file).read_bytes().strip())
    if settings.environment.lower() not in LOCAL_ENVIRONMENTS:
        raise ValueError("Не настроен файл ключа шифрования интеграций")
    return None


def encrypt(value):
    if not value or value.startswith(PREFIX):
        return value
    key = cipher()
    return PREFIX + key.encrypt(value.encode()).decode() if key else value


def decrypt(value):
    if not value or not value.startswith(PREFIX):
        return value
    key = cipher()
    if key is None:
        raise ValueError("Для чтения настроек требуется исходный ключ шифрования")
    return key.decrypt(value[len(PREFIX):].encode()).decode()


class SecretText(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt(value)

    def process_result_value(self, value, dialect):
        return decrypt(value)
