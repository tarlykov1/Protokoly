from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.domain import Protocol, ProtocolTaskControl, ProtocolTaskLink
from app.services.demo_publication import protocol_plan
from app.services.tasks.gateway import TaskGateway


class PublicationNotAllowedError(ValueError):
    pass


@dataclass(frozen=True)
class PublicationResult:
    links: list[ProtocolTaskLink]
    reused: bool = False

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
        for protocol_task, planned in rows:
            external = self.gateway.create_task(
                {
                    "title": planned.title,
                    "responsible_id": planned.responsible_id,
                    "deadline": str(planned.deadline) if planned.deadline else None,
                    "parent_external_key": planned.parent_external_key,
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
        return PublicationResult(links)

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
