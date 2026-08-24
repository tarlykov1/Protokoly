from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models.domain import Employee, EmployeeSourceSettings
from app.services.employees.provider import EmployeeProvider


class EmployeeDirectoryService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Employee:
        employee = Employee(**data)
        self.db.add(employee)
        self.db.commit()
        self.db.refresh(employee)
        return employee

    def update(self, employee: Employee, **data) -> Employee:
        for field, value in data.items():
            setattr(employee, field, value)
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
                self.db.add(Employee(**values))
            count += 1
        if settings:
            settings.last_sync_at = datetime.now(UTC)
            settings.last_sync_status = "success"
            settings.last_sync_message = f"Загружено записей: {count}"
        self.db.commit()
        return count
