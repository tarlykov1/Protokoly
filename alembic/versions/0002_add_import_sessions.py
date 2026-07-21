"""add import sessions

Revision ID: 0002_add_import_sessions
Revises: 0001_create_foundation_tables
Create Date: 2026-07-21
"""

import sqlalchemy as sa

from alembic import op

revision = "0002_add_import_sessions"
down_revision = "0001_create_foundation_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("stored_filename", sa.String(255), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("parser_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("parsed_payload", sa.JSON()),
        sa.Column("warnings_payload", sa.JSON()),
        sa.Column("errors_payload", sa.JSON()),
        sa.Column("parse_history", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("protocol_id", sa.Integer(), sa.ForeignKey("protocols.id")),
    )
    op.create_index("ix_import_sessions_checksum", "import_sessions", ["checksum"])


def downgrade() -> None:
    op.drop_table("import_sessions")
