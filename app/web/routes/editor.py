"""Transactional protocol editing endpoint shared by full and inline editors."""

from datetime import date, time

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models.domain import Protocol, ProtocolSection, ProtocolSignatory
from app.db.session import get_db
from app.services.auth import CurrentUser, Permission, require
from app.services.protocols.editor import apply_task_data
from app.services.protocols.governance import record_event

router = APIRouter()


@router.post("/protocols/{protocol_id}/editor/save")
def save_protocol_editor(
    protocol_id: int,
    payload: dict = Body(...),
    actor: CurrentUser = Depends(require(Permission.EDIT)),
    db: Session = Depends(get_db),
):
    try:
        protocol = db.get(Protocol, protocol_id)
        if not protocol:
            raise HTTPException(status_code=404, detail="Протокол не найден")
        expected_version = payload.get("version", protocol.version)
        try:
            expected_version = int(expected_version)
            if not isinstance(payload.get("protocol", {}), dict):
                raise ValueError
            for name in ("tasks", "sections", "signatories", "signatory_updates"):
                if name in payload and (
                    not isinstance(payload[name], list)
                    or any(not isinstance(item, dict) for item in payload[name])
                ):
                    raise ValueError
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, "Некорректный формат данных редактора") from exc
        # Compare-and-swap is atomic; a Python-only check allows concurrent overwrites.
        result = db.execute(
            update(Protocol)
            .where(Protocol.id == protocol_id, Protocol.version == expected_version)
            .values(version=Protocol.version + 1)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(
                409,
                "Протокол был изменён другим пользователем. Обновите страницу перед сохранением.",
            )
        db.refresh(protocol)
        protocol_data = payload.get("protocol", {})
        tracked_before = {}
        text_fields = (
            "document_type",
            "title",
            "number",
            "meeting_location",
            "meeting_format",
            "organization_name",
            "event_type",
            "event_title",
            "meeting_topic",
            "agenda_basis",
            "chairperson_snapshot",
            "secretary_snapshot",
            "initiator",
            "responsible",
            "participants",
            "responsible_department",
            "project_label",
            "description",
            "footer_notes",
            "prepared_by",
            "approved_by",
        )
        for field in text_fields:
            if field in protocol_data:
                tracked_before[field] = getattr(protocol, field)
                cleaned = str(protocol_data[field] or "").strip()
                setattr(protocol, field, cleaned or ("" if field == "title" else None))
        if "meeting_date" in protocol_data:
            value = protocol_data["meeting_date"]
            tracked_before["meeting_date"] = protocol.meeting_date
            protocol.meeting_date = date.fromisoformat(value) if value else None
        if "meeting_time" in protocol_data:
            tracked_before["meeting_time"] = protocol.meeting_time
            value = protocol_data["meeting_time"]
            protocol.meeting_time = time.fromisoformat(value) if value else None
        for field in ("chairperson_employee_id", "secretary_employee_id"):
            if field in protocol_data:
                tracked_before[field] = getattr(protocol, field)
                value = protocol_data[field]
                setattr(protocol, field, int(value) if value else None)
        old_signatories = [
            (s.role, s.employee_id, s.name_snapshot, s.position_snapshot)
            for s in protocol.signatories
        ]
        signatories_by_id = {item.id: item for item in protocol.signatories}
        for item in payload.get("signatory_updates", []):
            signatory = signatories_by_id.get(int(item["id"]))
            if signatory is None:
                raise HTTPException(404, "Подписант не найден в протоколе")
            for field in ("role", "name_snapshot", "position_snapshot"):
                if field in item:
                    value = str(item[field] or "").strip()
                    if field != "position_snapshot" and not value:
                        raise HTTPException(422, "Укажите роль и ФИО подписанта")
                    setattr(signatory, field, value or None)
        if "signatories" in payload:
            protocol.signatories.clear()
            for order, item in enumerate(payload.get("signatories") or []):
                name = str(item.get("name_snapshot") or "").strip()
                role = str(item.get("role") or "").strip()
                if name and role:
                    previous = signatories_by_id.get(int(item["id"])) if item.get("id") else None
                    if item.get("id") and previous is None:
                        raise HTTPException(404, "Подписант не найден в протоколе")
                    if previous:
                        previous.role, previous.name_snapshot = role, name
                        previous.position_snapshot = (
                            str(item.get("position_snapshot") or "").strip() or None
                        )
                        previous.sort_order = order
                        protocol.signatories.append(previous)
                        continue
                    protocol.signatories.append(
                        ProtocolSignatory(
                            role=role,
                            employee_id=int(item["employee_id"])
                            if item.get("employee_id")
                            else None,
                            name_snapshot=name,
                            position_snapshot=str(item.get("position_snapshot") or "").strip()
                            or None,
                            sort_order=order,
                        )
                    )
        changed = [
            field for field, old in tracked_before.items() if getattr(protocol, field) != old
        ]
        if changed:
            record_event(db, protocol, "protocol_details_changed", actor.username, fields=changed)
        new_signatories = [
            (s.role, s.employee_id, s.name_snapshot, s.position_snapshot)
            for s in protocol.signatories
        ]
        if new_signatories != old_signatories:
            record_event(db, protocol, "protocol_signatories_changed", actor.username)
        tasks = {task.id: task for task in protocol.tasks}
        sections = {
            section.id: section
            for section in db.scalars(
                select(ProtocolSection).where(ProtocolSection.protocol_id == protocol_id)
            ).all()
        }
        for section_data in payload.get("sections", []):
            section = sections.get(int(section_data["id"]))
            if section is None:
                raise HTTPException(404, "Раздел не найден в протоколе")
            if section:
                section.title = section_data["title"].strip() or section.title
                if "sort_order" in section_data:
                    section.sort_order = int(section_data["sort_order"])
        for task_data in payload.get("tasks", []):
            task = tasks.get(int(task_data["id"]))
            if task is None:
                raise HTTPException(404, "Поручение не найдено в протоколе")
            if task:
                old_title, old_deadline = task.title, task.deadline
                old_assignees = sorted(a.employee_id for a in task.assignments if a.employee_id)
                try:
                    apply_task_data(db, task, task_data)
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
                if "position" in task_data:
                    task.position = int(task_data["position"])
                if task.title != old_title:
                    record_event(db, protocol, "task_text_changed", actor.username, task_id=task.id)
                if task.deadline != old_deadline:
                    record_event(
                        db, protocol, "task_deadline_changed", actor.username, task_id=task.id
                    )
                new_assignees = sorted(a.employee_id for a in task.assignments if a.employee_id)
                if new_assignees != old_assignees:
                    record_event(
                        db, protocol, "task_assignees_changed", actor.username, task_id=task.id
                    )
        for task_data in payload.get("tasks", []):
            task = tasks.get(int(task_data["id"]))
            if task:
                task.version += 1
        db.commit()
        return {
            "saved": True,
            "version": protocol.version,
            "signatories": [
                {"id": item.id, "sort_order": item.sort_order} for item in protocol.signatories
            ],
        }

    except HTTPException:
        db.rollback()
        raise
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        db.rollback()
        raise HTTPException(422, "Некорректные значения полей редактора") from exc
