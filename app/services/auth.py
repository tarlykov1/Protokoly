from dataclasses import dataclass
from enum import StrEnum
from secrets import compare_digest
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import LOCAL_ENVIRONMENTS, get_settings
from app.db.session import get_db


class Role(StrEnum):
    ADMIN = "administrator"
    AUTHOR = "author"
    EDITOR = "editor"
    APPROVER = "approver"
    OBSERVER = "observer"


class Permission(StrEnum):
    CREATE = "create"
    EDIT = "edit"
    APPROVE = "approve"
    PUBLISH = "publish"
    DELETE = "delete"


ROLE_PERMISSIONS = {
    Role.ADMIN: set(Permission),
    Role.AUTHOR: {Permission.CREATE, Permission.EDIT},
    Role.EDITOR: {Permission.EDIT},
    Role.APPROVER: {Permission.APPROVE, Permission.PUBLISH},
    Role.OBSERVER: set(),
}


@dataclass(frozen=True)
class CurrentUser:
    username: str
    role: Role
    bitrix_user_id: int | None = None

    def can(self, permission: Permission) -> bool:
        return permission in ROLE_PERMISSIONS[self.role]


def current_user(request: Request) -> CurrentUser:
    """Resolve identity supplied by the corporate authentication proxy.

    Local development retains the demo identity. Other environments require a
    trusted proxy secret plus an explicit identity and role on every request.
    """
    settings = get_settings()
    local = settings.environment.strip().lower() in LOCAL_ENVIRONMENTS
    if settings.environment == "desktop":
        import base64
        from pathlib import Path
        try:
            scheme, encoded = request.headers.get("Authorization", "").split(" ", 1)
            username, password = base64.b64decode(encoded, validate=True).decode().split(":", 1)
            expected = Path(settings.local_password_file).read_text().strip()
            valid = scheme.lower() == "basic" and username == "local" and bool(expected) and compare_digest(password.encode(), expected.encode())
        except (ValueError, OSError, UnicodeError):
            valid = False
        if not valid:
            raise HTTPException(401, "Введите локальный пароль", headers={"WWW-Authenticate": 'Basic realm="Protokoly"'})
        return CurrentUser("local", Role.ADMIN)
    if not local:
        secret = settings.auth_proxy_secret.get_secret_value()
        if not secret:
            raise HTTPException(503, "Не настроена авторизация через корпоративный прокси")
        supplied = request.headers.get("X-Auth-Proxy-Secret", "")
        if not compare_digest(supplied.encode(), secret.encode()):
            raise HTTPException(401, "Требуется корпоративная авторизация")
        if not request.headers.get("X-User", "").strip() or not request.headers.get("X-User-Role"):
            raise HTTPException(401, "Не переданы пользователь и роль")
    raw_role = request.headers.get("X-User-Role", Role.ADMIN)
    try:
        role = Role(raw_role)
    except ValueError as exc:
        raise HTTPException(401, "Неизвестная роль пользователя") from exc
    bitrix_id = None
    if not local:
        try:
            bitrix_id = int(request.headers.get("X-Bitrix-User-ID", ""))
        except ValueError:
            if settings.bitrix_access_enabled:
                raise HTTPException(401, "Прокси должен передать подтверждённый ID пользователя Битрикс24") from None
    return CurrentUser(request.headers.get("X-User", "system"), role, bitrix_id)


def require(permission: Permission):
    def dependency(request: Request) -> CurrentUser:
        user = current_user(request)
        if not user.can(permission):
            raise HTTPException(403, f"Недостаточно прав: {permission.value}")
        return user

    return dependency


def require_admin(request: Request) -> CurrentUser:
    user = current_user(request)
    if user.role is not Role.ADMIN:
        raise HTTPException(403, "Раздел доступен только администратору")
    return user


async def _authorize_request(request: Request, db: Session = Depends(get_db)) -> None:
    """Cover all application routes, including legacy handlers without Depends."""
    path = request.scope.get("route").path
    if path in {"/health", "/ready"}:
        return
    user = current_user(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("Origin")
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            raise HTTPException(403, "Межсайтовый запрос запрещён")
        if origin:
            parsed = urlsplit(origin)
            if (parsed.scheme, parsed.netloc) != (request.url.scheme, request.url.netloc):
                raise HTTPException(403, "Источник запроса не совпадает с приложением")
    if path.startswith(("/settings/", "/system/")):
        require_admin(request)
        return
    if get_settings().bitrix_access_enabled:
        from app.services.project_access import configure_scope
        configure_scope(db, user.bitrix_user_id, writable=request.method not in {"GET", "HEAD", "OPTIONS"}, username=user.username)
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if path.endswith(("/workflow", "/presence")):
        return  # Workflow service checks the requested transition's permission.
    if path.startswith("/demo/"):
        require_admin(request)
        return
    if path.endswith(("/publish", "/sync-bitrix", "/demo-publish", "/retry-failed", "/reconcile")):
        permission = Permission.PUBLISH
    elif request.method == "DELETE" or path.endswith("/delete"):
        permission = Permission.DELETE
    elif path in {
        "/protocols",
        "/protocols/create",
        "/projects",
        "/protocols/import/preview",
    } or path.endswith("/confirm"):
        permission = Permission.CREATE
    else:
        permission = Permission.EDIT
    if not user.can(permission):
        raise HTTPException(403, f"Недостаточно прав: {permission.value}")


async def authorize_request(request: Request, db: Session = Depends(get_db)):
    try:
        await _authorize_request(request, db)
        from app.services.concurrency import protect_mutation
        await protect_mutation(request, db)
        yield
    finally:
        locks = db.info.pop("request_locks", None)
        if locks:
            locks.close()
