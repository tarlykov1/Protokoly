"""Add production Bitrix24 publication settings and sync metadata.

Revision ID: 0016
Revises: 0015
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015_task_participant_groups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "publication_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("protocol_id", sa.Integer(), nullable=False),
        sa.Column("bitrix_project_id", sa.Integer()),
        sa.Column("task_creator_id", sa.Integer()),
        sa.Column("default_responsible_id", sa.Integer()),
        sa.Column("parent_task_mode", sa.String(32), nullable=False, server_default="separate"),
        sa.Column("root_task_title", sa.String(500)),
        sa.Column("observers", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("accomplices", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("create_checklist", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("add_protocol_link", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sync_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("custom_fields", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["protocol_id"], ["protocols.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("protocol_id"),
    )
    op.create_index("ix_publication_settings_protocol_id", "publication_settings", ["protocol_id"])
    op.add_column(
        "protocol_task_controls", sa.Column("last_synced_at", sa.DateTime(timezone=True))
    )


def downgrade() -> None:
    op.drop_column("protocol_task_controls", "last_synced_at")
    op.drop_index("ix_publication_settings_protocol_id", table_name="publication_settings")
    op.drop_table("publication_settings")
