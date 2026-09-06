"""Backfill safe employee aliases used by DOCX assignee resolution.

Revision ID: 0021_employee_fio_aliases
Revises: 0020_protocol_document_fields
"""

import re

import sqlalchemy as sa

from alembic import op

revision = "0021_employee_fio_aliases"
down_revision = "0020_protocol_document_fields"
branch_labels = None
depends_on = None


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower().replace("ё", "е")).strip()


def _aliases(full_name: str) -> set[str]:
    parts = [part for part in re.split(r"\s+", (full_name or "").strip()) if part]
    if len(parts) < 2:
        return set()
    surname, first = parts[0], parts[1]
    middle = parts[2] if len(parts) > 2 else ""
    compact = f"{surname} {first[0]}." + (f"{middle[0]}." if middle else "")
    spaced = f"{surname} {first[0]}." + (f" {middle[0]}." if middle else "")
    return {compact, spaced}


def upgrade():
    connection = op.get_bind()
    employees = sa.table(
        "employees", sa.column("id", sa.Integer()), sa.column("full_name", sa.String())
    )
    aliases = sa.table(
        "employee_aliases",
        sa.column("employee_id", sa.Integer()),
        sa.column("alias", sa.String()),
        sa.column("normalized_alias", sa.String()),
        sa.column("source", sa.String()),
    )
    existing = {
        (row.employee_id, row.normalized_alias)
        for row in connection.execute(sa.select(aliases.c.employee_id, aliases.c.normalized_alias))
    }
    for employee in connection.execute(sa.select(employees.c.id, employees.c.full_name)):
        for alias in _aliases(employee.full_name):
            normalized = _normalize(alias)
            key = (employee.id, normalized)
            if key in existing:
                continue
            connection.execute(
                aliases.insert().values(
                    employee_id=employee.id,
                    alias=alias,
                    normalized_alias=normalized,
                    source="derived_fio",
                )
            )
            existing.add(key)


def downgrade():
    connection = op.get_bind()
    connection.execute(
        sa.text("DELETE FROM employee_aliases WHERE source = :source"),
        {"source": "derived_fio"},
    )
