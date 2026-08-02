"""Add provider-neutral protocol task links.

Revision ID: 0006_add_protocol_task_links
Revises: 0005_add_protocol_task_control
"""

import sqlalchemy as sa

from alembic import op

revision = "0006_add_protocol_task_links"
down_revision = "0005_add_protocol_task_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "protocol_task_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "protocol_task_id",
            sa.Integer(),
            sa.ForeignKey("protocol_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_system", sa.String(32), nullable=False),
        sa.Column("external_task_id", sa.String(255), nullable=False),
        sa.Column("external_task_url", sa.String(1000)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("external_system", "external_task_id"),
    )
    op.create_index(
        "ix_protocol_task_links_protocol_task_id", "protocol_task_links", ["protocol_task_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_protocol_task_links_protocol_task_id", table_name="protocol_task_links")
    op.drop_table("protocol_task_links")
