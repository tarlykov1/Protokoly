from dataclasses import dataclass
from enum import StrEnum
from secrets import compare_digest
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from app.core.config import LOCAL_ENVIRONMENTS, get_settings


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

    def can(self, permission: Permission) -> bool:
        return permission in ROLE_PERMISSIONS[self.role]


def current_user(request: Request) -> CurrentUser:
    """Resolve identity supplied by the corporate authentication proxy.

    Local development retains the demo identity. Other environments require a
    trusted proxy secret plus an explicit identity and role on every request.
    """
    settings = get_settings()
    local = settings.environment.strip().lower() in LOCAL_ENVIRONMENTS
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
    return CurrentUser(request.headers.get("X-User", "system"), role)


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


def authorize_request(request: Request) -> None:
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
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if path.endswith(("/workflow", "/presence")):
        return  # Workflow service checks the requested transition's permission.
    if path.startswith("/demo/"):
        require_admin(request)
        return
    if path.endswith(("/publish", "/sync-bitrix", "/demo-publish", "/retry-failed")):
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
