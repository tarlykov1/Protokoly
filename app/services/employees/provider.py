from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import MetaData, Table, create_engine, select


@dataclass(frozen=True, slots=True)
class EmployeeRecord:
    external_id: str
    full_name: str
    email: str | None = None
    position: str | None = None
    department: str | None = None
    bitrix_user_id: int | None = None


class EmployeeProvider(ABC):
    """Stable interface for employee sources."""

    source_type: str

    @abstractmethod
    def load(self) -> Iterable[EmployeeRecord]: ...

    def test_connection(self) -> tuple[bool, str]:
        try:
            next(iter(self.load()), None)
        except Exception as exc:
            return False, str(exc)
        return True, "Соединение установлено"


class ManualEmployeeProvider(EmployeeProvider):
    source_type = "manual"

    def load(self) -> Iterable[EmployeeRecord]:
        return ()


class DatabaseEmployeeProvider(EmployeeProvider):
    source_type = "database"

    def __init__(self, connection_url: str, parameters: dict[str, Any]):
        self.connection_url = connection_url
        self.parameters = parameters

    def load(self) -> Iterable[EmployeeRecord]:
        engine = create_engine(self.connection_url)
        table = Table(
            self.parameters["table"],
            MetaData(),
            schema=self.parameters.get("schema") or None,
            autoload_with=engine,
        )
        fields = {key: self.parameters.get(key) for key in ("id_field", "name_field", "email_field")}
        required = (fields["id_field"], fields["name_field"])
        if not all(required) or any(value not in table.c for value in required):
            raise ValueError("Не найдены настроенные поля ID или ФИО")
        columns = [table.c[value] for value in fields.values() if value and value in table.c]
        with engine.connect() as connection:
            rows = connection.execute(select(*columns)).mappings().all()
        return [
            EmployeeRecord(
                external_id=str(row[fields["id_field"]]),
                full_name=str(row[fields["name_field"]]),
                email=str(row[fields["email_field"]]) if fields["email_field"] and row[fields["email_field"]] else None,
            )
            for row in rows
        ]


class BitrixEmployeeProvider(EmployeeProvider):
    source_type = "bitrix"

    def __init__(self, fetch_users: Callable[[], Iterable[dict[str, Any]]]):
        self.fetch_users = fetch_users

    def load(self) -> Iterable[EmployeeRecord]:
        return [
            EmployeeRecord(
                external_id=str(user.get("ID") or user.get("id")),
                full_name=" ".join(filter(None, (user.get("LAST_NAME"), user.get("NAME"), user.get("SECOND_NAME")))).strip(),
                email=user.get("EMAIL"),
                position=user.get("WORK_POSITION"),
                department=str(user.get("UF_DEPARTMENT", "")) or None,
                bitrix_user_id=int(user.get("ID") or user.get("id")),
            )
            for user in self.fetch_users()
        ]
