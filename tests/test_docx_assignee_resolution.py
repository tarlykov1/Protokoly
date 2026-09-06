from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.domain import Employee, EmployeeAlias
from app.services.employees.service import EmployeeDirectoryService
from app.services.imports.service import resolve_payload


def directory_session(*names: str) -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add_all(Employee(full_name=name, is_active=True) for name in names)
    db.commit()
    return db


def payload(name: str) -> dict:
    return {"project_id": -1, "tasks": [{"task_number": "1", "assignee_raw": name}]}


def test_missing_docx_assignee_is_not_autoselected():
    db = directory_session("Иванов Иван Иванович")
    resolved = resolve_payload(db, payload("Иванов Иван Иванов"))
    match = resolved["tasks"][0]["assignee_resolution"][0]
    assert match == {"raw": "Иванов Иван Иванов", "status": "not_found"}
    assert "Пользователь не найден" in resolved["errors"][0]


def test_duplicate_exact_full_name_requires_manual_choice():
    db = directory_session("Иванов Иван Иванович", "Иванов Иван Иванович")
    resolved = resolve_payload(db, payload("Иванов Иван Иванович"))
    match = resolved["tasks"][0]["assignee_resolution"][0]
    assert match["status"] == "multiple_matches"
    assert len(match["candidate_ids"]) == 2
    assert "несколько сотрудников" in resolved["errors"][0]


def test_unique_exact_full_name_is_matched_successfully():
    db = directory_session("Иванов Иван Иванович", "Петров Петр Петрович")
    resolved = resolve_payload(db, payload("  ИВАНОВ   Иван Иванович "))
    match = resolved["tasks"][0]["assignee_resolution"][0]
    assert match["status"] == "not_in_bitrix"
    assert match["name"] == "Иванов Иван Иванович"
    assert match["employee_id"] is not None
    assert resolved["errors"] == []


def test_manual_employee_is_resolved_by_compact_initials():
    db = directory_session()
    employee = EmployeeDirectoryService(db).create(full_name="Прокофьев Дмитрий Юрьевич")
    resolved = resolve_payload(db, payload("Прокофьев Д.Ю."))
    match = resolved["tasks"][0]["assignee_resolution"][0]
    assert match["employee_id"] == employee.id
    assert match["name"] == "Прокофьев Дмитрий Юрьевич"
    assert match["status"] == "not_in_bitrix"
    assert resolved["errors"] == []


def test_manual_employee_aliases_cover_compact_and_spaced_initials():
    db = directory_session()
    employee = EmployeeDirectoryService(db).create(full_name="Прокофьев Дмитрий Юрьевич")
    aliases = db.scalars(select(EmployeeAlias).where(EmployeeAlias.employee_id == employee.id)).all()
    normalized = {alias.normalized_alias for alias in aliases}
    assert "прокофьев д.ю." in normalized
    assert "прокофьев д. ю." in normalized
