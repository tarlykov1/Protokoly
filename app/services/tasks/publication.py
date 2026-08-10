from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.domain import (
    Employee,
    Protocol,
    ProtocolSection,
    ProtocolTaskControl,
    ProtocolTaskLink,
    PublicationSettings,
)
from app.services.demo_publication import protocol_plan
from app.services.protocols.editor import editor_errors
from app.services.tasks.gateway import TaskGateway


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

    def settings_for(self, protocol: Protocol) -> PublicationSettings:
        if protocol.publication_settings is None:
            protocol.publication_settings = PublicationSettings(
                bitrix_project_id=protocol.project.bitrix_group_id
            )
            self.db.flush()
        return protocol.publication_settings

    def preview(self, protocol: Protocol) -> PublicationPreview:
        settings = self.settings_for(protocol)
        rows, plan_errors, _ = protocol_plan(self.db, protocol)
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
        existing = self._links(protocol)
        if existing and not update_existing:
            return PublicationResult(existing, reused=True)
        if protocol.status not in {"approved", "published"}:
            raise PublicationNotAllowedError("Можно публиковать только утверждённый протокол")
        unresolved = [task.number for task in protocol.tasks if "Пользователь не найден" in editor_errors(task)]
        if unresolved:
            raise PublicationNotAllowedError(
                "Пользователь не найден для поручений: " + ", ".join(unresolved)
            )
        settings = self.settings_for(protocol)
        rows, errors, _ = protocol_plan(self.db, protocol)
        # Keep compatibility for installations that used project defaults before settings existed.
        if errors:
            raise PublicationNotAllowedError("; ".join(errors))

        existing_by_task: dict[int, list[ProtocolTaskLink]] = {}
        for link in existing:
            existing_by_task.setdefault(link.protocol_task_id, []).append(link)
        links: list[ProtocolTaskLink] = []
        warnings: list[str] = []
        updated = 0
        parent_ids: dict[int, str] = {}
        root_id: str | None = None

        if settings.parent_task_mode != "separate" and rows:
            root_payload = self._root_payload(protocol, settings)
            root_link = existing[0] if existing and update_existing else None
            if root_link:
                self.gateway.update_task(root_link.external_task_id, root_payload)
                root_id = root_link.external_task_id
                updated += 1
            else:
                external = self.gateway.create_task(root_payload)
                root_id = str(external["id"])
                root_link = self._add_link(rows[0][0].id, external)
            links.append(root_link)

        for protocol_task, planned in rows:
            responsible_id = planned.responsible_id or settings.default_responsible_id
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
                    warnings.append(f"Исполнитель «{planned.original_assignee}» не найден в Bitrix24")
            parent_id = parent_ids.get(protocol_task.parent_task_id) or root_id
            payload = self._task_payload(protocol, protocol_task, planned, settings, responsible_id, parent_id)
            candidates = existing_by_task.get(protocol_task.id, []) if update_existing else []
            # The first link may represent the root, so do not reuse it as the instruction link.
            link = next((item for item in candidates if item not in links), None)
            if link:
                self.gateway.update_task(link.external_task_id, payload)
                link.last_synced_at = datetime.now(UTC)
                links.append(link)
                updated += 1
                external_id = link.external_task_id
            else:
                external = self.gateway.create_task(payload)
                link = self._add_link(protocol_task.id, external)
                links.append(link)
                external_id = str(external["id"])
            parent_ids.setdefault(protocol_task.id, external_id)
            if protocol_task.control is None:
                self.db.add(ProtocolTaskControl(protocol_task=protocol_task, status="pending", planned_date=protocol_task.deadline))
        protocol.status = "published"
        self.db.commit()
        return PublicationResult(links, warnings=tuple(dict.fromkeys(warnings)), updated_count=updated)

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
        return list(self.db.scalars(select(ProtocolTaskLink).where(ProtocolTaskLink.protocol_task_id.in_(ids)).order_by(ProtocolTaskLink.id)).all())
