from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.domain import Employee, Protocol, ProtocolTaskControl, ProtocolTaskLink
from app.services.demo_publication import protocol_plan
from app.services.tasks.gateway import TaskGateway


class PublicationNotAllowedError(ValueError):
    pass


@dataclass(frozen=True)
class PublicationResult:
    links: list[ProtocolTaskLink]
    reused: bool = False
    warnings: tuple[str, ...] = ()

    @property
    def created_count(self) -> int:
        return len(self.links)


class PublicationService:
    """Publishes an approved protocol without depending on a concrete provider."""

    def __init__(self, db: Session, gateway: TaskGateway) -> None:
        self.db = db
        self.gateway = gateway

    def publish(self, protocol: Protocol) -> PublicationResult:
        existing = self._links(protocol)
        if existing:
            return PublicationResult(existing, reused=True)
        if protocol.status != "approved":
            raise PublicationNotAllowedError("Можно публиковать только утверждённый протокол")

        rows, errors, _ = protocol_plan(self.db, protocol)
        if errors:
            raise PublicationNotAllowedError("; ".join(errors))

        links = []
        warnings: list[str] = []
        for protocol_task, planned in rows:
            responsible_id = planned.responsible_id
            if responsible_id is None and planned.original_assignee:
                user = self.gateway.get_user(planned.original_assignee)
                if user:
                    responsible_id = int(user.get("ID") or user.get("id"))
                    employee = self.db.scalar(
                        select(Employee).where(Employee.full_name == planned.original_assignee)
                    )
                    if employee:
                        employee.bitrix_user_id = responsible_id
                        employee.is_available_in_bitrix = True
                else:
                    warnings.append(
                        f"Исполнитель «{planned.original_assignee}» не найден в Bitrix24; "
                        "задача создана без назначения."
                    )
            external = self.gateway.create_task(
                {
                    "title": planned.title,
                    "responsible_id": responsible_id,
                    "deadline": str(planned.deadline) if planned.deadline else None,
                    "parent_external_key": planned.parent_external_key,
                    "assignee_raw": planned.assignee_raw,
                    "original_assignee": planned.original_assignee,
                    "assignee_match_result": planned.assignee_match_result,
                    "missing_bitrix_id_reason": planned.missing_bitrix_id_reason,
                }
            )
            link = ProtocolTaskLink(
                protocol_task_id=protocol_task.id,
                external_system=self.gateway.external_system,
                external_task_id=str(external["id"]),
                external_task_url=external.get("url"),
                external_status=external.get("status"),
                last_synced_at=datetime.now(UTC),
            )
            self.db.add(link)
            links.append(link)
            if protocol_task.control is None:
                self.db.add(
                    ProtocolTaskControl(
                        protocol_task=protocol_task,
                        status="pending",
                        planned_date=protocol_task.deadline,
                    )
                )
        protocol.status = "published"
        self.db.commit()
        for link in links:
            self.db.refresh(link)
        return PublicationResult(links, warnings=tuple(warnings))

    def _links(self, protocol: Protocol) -> list[ProtocolTaskLink]:
        task_ids = [task.id for task in protocol.tasks]
        if not task_ids:
            return []
        return list(
            self.db.scalars(
                select(ProtocolTaskLink)
                .where(ProtocolTaskLink.protocol_task_id.in_(task_ids))
                .order_by(ProtocolTaskLink.id)
            ).all()
        )
