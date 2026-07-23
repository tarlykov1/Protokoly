from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.domain import (
    ImportSession,
    Protocol,
    ProtocolSection,
    ProtocolTask,
    ProtocolTaskAssignment,
)
from app.parsers.docx import parse_docx
from app.parsers.protocol import ParserRegistry

MAX_IMPORT_SIZE = 10 * 1024 * 1024
logger = logging.getLogger(__name__)

ALLOWED_MIME = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/zip",
}


def import_dir() -> Path:
    path = Path("var/imports").resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _validate_upload(file: UploadFile, data: bytes) -> None:
    if not (file.filename or "").lower().endswith(".docx"):
        raise HTTPException(400, "Only .docx files are allowed")
    mime = file.content_type or mimetypes.guess_type(file.filename or "")[0] or ""
    if mime not in ALLOWED_MIME:
        raise HTTPException(400, "Invalid DOCX MIME type")
    if len(data) > MAX_IMPORT_SIZE:
        raise HTTPException(413, "DOCX file is too large")
    if not data.startswith(b"PK"):
        raise HTTPException(400, "DOCX ZIP signature is invalid")
    try:
        with ZipFile(__import__("io").BytesIO(data)) as zf:
            if "word/document.xml" not in zf.namelist():
                raise HTTPException(400, "DOCX payload is invalid")
    except BadZipFile as exc:
        raise HTTPException(400, "DOCX archive is corrupted") from exc


def duplicate_warnings(
    db: Session, project_id: int, checksum: str, number: str | None
) -> list[dict]:
    stmt = (
        select(ImportSession)
        .where(ImportSession.project_id == project_id, ImportSession.checksum == checksum)
        .order_by(ImportSession.created_at.desc())
    )
    result = []
    for s in db.scalars(stmt).all():
        protocol_number = (s.parsed_payload or {}).get("document_number")
        if not number or not protocol_number or protocol_number == number:
            result.append(
                {
                    "session_id": s.id,
                    "created_at": str(s.created_at),
                    "status": s.status,
                    "protocol_id": s.protocol_id,
                }
            )
    return result


def resolve_payload(db: Session, payload: dict) -> dict:
    from app.db.models.domain import Block, Direction, Employee, EmployeeAlias, EmployeeList

    def norm(v: str) -> str:
        return re.sub(r"\s+", " ", v.lower().replace("ё", "е")).strip()

    employees = db.scalars(select(Employee)).all()
    aliases = db.scalars(select(EmployeeAlias)).all()
    lists = {norm(x.name): x for x in db.scalars(select(EmployeeList)).all()}
    alias_map = {norm(a.alias): a.employee_id for a in aliases}
    dirs = db.scalars(
        select(Direction).where(Direction.project_id == payload.get("project_id", -1))
    ).all()
    blocks = db.scalars(
        select(Block).where(Block.project_id == payload.get("project_id", -1))
    ).all()
    for task in payload.get("tasks", []):
        raw = task.get("assignee_raw") or ""
        parts = [p.strip() for p in re.split(r",|/| совместно с ", raw) if p.strip()]
        task["assignee_resolution"] = []
        for part in parts:
            n = norm(part.replace("Ответственный:", ""))
            matches = [e for e in employees if norm(e.full_name) == n or alias_map.get(n) == e.id]
            if n in lists:
                task["assignee_resolution"].append(
                    {"raw": part, "status": "found", "employee_list_id": lists[n].id}
                )
            elif len(matches) == 1:
                task["assignee_resolution"].append(
                    {
                        "raw": part,
                        "status": "found" if matches[0].is_available_in_bitrix else "not_in_bitrix",
                        "employee_id": matches[0].id,
                        "name": matches[0].full_name,
                    }
                )
            elif len(matches) > 1:
                task["assignee_resolution"].append(
                    {
                        "raw": part,
                        "status": "multiple_matches",
                        "candidate_ids": [e.id for e in matches],
                    }
                )
            else:
                task["assignee_resolution"].append({"raw": part, "status": "not_found"})
        if not parts:
            task["assignee_resolution"] = [{"raw": raw, "status": "not_found"}]
        d_raw = norm(task.get("direction_raw") or "")
        b_raw = norm(task.get("block_raw") or "")
        if d_raw:
            d = next((x for x in dirs if norm(x.name) == d_raw or norm(x.code) == d_raw), None)
            task["direction_id"] = d.id if d else None
        if b_raw and task.get("direction_id"):
            b = next(
                (
                    x
                    for x in blocks
                    if x.direction_id == task["direction_id"]
                    and (norm(x.name) == b_raw or norm(x.code) == b_raw)
                ),
                None,
            )
            task["block_id"] = b.id if b else None
    return payload


