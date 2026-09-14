"""Apply migrations and encrypt legacy credentials before serving requests."""
from alembic.config import Config
from sqlalchemy import text

from alembic import command
from app.core.secrets import encrypt
from app.db.session import engine


def main():
    command.upgrade(Config("alembic.ini"), "head")
    with engine.begin() as connection:
        for row in connection.execute(text("SELECT id, webhook_url, encrypted_token FROM integration_settings")).mappings().all():
            connection.execute(text("UPDATE integration_settings SET webhook_url=:url, encrypted_token=:token WHERE id=:id"),
                               {"id": row["id"], "url": encrypt(row["webhook_url"]), "token": encrypt(row["encrypted_token"])})
        import json
        for row in connection.execute(text("SELECT id, parameters FROM employee_source_settings")).mappings().all():
            parameters = row["parameters"] or {}
            if isinstance(parameters, str):
                parameters = json.loads(parameters)
            if parameters.get("password"):
                parameters["password"] = encrypt(parameters["password"])
                from app.db.models.domain import EmployeeSourceSettings
                connection.execute(EmployeeSourceSettings.__table__.update().where(EmployeeSourceSettings.id == row["id"]).values(parameters=parameters))


if __name__ == "__main__":
    main()
