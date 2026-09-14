"""Durable, single-worker integration queue with crash recovery."""
import time

from sqlalchemy import select

from app.core.locks import OperationBusy, operation_lock
from app.db.models.domain import IntegrationJob, Protocol
from app.db.session import SessionLocal
from app.services.project_access import configure_scope
from app.services.tasks.gateway import get_bitrix_gateway
from app.services.tasks.publication import PublicationService
from app.services.tasks.sync import BitrixTaskSyncService


def enqueue(db, protocol, kind, actor, update_existing=False):
    with operation_lock(db, f"queue:{protocol.id}"):
        existing = db.scalar(select(IntegrationJob).where(
            IntegrationJob.protocol_id == protocol.id,
            IntegrationJob.status.in_(["pending", "running"])))
        if existing:
            return existing
        job = IntegrationJob(protocol_id=protocol.id, kind=kind, requested_by=actor.username,
                             bitrix_user_id=db.info.get("bitrix_user_id", actor.bitrix_user_id),
                             update_existing=update_existing, status="pending")
        db.add(job)
        db.commit()
        return job


def run_next():
    with SessionLocal() as db:
        try:
            with operation_lock(db, "integration-worker"):
                job = db.scalar(select(IntegrationJob).where(IntegrationJob.status.in_(["pending", "running"])).order_by(IntegrationJob.id).limit(1))
                if not job:
                    return False
                job_id, protocol_id = job.id, job.protocol_id
                job.status = "running"
                db.commit()
                try:
                    from app.core.config import get_settings
                    if get_settings().bitrix_access_enabled:
                        configure_scope(db, job.bitrix_user_id, writable=True, username=job.requested_by)
                        if protocol_id not in [p.id for p in db.scalars(select(Protocol).where(Protocol.project_id.in_(db.info["project_write_scope"]))).all()]:
                            raise ValueError("Права на протокол отозваны")
                    protocol = db.get(Protocol, protocol_id)
                    if protocol is None:
                        raise ValueError("Протокол недоступен")
                    gateway = get_bitrix_gateway(db)
                    if job.kind == "publish":
                        PublicationService(db, gateway).publish(protocol, update_existing=job.update_existing)
                    else:
                        with operation_lock(db, f"protocol:{protocol_id}"):
                            result = BitrixTaskSyncService(db, gateway).sync(protocol)
                            if result.errors:
                                raise ValueError("; ".join(result.messages))
                    status, message = "done", "Операция завершена"
                except Exception:
                    db.rollback()
                    status, message = "failed", "Операция не завершена. Проверьте права, соединение и журнал интеграции; повторите после устранения причины"
                # Queue state is operational metadata, updated outside user scoping.
                db.info.pop("project_scope", None)
                db.expunge_all()
                job = db.get(IntegrationJob, job_id)
                job.status, job.message = status, message
                db.commit()
                return True
        except OperationBusy:
            return False
        finally:
            for client in db.info.pop("owned_http_clients", []):
                client.close()


def main():
    while True:
        if not run_next():
            time.sleep(2)


if __name__ == "__main__":
    main()
