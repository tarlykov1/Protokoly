from dataclasses import dataclass
from enum import StrEnum

from fastapi import HTTPException, Request


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

    Administrator is the compatibility default until SSO middleware is configured.
    """
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
