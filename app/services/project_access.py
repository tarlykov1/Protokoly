"""Fail-closed project scope derived from current Bitrix24 group membership."""
from fastapi import HTTPException
from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session, with_loader_criteria

from app.db.base import Base
from app.db.models.domain import Project, ReportRun, SavedReportView
from app.services.tasks.gateway import Bitrix24RestGateway, get_bitrix_gateway


def group_role(gateway, group_id, user_id):
    members = gateway._list_all("sonet_group.user.get", {"ID": group_id})
    return next((str(row.get("ROLE", "")) for row in members
                 if str(row.get("USER_ID")) == str(user_id)), None)


def configure_scope(db, user_id=None, *, writable=False, username=""):
    gateway = get_bitrix_gateway(db)
    if not isinstance(gateway, Bitrix24RestGateway):
        raise HTTPException(503, "Для доступа к проектам подключите REST Битрикс24 в настройках интеграции")
    try:
        identity = gateway.check_connection()
        actual_id = int(identity.get("ID") or identity.get("id"))
        user_id = user_id or actual_id
        allowed = []
        write_ids = []
        roles = {}
        for project in db.scalars(select(Project)).all():
            if not project.bitrix_group_id:
                continue
            role = group_role(gateway, project.bitrix_group_id, user_id)
            roles[project.bitrix_group_id] = role
            if role in {"A", "E", "K"}:
                allowed.append(project.id)
            if role in {"A", "E"}:
                write_ids.append(project.id)
    except Exception as exc:
        raise HTTPException(503, "Не удалось проверить права в Битрикс24. Доступ закрыт до восстановления связи") from exc
    db.info["project_scope"] = tuple(allowed)
    db.info["project_write_scope"] = tuple(write_ids)
    db.info["scope_username"] = username
    db.info["bitrix_user_id"] = user_id
    db.info["group_roles"] = roles
    db.info["scope_gateway"] = gateway
    db.info["scope_writable"] = writable
    # Identity map must not bypass Session.get filtering after the unscoped discovery.
    db.expunge_all()
    return user_id


def _predicate(table, ids, seen=()):
    if table.name in seen:
        return None
    if table.name == "projects":
        return table.c.id.in_(ids)
    priority = {"project_id": 0, "protocol_id": 1, "protocol_task_id": 2}
    for foreign_key in sorted(table.foreign_keys, key=lambda fk: (priority.get(fk.parent.name, 10), fk.parent.name)):
        parent = foreign_key.column.table
        condition = _predicate(parent, ids, (*seen, table.name))
        if condition is not None:
            return foreign_key.parent.in_(select(foreign_key.column).where(condition))
    return None


@event.listens_for(Session, "do_orm_execute")
def scope_queries(state):
    ids = state.session.info.get("project_scope")
    if ids is None:
        return
    if state.is_select or state.is_update or state.is_delete:
        for mapper in Base.registry.mappers:
            cls = mapper.class_
            condition = _predicate(mapper.local_table, ids)
            if condition is not None:
                state.statement = state.statement.options(with_loader_criteria(cls, condition, include_aliases=True))
        username = state.session.info["scope_username"]
        for cls, column in ((ReportRun, ReportRun.user), (SavedReportView, SavedReportView.owner)):
            state.statement = state.statement.options(with_loader_criteria(cls, column == username, include_aliases=True))
    if state.is_update or state.is_delete:
        # Bulk mutations must use write scope, even after a collection-level read.
        table = state.statement.table
        condition = _predicate(table, state.session.info["project_write_scope"])
        if condition is not None:
            state.statement = state.statement.where(condition)


@event.listens_for(Session, "before_flush")
def guard_writes(db, _context, _instances):
    if "project_scope" not in db.info:
        return
    allowed = db.info["project_write_scope"]
    for obj in db.new | db.dirty | db.deleted:
        mapper = inspect(type(obj))
        condition = _predicate(mapper.local_table, allowed)
        if condition is None:
            continue
        if isinstance(obj, Project):
            role = db.info["group_roles"].get(obj.bitrix_group_id)
            if obj.bitrix_group_id and role is None:
                role = group_role(db.info["scope_gateway"], obj.bitrix_group_id, db.info["bitrix_user_id"])
            if role not in {"A", "E"}:
                raise HTTPException(403, "Изменять проект могут владелец и модераторы группы Битрикс24")
            continue
        # Resolve every project-bearing foreign key, including destination after a move.
        for fk in mapper.local_table.foreign_keys:
            parent = fk.column.table
            predicate = _predicate(parent, allowed)
            value = getattr(obj, fk.parent.name, None)
            if predicate is not None and value is not None:
                found = db.connection().scalar(select(fk.column).where(fk.column == value, predicate))
                if found is None:
                    raise HTTPException(403, "Нет права изменять этот проект или протокол")