def _safe_headings(doc) -> list[str]:
    headings: list[str] = []
    for element in doc.elements:
        text = re.sub(r"\s+", " ", element.text).strip()
        if text and (element.style and "Heading" in element.style or text.upper() == text):
            headings.append(text[:80])
        if len(headings) == 5:
            break
    return headings


def parse_file(db: Session, session: ImportSession, parser_type: str | None = None) -> None:
    doc = parse_docx(session.file_path)
    paragraph_count = sum(1 for e in doc.elements if e.kind == "paragraph")
    logger.info(
        "DOCX import parse start filename=%s paragraphs=%s elements=%s headings=%s",
        session.original_filename,
        paragraph_count,
        len(doc.elements),
        _safe_headings(doc),
    )
    parser, choice = ParserRegistry().choose(doc, parser_type)
    logger.info(
        "DOCX import parser selected filename=%s parser=%s confidence=%.2f",
        session.original_filename,
        parser.parser_type,
        choice.confidence,
    )
    try:
        result = parser.parse(doc).to_dict()
    except Exception:
        logger.exception(
            "DOCX import parser failed filename=%s parser=%s; falling back to universal",
            session.original_filename,
            parser.parser_type,
        )
        fallback = ParserRegistry().get("universal")
        result = fallback.parse(doc).to_dict()
        result.setdefault("warnings", []).append(
            "Специализированный парсер МЕМО не применён. Документ обработан универсальным парсером."
        )
        parser = fallback
        choice = fallback.confidence(doc)
    result["parser_choice"] = {
        "parser_type": choice.parser_type,
        "confidence": choice.confidence,
        "reasons": choice.reasons,
        "warnings": choice.warnings,
    }
    result["project_id"] = session.project_id
    result = resolve_payload(db, result)
    result["duplicates"] = duplicate_warnings(
        db, session.project_id, session.checksum, result.get("document_number")
    )
    session.parser_type = parser.parser_type
    session.parsed_payload = result
    if parser.parser_type == "universal" and "мемо" in session.original_filename.lower():
        result.setdefault("warnings", []).append(
            "Специализированный парсер МЕМО не применён. Документ обработан универсальным парсером."
        )
        logger.warning(
            "DOCX import memo fallback to universal filename=%s", session.original_filename
        )
    session.warnings_payload = result.get("warnings", []) + choice.warnings
    session.errors_payload = result.get("errors", [])
    session.status = (
        "needs_review" if session.errors_payload or session.warnings_payload else "parsed"
    )


def create_preview_session(
    db: Session, project_id: int, file: UploadFile, parser_type: str | None = None
) -> ImportSession:
    data = file.file.read()
    _validate_upload(file, data)
    checksum = hashlib.sha256(data).hexdigest()
    stored = f"{uuid.uuid4().hex}.docx"
    path = import_dir() / stored
    path.write_bytes(data)
    session = ImportSession(
        project_id=project_id,
        original_filename=Path(file.filename or "upload.docx").name,
        stored_filename=stored,
        file_path=str(path),
        file_size=len(data),
        checksum=checksum,
        parser_type="universal",
        status="uploaded",
        expires_at=datetime.now(UTC) + timedelta(hours=get_settings().import_session_ttl_hours),
        parsed_payload={},
        warnings_payload=[],
        errors_payload=[],
        parse_history=[],
    )
    db.add(session)
    db.flush()
    auto_parser_type = None if parser_type in (None, "", "universal") else parser_type
    parse_file(db, session, auto_parser_type)
    db.commit()
    db.refresh(session)
    return session


