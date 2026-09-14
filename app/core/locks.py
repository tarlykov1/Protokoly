"""Cross-process operation locks; PostgreSQL locks survive business commits."""
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path

from filelock import FileLock, Timeout
from sqlalchemy import text

from app.core.config import get_settings


class OperationBusy(ValueError):
    pass


@contextmanager
def operation_lock(db, name: str):
    digest = sha256(name.encode()).hexdigest()
    engine = db.get_bind()
    if engine.dialect.name == "postgresql":
        key = int(digest[:15], 16)
        with engine.connect() as connection:
            acquired = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
            if not acquired:
                raise OperationBusy("Операция уже выполняется")
            try:
                yield
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
    else:
        folder = Path(get_settings().integration_lock_dir)
        folder.mkdir(parents=True, exist_ok=True)
        lock = FileLock(folder / f"{digest}.lock", thread_local=False)
        try:
            lock.acquire(timeout=0)
        except Timeout as exc:
            raise OperationBusy("Операция уже выполняется") from exc
        try:
            yield
        finally:
            lock.release()
