"""Add one-to-one execution controls for protocol tasks.

Revision ID: 0008_add_protocol_task_controls
Revises: 0007_add_execution_control
"""

import sqlalchemy as sa

from alembic import op

revision = "0008_add_protocol_task_controls"
down_revision = "0007_add_execution_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "protocol_task_controls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("protocol_task_id", sa.Integer(), sa.ForeignKey("protocol_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("planned_date", sa.Date()),
        sa.Column("actual_date", sa.Date()),
        sa.Column("result_comment", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("protocol_task_id"),
    )
    op.create_index("ix_protocol_task_controls_protocol_task_id", "protocol_task_controls", ["protocol_task_id"])


def downgrade() -> None:
    op.drop_index("ix_protocol_task_controls_protocol_task_id", table_name="protocol_task_controls")
    op.drop_table("protocol_task_controls")
