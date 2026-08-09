from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.domain import Protocol, ProtocolTaskControl, ProtocolTaskLink
from app.services.tasks.gateway import TaskGateway


@dataclass(frozen=True)
class SyncResult:
    updated: int
    errors: int
    synced_at: datetime
    messages: tuple[str, ...] = ()


class BitrixTaskSyncService:
    """Pull Bitrix execution data into local protocol controls."""

    STATUS_MAP = {
        "1": "pending", "2": "pending", "3": "in_progress", "4": "waiting_control",
        "5": "completed", "pending": "pending", "new": "pending", "in progress": "in_progress",
        "in_progress": "in_progress", "waiting control": "waiting_control",
        "waiting_control": "waiting_control", "completed": "completed",
    }

    def __init__(self, db: Session, gateway: TaskGateway):
        self.db, self.gateway = db, gateway

    def sync(self, protocol: Protocol) -> SyncResult:
        now = datetime.now(UTC)
        ids = [task.id for task in protocol.tasks]
        links = self.db.scalars(select(ProtocolTaskLink).where(ProtocolTaskLink.protocol_task_id.in_(ids or [0]))).all()
        updated = errors = 0
        messages = []
        for link in links:
            try:
                remote = self.gateway.get_task(link.external_task_id)
                if not remote:
                    raise ValueError("задача не найдена")
                raw_status = str(remote.get("status", "")).lower()
                status = self.STATUS_MAP.get(raw_status, "pending")
                control = link.protocol_task.control
                if control is None:
                    control = ProtocolTaskControl(protocol_task=link.protocol_task)
                    self.db.add(control)
                deadline = self._date(remote.get("deadline")) or control.planned_date or link.protocol_task.deadline
                control.planned_date = deadline
                control.status = "overdue" if status != "completed" and deadline and deadline < date.today() else status
                closed = self._date(remote.get("closed_date") or remote.get("closeddate"))
                if status == "completed":
                    control.actual_date = closed or date.today()
                control.result_comment = remote.get("result") or remote.get("result_comment") or control.result_comment
                control.last_synced_at = link.last_synced_at = now
                link.external_status = raw_status
                updated += 1
            except Exception as exc:
                errors += 1
                messages.append(f"{link.external_task_id}: {exc}")
        self.db.commit()
        return SyncResult(updated, errors, now, tuple(messages))

    @staticmethod
    def _date(value):
        if not value:
            return None
        if isinstance(value, date):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
        except ValueError:
            return None
