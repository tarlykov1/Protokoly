"""Add the protocol task control flag.

Revision ID: 0005_add_protocol_task_control
Revises: 0004_add_parser_id
"""

import sqlalchemy as sa

from alembic import op

revision = "0005_add_protocol_task_control"
down_revision = "0004_add_parser_id"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "protocol_tasks",
        sa.Column("is_controlled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("protocol_tasks", "is_controlled")
