"""add protocol task parent

Revision ID: 0013_add_protocol_task_parent
Revises: 0012_add_protocol_location
"""

import sqlalchemy as sa

from alembic import op

revision = "0013_add_protocol_task_parent"
down_revision = "0012_add_protocol_location"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("protocol_tasks") as batch_op:
        batch_op.add_column(sa.Column("parent_task_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_protocol_tasks_parent_task_id",
            "protocol_tasks",
            ["parent_task_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("protocol_tasks") as batch_op:
        batch_op.drop_constraint("fk_protocol_tasks_parent_task_id", type_="foreignkey")
        batch_op.drop_column("parent_task_id")
