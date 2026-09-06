import re
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models.domain import Employee, EmployeeAlias, EmployeeSourceSettings
from app.services.employees.provider import EmployeeProvider


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower().replace("ё", "е")).strip()


def _derived_aliases(full_name: str) -> set[str]:
    """Build safe deterministic aliases for common Russian FIO notation."""
    parts = [part for part in re.split(r"\s+", full_name.strip()) if part]
    if len(parts) < 2:
        return set()
    surname, first = parts[0], parts[1]
    middle = parts[2] if len(parts) > 2 else ""
    initials = f"{first[0]}." + (f"{middle[0]}." if middle else "")
    spaced_initials = f"{first[0]}." + (f" {middle[0]}." if middle else "")
    return {f"{surname} {initials}", f"{surname} {spaced_initials}"}


class EmployeeDirectoryService:
    def __init__(self, db: Session):
        self.db = db

    def _sync_aliases(self, employee: Employee) -> None:
        existing = {
            _normalize_name(alias.alias)
            for alias in self.db.scalars(
                select(EmployeeAlias).where(EmployeeAlias.employee_id == employee.id)
            ).all()
        }
        for alias in _derived_aliases(employee.full_name):
            normalized = _normalize_name(alias)
            if normalized not in existing:
                self.db.add(
                    EmployeeAlias(
                        employee_id=employee.id,
                        alias=alias,
                        normalized_alias=normalized,
                        source="derived_fio",
                    )
                )
                existing.add(normalized)

    def create(self, **data) -> Employee:
        employee = Employee(**data)
        self.db.add(employee)
        self.db.flush()
        self._sync_aliases(employee)
        self.db.commit()
        self.db.refresh(employee)
        return employee

    def update(self, employee: Employee, **data) -> Employee:
        for field, value in data.items():
            setattr(employee, field, value)
        self.db.flush()
        self._sync_aliases(employee)
        self.db.commit()
        self.db.refresh(employee)
        return employee

    def delete(self, employee: Employee) -> None:
        self.db.delete(employee)
        self.db.commit()

    def search(self, query: str = "", source: str | None = None, department: str | None = None):
        statement = select(Employee)
        if query.strip():
            pattern = f"%{query.strip()}%"
            statement = statement.where(
                or_(
                    Employee.full_name.ilike(pattern),
                    Employee.email.ilike(pattern),
                    Employee.department.ilike(pattern),
                    Employee.position.ilike(pattern),
                )
            )
        if source:
            statement = statement.where(Employee.source_system == source)
        if department:
            statement = statement.where(Employee.department == department)
        return self.db.scalars(statement.order_by(Employee.full_name)).all()

    def sync(
        self, provider: EmployeeProvider, settings: EmployeeSourceSettings | None = None
    ) -> int:
        count = 0
        for record in provider.load():
            employee = self.db.scalar(
                select(Employee).where(
                    or_(
                        Employee.personnel_number == record.external_id,
                        Employee.email == record.email if record.email else False,
                    )
                )
            )
            values = {
                "full_name": record.full_name,
                "email": record.email,
                "position": record.position,
                "department": record.department,
                "bitrix_user_id": record.bitrix_user_id,
                "personnel_number": record.external_id,
                "source_system": provider.source_type,
            }
            if employee:
                for key, value in values.items():
                    setattr(employee, key, value)
            else:
                employee = Employee(**values)
                self.db.add(employee)
            self.db.flush()
            self._sync_aliases(employee)
            count += 1
        if settings:
            settings.last_sync_at = datetime.now(UTC)
            settings.last_sync_status = "success"
            settings.last_sync_message = f"Загружено записей: {count}"
        self.db.commit()
        return count
