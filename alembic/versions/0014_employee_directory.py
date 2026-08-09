"""employee directory and source settings

Revision ID: 0014_employee_directory
Revises: 0013_add_protocol_task_parent
"""

import sqlalchemy as sa

from alembic import op

revision = "0014_employee_directory"
down_revision = "0013_add_protocol_task_parent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("employees") as batch_op:
        batch_op.add_column(sa.Column("position", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("department", sa.String(255), nullable=True))
    op.create_table(
        "employee_source_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_type", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True)),
        sa.Column("last_sync_status", sa.String(32)),
        sa.Column("last_sync_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("employee_source_settings")
    with op.batch_alter_table("employees") as batch_op:
        batch_op.drop_column("department")
        batch_op.drop_column("position")
