from sqlalchemy.orm import Session

from app.db.models.domain import Protocol, PublicationRun
from app.services.demo_publication import FakeBitrixGateway, run_publication


class PublicationService:
    """Application entry point for publishing an approved protocol.

    The gateway is injected so the production Bitrix adapter can replace the deterministic
    fake without changing workflow or HTTP handlers.
    """

    def __init__(self, gateway: FakeBitrixGateway | None = None):
        self.gateway = gateway or FakeBitrixGateway()

    def publish(
        self, db: Session, protocol: Protocol, *, fail_key: str | None = None
    ) -> tuple[PublicationRun | None, list[str]]:
        if protocol.status != "approved":
            return None, ["Публикация разрешена только для утвержденного протокола"]
        return run_publication(db, protocol, fail_key=fail_key, gateway=self.gateway)


__all__ = ["FakeBitrixGateway", "PublicationService"]
