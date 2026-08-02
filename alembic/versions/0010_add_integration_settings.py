"""Add configurable integrations and their request log.

Revision ID: 0010_add_integration_settings
Revises: 0009_protocol_user_workflow
"""

import sqlalchemy as sa

from alembic import op

revision = "0010_add_integration_settings"
down_revision = "0009_protocol_user_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("type", sa.String(64), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("mode", sa.String(16), nullable=False, server_default="fake"),
        sa.Column("portal_url", sa.String(1000)),
        sa.Column("webhook_url", sa.String(1000)),
        sa.Column("user_id", sa.String(64)),
        sa.Column("encrypted_token", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "integration_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("operation", sa.String(128), nullable=False),
        sa.Column("request", sa.JSON()),
        sa.Column("response", sa.JSON()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_integration_logs_operation", "integration_logs", ["operation"])


def downgrade() -> None:
    op.drop_table("integration_logs")
    op.drop_table("integration_settings")
