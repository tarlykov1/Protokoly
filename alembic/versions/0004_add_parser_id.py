"""persist the selected import parser

Revision ID: 0004_add_parser_id
Revises: 0003_add_publication_runs
Create Date: 2026-07-30
"""

import sqlalchemy as sa

from alembic import op

revision = "0004_add_parser_id"
down_revision = "0003_add_publication_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "import_sessions",
        sa.Column("parser_id", sa.String(64), nullable=True),
    )
    op.execute(
        "UPDATE import_sessions "
        "SET parser_id = replace(parser_type, '_', '-') "
        "WHERE parser_id IS NULL"
    )
    with op.batch_alter_table("import_sessions") as batch_op:
        batch_op.alter_column("parser_id", nullable=False)


def downgrade() -> None:
    op.drop_column("import_sessions", "parser_id")
