from __future__ import annotations

import importlib.metadata
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import sanitize_payload
from app.db.models.domain import (
    EditPresence,
    Employee,
    EmployeeSourceSettings,
    IntegrationLog,
    IntegrationSettings,
    Protocol,
    ProtocolTask,
    ProtocolTaskLink,
)

STARTED_AT = datetime.now(UTC)


def _revision(db: Session) -> tuple[str | None, str | None]:
    try:
        current = db.execute(text("select version_num from alembic_version")).scalar_one_or_none()
    except Exception:
        current = None
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    head = ScriptDirectory.from_config(config).get_current_head()
    return current, head


def _portal(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.hostname or "", "", "", ""))


def system_snapshot(db: Session) -> dict:
    settings = get_settings()
    current, head = _revision(db)
    bitrix = db.scalar(select(IntegrationSettings).where(IntegrationSettings.type == "bitrix24"))
    employee_source = db.scalar(select(EmployeeSourceSettings).order_by(EmployeeSourceSettings.id))
    last_log = db.scalar(select(IntegrationLog).order_by(IntegrationLog.id.desc()))
    last_success = db.scalar(
        select(IntegrationLog).where(IntegrationLog.status == "success").order_by(IntegrationLog.id.desc())
    )
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    errors = db.scalar(
        select(func.count()).select_from(IntegrationLog).where(
            IntegrationLog.status == "error", IntegrationLog.created_at >= cutoff
        )
    ) or 0
    broken_links = db.scalar(
        select(func.count()).select_from(ProtocolTaskLink).where(
            ProtocolTaskLink.external_task_id.in_((None, ""))
        )
    ) or 0
    try:
        version = importlib.metadata.version("protocol-management-system")
    except importlib.metadata.PackageNotFoundError:
        version = "development"
    migration_ok = bool(current and current == head)
    return sanitize_payload({
        "application": {"status": "healthy", "version": version, "environment": settings.environment,
                        "uptime_seconds": int((datetime.now(UTC) - STARTED_AT).total_seconds())},
        "database": {"status": "healthy" if migration_ok else "warning", "connected": True,
                     "type": db.bind.dialect.name, "current_revision": current,
                     "expected_head": head, "pending_migrations": not migration_ok},
        "bitrix24": {"status": "healthy" if bitrix and bitrix.enabled and (not last_log or last_log.status == "success") else "warning",
                     "mode": bitrix.mode if bitrix else "fake", "enabled": bool(bitrix and bitrix.enabled),
                     "portal": _portal(bitrix.portal_url) if bitrix else None,
                     "last_check": last_log.created_at if last_log else None,
                     "last_success": last_success.created_at if last_success else None,
                     "last_error": last_log.response if last_log and last_log.status == "error" else None},
        "employees": {"status": "error" if employee_source and employee_source.last_sync_status == "error" else "healthy",
                      "provider": employee_source.provider_type if employee_source else "manual",
                      "last_sync": employee_source.last_sync_at if employee_source else None,
                      "count": db.scalar(select(func.count()).select_from(Employee)) or 0,
                      "last_error": employee_source.last_sync_message if employee_source and employee_source.last_sync_status == "error" else None},
        "issues": {"status": "warning" if errors or broken_links else "healthy", "errors_24h": errors,
                   "tasks_with_sync_errors": errors, "published_without_link": broken_links},
    })


def readiness(db: Session) -> dict:
    current, head = _revision(db)
    counts = {
        "projects": db.scalar(select(func.count()).select_from(Protocol)),
        "tasks": db.scalar(select(func.count()).select_from(ProtocolTask)),
    }
    # Unit/demo databases can be bootstrapped with metadata.create_all and have no
    # alembic_version table; their critical-table reads above are the readiness proof.
    metadata_bootstrap = current is None and db.bind.dialect.name == "sqlite"
    if current != head and not metadata_bootstrap:
        raise RuntimeError(f"Ожидается миграция {head}, применена {current or 'нет'}")
    return {"status": "ready", "database": "ok", "revision": current or "metadata", "critical_tables": counts}


def touch_presence(db: Session, protocol_id: int, username: str, request_id: str) -> list[dict]:
    now = datetime.now(UTC)
    db.query(EditPresence).filter(EditPresence.last_seen_at < now - timedelta(seconds=90)).delete()
    presence = db.scalar(select(EditPresence).where(EditPresence.protocol_id == protocol_id, EditPresence.username == username))
    if presence:
        presence.last_seen_at = now
        presence.request_id = request_id
    else:
        db.add(EditPresence(protocol_id=protocol_id, username=username, request_id=request_id, last_seen_at=now))
    db.commit()
    active = db.scalars(select(EditPresence).where(EditPresence.protocol_id == protocol_id, EditPresence.last_seen_at >= now - timedelta(seconds=90))).all()
    return [{"username": item.username, "last_seen_at": item.last_seen_at} for item in active]
