from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models.domain import Protocol, ProtocolHistory
from app.services.protocols.editor import editor_errors

PROTOCOL_STATUSES = (
    "draft", "review", "approved", "published", "control", "completed", "returned"
)
TRANSITIONS = {
    "draft": "review",
    "review": "approved",
    "approved": "published",
    "published": "control",
    "control": "completed",
}


@dataclass(frozen=True)
class WorkflowValidationError(ValueError):
    errors: tuple[str, ...]

    def __str__(self) -> str:
        return "; ".join(self.errors)


def approval_errors(protocol: Protocol) -> list[str]:
    errors = []
    for label, value in (
        ("название", protocol.title),
        ("номер", protocol.number),
        ("дата мероприятия", protocol.meeting_date),
    ):
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(f"Не заполнено обязательное поле: {label}")
    if not protocol.tasks:
        errors.append("В протоколе нет поручений")
    for task in protocol.tasks:
        errors.extend(f"Поручение {task.number or '—'}: {error}" for error in editor_errors(task))
    return errors


def available_transition(protocol: Protocol) -> str | None:
    return TRANSITIONS.get(protocol.status)


def transition_protocol(
    db: Session,
    protocol: Protocol,
    target_status: str,
    *,
    user: str,
    comment: str | None = None,
) -> ProtocolHistory:
    if target_status not in PROTOCOL_STATUSES:
        raise WorkflowValidationError((f"Неизвестный статус: {target_status}",))
    expected = available_transition(protocol)
    if target_status != expected:
        raise WorkflowValidationError(
            (f"Переход {protocol.status} → {target_status} недопустим",)
        )
    if target_status == "approved":
        errors = approval_errors(protocol)
        if errors:
            raise WorkflowValidationError(tuple(errors))
    history = ProtocolHistory(
        protocol=protocol,
        from_status=protocol.status,
        to_status=target_status,
        user=user.strip() or "Система",
        comment=comment.strip() if comment and comment.strip() else None,
    )
    protocol.status = target_status
    db.add(history)
    db.commit()
    return history
