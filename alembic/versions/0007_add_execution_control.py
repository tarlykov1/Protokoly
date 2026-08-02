"""Add task execution lifecycle and status history.

Revision ID: 0007_add_execution_control
Revises: 0006_add_protocol_task_links
"""

import sqlalchemy as sa

from alembic import op

revision = "0007_add_execution_control"
down_revision = "0006_add_protocol_task_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("protocol_tasks", "status", new_column_name="validation_status")
    op.add_column(
        "protocol_tasks",
        sa.Column("status", sa.String(32), nullable=False, server_default="new"),
    )
    op.create_table(
        "protocol_task_status_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("protocol_task_id", sa.Integer(), sa.ForeignKey("protocol_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("old_status", sa.String(32), nullable=False),
        sa.Column("new_status", sa.String(32), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("changed_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_protocol_task_status_history_protocol_task_id", "protocol_task_status_history", ["protocol_task_id"])
    op.add_column("protocol_task_links", sa.Column("external_status", sa.String(64)))
    op.add_column("protocol_task_links", sa.Column("last_synced_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("protocol_task_links", "last_synced_at")
    op.drop_column("protocol_task_links", "external_status")
    op.drop_index("ix_protocol_task_status_history_protocol_task_id", table_name="protocol_task_status_history")
    op.drop_table("protocol_task_status_history")
    op.drop_column("protocol_tasks", "status")
    op.alter_column("protocol_tasks", "validation_status", new_column_name="status")