def update_session_payload(db: Session, session: ImportSession, payload: str) -> None:
    session.parsed_payload = json.loads(payload)
    session.status = "needs_review"
    db.commit()


def reparse_session(db: Session, session: ImportSession, parser_type: str, confirmed: bool) -> None:
    if not confirmed:
        raise HTTPException(400, "Reparse requires confirmation")
    history = list(session.parse_history or [])
    history.append(
        {
            "at": datetime.now(UTC).isoformat(),
            "parser_type": session.parser_type,
            "payload": session.parsed_payload,
        }
    )
    session.parse_history = history
    parse_file(db, session, parser_type)
    db.commit()


def _as_date(value: str | None):
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def confirm_session(db: Session, session: ImportSession) -> Protocol:
    payload = session.parsed_payload or {}
    protocol = Protocol(
        project_id=session.project_id,
        protocol_type=payload.get("protocol_type") or "protocol",
        title=payload.get("document_title") or session.original_filename,
        number=payload.get("document_number"),
        meeting_date=_as_date(payload.get("meeting_date") or payload.get("document_date")),
        status="draft",
        source_type="docx_import",
        source_filename=session.original_filename,
        source_file_path=session.file_path,
    )
    db.add(protocol)
    db.flush()
    section_by_title = {}
    for i, s in enumerate(payload.get("sections", []), 1):
        sec = ProtocolSection(
            protocol_id=protocol.id,
            title=s.get("title") or "Без раздела",
            sort_order=i,
            original_text=s.get("original_text"),
            direction_id=s.get("direction_id"),
            block_id=s.get("block_id"),
        )
        db.add(sec)
        db.flush()
        section_by_title[sec.title] = sec
    if "Без раздела" not in section_by_title:
        sec = ProtocolSection(protocol_id=protocol.id, title="Без раздела", sort_order=0)
        db.add(sec)
        db.flush()
        section_by_title[sec.title] = sec
    for i, t in enumerate(payload.get("tasks", []), 1):
        loc = t.get("source_location") or {}
        task = ProtocolTask(
            protocol_id=protocol.id,
            section_id=section_by_title.get(t.get("section_title") or "Без раздела").id,
            number=t.get("task_number") or str(i),
            title=(t.get("title") or "Поручение")[:500],
            description=t.get("description"),
            acceptance_criteria=t.get("acceptance_criteria"),
            deadline=_as_date(t.get("deadline")),
            priority=t.get("priority"),
            create_as_subtasks=False,
            status="draft",
            original_text=t.get("source_text"),
            source_paragraph=loc.get("paragraph_index"),
            source_table=loc.get("table_index"),
        )
        db.add(task)
        db.flush()
        for order, r in enumerate(t.get("assignee_resolution") or [], 1):
            if r.get("employee_id") or r.get("employee_list_id"):
                db.add(
                    ProtocolTaskAssignment(
                        protocol_task_id=task.id,
                        employee_id=r.get("employee_id"),
                        source_employee_list_id=r.get("employee_list_id"),
                        sort_order=order,
                    )
                )
    session.status = "confirmed"
    session.confirmed_at = datetime.now(UTC)
    session.protocol_id = protocol.id
    db.commit()
    db.refresh(protocol)
    return protocol


def cleanup_expired_import_sessions(db: Session) -> int:
    now = datetime.now(UTC)
    count = 0
    for s in db.scalars(
        select(ImportSession).where(
            ImportSession.expires_at < now, ImportSession.status.notin_(["confirmed", "expired"])
        )
    ).all():
        p = Path(s.file_path)
        if p.exists():
            p.unlink()
        s.status = "expired"
        count += 1
    db.commit()
    return count
