from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.domain import (
    Protocol,
    ProtocolDocumentVersion,
    ProtocolHistory,
    ProtocolTask,
    ProtocolTaskControl,
)
from app.services.auth import CurrentUser, Permission

EVENT_LABELS = {
    "protocol_created": "Создание протокола",
    "protocol_details_changed": "Изменение реквизитов протокола",
    "protocol_signatories_changed": "Изменение подписной части",
    "task_text_changed": "Изменение текста поручения",
    "task_assignees_changed": "Изменение исполнителей",
    "task_deadline_changed": "Изменение срока",
    "status_changed": "Изменение статуса",
    "published": "Публикация",
    "bitrix_synced": "Синхронизация Bitrix24",
}


def record_event(db: Session, protocol: Protocol | int, event_type: str, user: str, **details):
    protocol_id = protocol if isinstance(protocol, int) else protocol.id
    event = ProtocolHistory(protocol_id=protocol_id, event_type=event_type, user=user, details=details)
    db.add(event)
    return event


TRANSITIONS = {
    ("draft", "submit_review"): ("review", Permission.EDIT),
    ("review", "return_draft"): ("draft", Permission.APPROVE),
    ("review", "approve"): ("approved", Permission.APPROVE),
    ("approved", "publish"): ("published", Permission.PUBLISH),
    ("published", "open_tasks"): ("control", Permission.PUBLISH),
    ("published", "sync"): ("published", Permission.PUBLISH),
    ("control", "complete"): ("completed", Permission.APPROVE),
}


def transition(db: Session, protocol: Protocol, action: str, actor: CurrentUser) -> str:
    target = TRANSITIONS.get((protocol.status, action))
    if target is None:
        raise ValueError("Недопустимый переход статуса")
    new_status, permission = target
    if not actor.can(permission):
        raise PermissionError(f"Недостаточно прав: {permission.value}")
    old_status = protocol.status
    protocol.status = new_status
    record_event(db, protocol, "status_changed", actor.username, old=old_status, new=new_status)
    if action == "publish":
        record_event(db, protocol, "published", actor.username)
    return new_status


def register_document(db: Session, protocol: Protocol, user: str) -> ProtocolDocumentVersion:
    version = (db.scalar(select(func.max(ProtocolDocumentVersion.version)).where(
        ProtocolDocumentVersion.protocol_id == protocol.id
    )) or 0) + 1
    item = ProtocolDocumentVersion(
        protocol_id=protocol.id, version=version, user=user,
        file_url=f"/protocols/{protocol.id}/export/docx?version={version}",
    )
    db.add(item)
    return item


def dashboard_metrics(db: Session, today: date | None = None) -> dict:
    today = today or date.today()
    statuses = dict(db.execute(select(Protocol.status, func.count()).group_by(Protocol.status)).all())
    task_count = db.scalar(select(func.count()).select_from(ProtocolTask)) or 0
    completed = db.scalar(select(func.count()).select_from(ProtocolTaskControl).where(
        ProtocolTaskControl.status == "completed"
    )) or 0
    overdue = db.scalar(select(func.count()).select_from(ProtocolTask).outerjoin(
        ProtocolTaskControl, ProtocolTaskControl.protocol_task_id == ProtocolTask.id
    ).where(ProtocolTask.deadline < today, func.coalesce(ProtocolTaskControl.status, "pending") != "completed")) or 0
    return {"statuses": statuses, "task_count": task_count,
            "completion_percent": int(completed * 100 / task_count) if task_count else 0,
            "overdue_count": overdue}
