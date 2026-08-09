from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.domain import Employee, EmployeeSourceSettings
from app.services.employees import EmployeeDirectoryService, EmployeeProvider, EmployeeRecord


class MockEmployeeProvider(EmployeeProvider):
    source_type = "mock"

    def load(self):
        return [
            EmployeeRecord(
                external_id="EXT-7",
                full_name="Мария Орлова",
                email="orlova@example.test",
                position="Аналитик",
                department="Финансы",
            )
        ]


def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_create_update_and_delete_employee():
    db = session()
    service = EmployeeDirectoryService(db)

    employee = service.create(full_name="Иван Петров", source_system="manual")
    service.update(employee, position="Руководитель", department="ИТ")

    assert service.search("Петров")[0].position == "Руководитель"
    service.delete(employee)
    assert db.get(Employee, employee.id) is None


def test_load_employees_from_mock_provider():
    db = session()
    settings = EmployeeSourceSettings(provider_type="mock", parameters={})
    db.add(settings)
    db.commit()

    count = EmployeeDirectoryService(db).sync(MockEmployeeProvider(), settings)

    employee = db.scalar(select(Employee))
    assert count == 1
    assert employee.full_name == "Мария Орлова"
    assert employee.source_system == "mock"
    assert settings.last_sync_status == "success"


def test_employee_source_can_be_selected():
    db = session()
    settings = EmployeeSourceSettings(provider_type="manual", parameters={})
    db.add(settings)
    db.commit()

    settings.provider_type = "database"
    settings.parameters = {"table": "employees", "id_field": "id", "name_field": "name"}
    db.commit()

    saved = db.get(EmployeeSourceSettings, settings.id)
    assert saved.provider_type == "database"
