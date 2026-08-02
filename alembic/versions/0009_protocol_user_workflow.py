"""Add protocol metadata and task ordering.

Revision ID: 0009_protocol_user_workflow
Revises: 0008_add_protocol_task_controls
"""

import sqlalchemy as sa

from alembic import op

revision = "0009_protocol_user_workflow"
down_revision = "0008_add_protocol_task_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("protocols", sa.Column("initiator", sa.String(255)))
    op.add_column("protocols", sa.Column("responsible", sa.String(255)))
    op.add_column("protocols", sa.Column("participants", sa.Text()))
    op.add_column("protocols", sa.Column("description", sa.Text()))
    op.add_column(
        "protocol_tasks", sa.Column("position", sa.Integer(), server_default="0", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("protocol_tasks", "position")
    for column in ("description", "participants", "responsible", "initiator"):
        op.drop_column("protocols", column)
