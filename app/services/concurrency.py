"""Serialize protocol mutations and reject stale browser writes."""
from contextlib import ExitStack

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm.attributes import set_committed_value

from app.core.config import LOCAL_ENVIRONMENTS, get_settings
from app.core.locks import OperationBusy, operation_lock
from app.db.models.domain import Protocol, ProtocolTask


async def protect_mutation(request, db):
    if request.method in {"GET", "HEAD", "OPTIONS"} or request.url.path.endswith("/presence"):
        return
    protocol_id = request.path_params.get("protocol_id")
    task_id = request.path_params.get("task_id")
    if not protocol_id and task_id:
        task = db.get(ProtocolTask, task_id)
        if task:
            protocol_id = task.protocol_id
    if not protocol_id:
        return
    stack = db.info.setdefault("request_locks", ExitStack())
    try:
        stack.enter_context(operation_lock(db, f"protocol:{protocol_id}"))
    except OperationBusy as exc:
        raise HTTPException(409, "Документ сейчас изменяется. Повторите запрос") from exc
    protocol = db.get(Protocol, int(protocol_id))
    if protocol is None:
        raise HTTPException(404, "Протокол не найден")
    if "project_write_scope" in db.info and protocol.project_id not in db.info["project_write_scope"]:
        raise HTTPException(403, "Нет права изменять этот протокол")
    db.info["locked_protocol_id"] = protocol.id
    if request.url.path.endswith("/editor/save"):
        return  # This route performs its own atomic version claim.
    expected = request.headers.get("X-Protocol-Version")
    if not expected and "application/x-www-form-urlencoded" in request.headers.get("Content-Type", ""):
        form = await request.form()
        expected = form.get("protocol_version")
    if not expected:
        if get_settings().environment not in LOCAL_ENVIRONMENTS:
            raise HTTPException(428, "Обновите страницу документа перед изменением")
        expected = protocol.version
    try:
        expected = int(expected)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, "Некорректная версия документа") from exc
    result = db.execute(update(Protocol).where(Protocol.id == protocol.id, Protocol.version == expected)
                        .values(version=Protocol.version + 1).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise HTTPException(409, "Документ изменён другим пользователем. Обновите страницу")
    set_committed_value(protocol, "version", expected + 1)
    request.state.protocol_version = expected + 1
