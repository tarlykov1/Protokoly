from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.locks import operation_lock
from app.db.models.domain import (
    IntegrationOperation,
    Protocol,
    ProtocolSection,
    ProtocolTaskControl,
    ProtocolTaskLink,
    PublicationSettings,
)
from app.services.demo_publication import protocol_plan
from app.services.tasks.gateway import BitrixRejectedError, TaskGateway
from app.services.validation import ProtocolValidationService


class PublicationNotAllowedError(ValueError):
    pass


@dataclass(frozen=True)
class PublicationPreview:
    task_count: int
    project_id: int | None
    missing_employees: tuple[str, ...]
    missing_bitrix_ids: tuple[str, ...]
    missing_deadlines: tuple[str, ...]
    errors: tuple[str, ...]
    existing_links: tuple[ProtocolTaskLink, ...]


@dataclass(frozen=True)
class PublicationResult:
    links: list[ProtocolTaskLink]
    reused: bool = False
    warnings: tuple[str, ...] = ()
    updated_count: int = 0

    @property
    def created_count(self) -> int:
        return 0 if self.reused else len(self.links) - self.updated_count


class PublicationService:
    """Idempotent publication of approved protocols using persisted Bitrix choices."""

    def __init__(self, db: Session, gateway: TaskGateway, protocol_base_url: str = "/protocols"):
        self.db = db
        self.gateway = gateway
        self.protocol_base_url = protocol_base_url.rstrip("/")

    def settings_for(self, protocol: Protocol, *, persist: bool = True) -> PublicationSettings:
        if protocol.publication_settings is None and not persist:
            return PublicationSettings(bitrix_project_id=protocol.project.bitrix_group_id,
                parent_task_mode="separate", accomplices=[], observers=[], custom_fields={}, add_protocol_link=True)
        if protocol.publication_settings is None:
            protocol.publication_settings = PublicationSettings(
                bitrix_project_id=protocol.project.bitrix_group_id
            )
            self.db.flush()
        return protocol.publication_settings

    def preview(self, protocol: Protocol) -> PublicationPreview:
        settings = self.settings_for(protocol, persist=False)
        rows, plan_errors, _ = protocol_plan(self.db, protocol, refresh=False)
        missing_employees: list[str] = []
        missing_ids: list[str] = []
        missing_deadlines: list[str] = []
        for task, planned in rows:
            if not planned.original_assignee:
                missing_employees.append(task.number)
            elif planned.responsible_id is None:
                missing_ids.append(planned.original_assignee)
            if not planned.deadline:
                missing_deadlines.append(task.number)
        count = len(rows) + (settings.parent_task_mode != "separate" and bool(rows))
        errors = list(plan_errors)
        if settings.bitrix_project_id is None:
            errors.append("Не выбран проект Bitrix24")
        if missing_ids and settings.default_responsible_id is None:
            errors.append("У исполнителей отсутствуют Bitrix user ID и не задан ответственный по умолчанию")
        return PublicationPreview(
            count,
            settings.bitrix_project_id,
            tuple(dict.fromkeys(missing_employees)),
            tuple(dict.fromkeys(missing_ids)),
            tuple(dict.fromkeys(missing_deadlines)),
            tuple(errors),
            tuple(self._links(protocol)),
        )

    def publish(self, protocol: Protocol, *, update_existing: bool = False) -> PublicationResult:
        if self.db.info.get("locked_protocol_id") == protocol.id:
            return self._publish(protocol, update_existing=update_existing)
        with operation_lock(self.db, f"protocol:{protocol.id}"):
            return self._publish(protocol, update_existing=update_existing)

    def _publish(self, protocol: Protocol, *, update_existing: bool) -> PublicationResult:
        existing = self._links(protocol)
        if any(link.publication_key is None for link in existing):
            raise PublicationNotAllowedError(
                "Существующие связи созданы старой версией: сначала сопоставьте их с поручениями в журнале интеграции"
            )
        if protocol.status not in {"approved", "published"}:
            raise PublicationNotAllowedError("Можно публиковать только утверждённый протокол")
        settings = self.settings_for(protocol)
        rows, errors, _ = protocol_plan(self.db, protocol)
        validation = ProtocolValidationService().validate(protocol)
        if not validation.can_publish:
            raise PublicationNotAllowedError(
                "Публикация заблокирована: "
                + "; ".join(
                    f"{issue.task_number}: {issue.message}" if issue.task_number else issue.message
                    for issue in validation.errors
                )
            )
        # Keep compatibility for installations that used project defaults before settings existed.
        if errors:
            raise PublicationNotAllowedError("; ".join(errors))
        from app.core.config import get_settings
        if get_settings().bitrix_access_enabled and settings.bitrix_project_id != protocol.project.bitrix_group_id:
            raise PublicationNotAllowedError("Группа публикации должна совпадать с группой выбранного проекта")
        if not rows:
            raise PublicationNotAllowedError("Нет поручений для публикации")
        if any(planned.responsible_id is None and settings.default_responsible_id is None for _, planned in rows):
            raise PublicationNotAllowedError("Не сопоставлен исполнитель с ID пользователя Битрикс24")
        # Parent instructions precede children independently of display order.
        def depth(task):
            parents = {item.id: item.parent_task_id for item in protocol.tasks}
            seen = set()
            parent = task.parent_task_id
            while parent:
                if parent in seen or parent == task.id:
                    raise PublicationNotAllowedError("Циклическая структура поручений")
                seen.add(parent)
                parent = parents.get(parent)
            return len(seen)
        rows.sort(key=lambda row: (depth(row[0]), row[0].position, row[1].task_type != "root"))
        expected_keys = {f"protocol:{protocol.id}:task:{task.id}:{planned.task_type}:{planned.responsible_id or settings.default_responsible_id}" for task, planned in rows}
        if settings.parent_task_mode != "separate":
            expected_keys.add(f"protocol:{protocol.id}:root")
        if any(link.publication_key not in expected_keys for link in existing):
            raise PublicationNotAllowedError("Состав исполнителей или режим изменён после публикации. Сначала сопоставьте существующие связи")

        links: list[ProtocolTaskLink] = []
        updated = reused = 0
        parent_ids: dict[int, str] = {}
        planned_ids: dict[str, str] = {}
        root_id = None
        if settings.parent_task_mode != "separate" and rows:
            payload = self._root_payload(protocol, settings)
            key = f"protocol:{protocol.id}:root"
            link, was_reused = self._publish_one(protocol, rows[0][0].id, key, "protocol_root", payload, update_existing)
            root_id = link.external_task_id
            links.append(link)
            reused += was_reused
            updated += was_reused and update_existing
        for task, planned in rows:
            responsible_id = planned.responsible_id or settings.default_responsible_id
            if responsible_id is None:
                raise PublicationNotAllowedError("Не сопоставлен исполнитель с ID пользователя Битрикс24")
            parent_id = planned_ids.get(planned.parent_external_key) or parent_ids.get(task.parent_task_id) or root_id
            payload = self._task_payload(protocol, task, planned, settings, responsible_id, parent_id)
            key = f"protocol:{protocol.id}:task:{task.id}:{planned.task_type}:{responsible_id}"
            kind = "task_root" if planned.task_type == "root" else "instruction"
            link, was_reused = self._publish_one(protocol, task.id, key, kind, payload, update_existing)
            links.append(link)
            reused += was_reused
            updated += was_reused and update_existing
            planned_ids[planned.external_key] = link.external_task_id
            parent_ids.setdefault(task.id, link.external_task_id)
            if task.control is None:
                self.db.add(ProtocolTaskControl(protocol_task=task, status="pending", planned_date=task.deadline))
        protocol.status = "published"
        if self.db.info.get("locked_protocol_id") != protocol.id:
            protocol.version += 1
        self.db.commit()
        return PublicationResult(links, reused=reused == len(links) and not update_existing, updated_count=reused)

    def _publish_one(self, protocol, task_id, key, kind, payload, update_existing):
        link = self.db.scalar(select(ProtocolTaskLink).where(ProtocolTaskLink.publication_key == key))
        if link:
            if update_existing:
                self.gateway.update_task(link.external_task_id, payload)
                link.last_synced_at = datetime.now(UTC)
                link.responsible_id = payload.get("responsible_id")
                self.db.commit()
            return link, True
        operation = self.db.scalar(select(IntegrationOperation).where(IntegrationOperation.operation_key == key))
        payload = {**payload, "xml_id": key}
        external = None
        if operation and operation.status in {"sending", "unknown", "done"}:
            external = self.gateway.find_task_by_key(key)
            if not external:
                raise PublicationNotAllowedError(
                    f"Неизвестен результат запроса {key}. Проверьте Битрикс24; повторное создание заблокировано"
                )
        if operation is None:
            operation = IntegrationOperation(protocol_id=protocol.id, protocol_task_id=task_id,
                operation_key=key, status="pending", link_kind=kind, payload=payload)
            self.db.add(operation)
            self.db.commit()
        if external is None:
            operation.status = "sending"
            operation.payload = payload
            self.db.commit()  # Durable intent before the external side effect.
            try:
                external = self.gateway.create_task(payload)
            except Exception as exc:
                operation.status = "pending" if isinstance(exc, BitrixRejectedError) else "unknown"
                operation.error = "Битрикс24 отклонил запрос; исправьте настройки перед повтором" if isinstance(exc, BitrixRejectedError) else "Результат внешнего запроса неизвестен; требуется сверка"
                self.db.commit()
                raise
        link = self._add_link(task_id, external)
        link.publication_key = key
        link.link_kind = kind
        link.responsible_id = payload.get("responsible_id")
        operation.status = "done"
        operation.external_task_id = str(external["id"])
        operation.error = None
        self.db.commit()  # Each successful external write has a durable local link.
        return link, False

    def _description(self, protocol: Protocol, task: Any, planned: Any, settings: PublicationSettings) -> str:
        section = self.db.get(ProtocolSection, task.section_id) if task.section_id else None
        performers = ", ".join(a.assignee_name or "" for a in task.assignments if a.assignee_name) or "—"
        parts = [planned.title]
        if task.description:
            parts.append(task.description)
        parts += [
            f"Протокол: {protocol.number or '—'} — {protocol.title}",
            f"Раздел: {section.title if section else '—'}",
            f"Исполнители: {performers}",
            f"Срок: {planned.deadline or '—'}",
        ]
        if settings.add_protocol_link:
            parts.append(f"Карточка протокола: {self.protocol_base_url}/{protocol.id}")
        return "\n\n".join(parts)

    def _task_payload(self, protocol, task, planned, settings, responsible_id, parent_id):
        return {
            "title": planned.title,
            "description": self._description(protocol, task, planned, settings),
            "responsible_id": responsible_id,
            "created_by": settings.task_creator_id,
            "deadline": str(planned.deadline) if planned.deadline else None,
            "group_id": settings.bitrix_project_id,
            "accomplices": settings.accomplices or [],
            "auditors": settings.observers or [],
            "parent_id": parent_id,
            "custom_fields": settings.custom_fields or {},
            "assignee_raw": planned.assignee_raw,
            "original_assignee": planned.original_assignee,
            "assignee_match_result": planned.assignee_match_result,
            "missing_bitrix_id_reason": planned.missing_bitrix_id_reason,
        }

    def _root_payload(self, protocol, settings):
        return {
            "title": settings.root_task_title or f"Протокол {protocol.number or protocol.title}",
            "description": f"Корневая задача протокола {protocol.number or '—'} — {protocol.title}",
            "responsible_id": settings.default_responsible_id,
            "created_by": settings.task_creator_id,
            "group_id": settings.bitrix_project_id,
            "accomplices": settings.accomplices or [],
            "auditors": settings.observers or [],
            "custom_fields": settings.custom_fields or {},
        }

    def _add_link(self, task_id, external):
        link = ProtocolTaskLink(
            protocol_task_id=task_id,
            external_system=self.gateway.external_system,
            external_task_id=str(external["id"]),
            external_task_url=external.get("url"),
            external_status=external.get("status"),
            last_synced_at=datetime.now(UTC),
        )
        self.db.add(link)
        return link

    def _links(self, protocol: Protocol) -> list[ProtocolTaskLink]:
        ids = [task.id for task in protocol.tasks]
        if not ids:
            return []
        return list(self.db.scalars(select(ProtocolTaskLink).where(ProtocolTaskLink.protocol_task_id.in_(ids), ProtocolTaskLink.external_system == self.gateway.external_system).order_by(ProtocolTaskLink.id)).all())
