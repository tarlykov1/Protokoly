"""add publication runs

Revision ID: 0003_add_publication_runs
Revises: 0002_add_import_sessions
Create Date: 2026-07-21
"""

import sqlalchemy as sa

from alembic import op

revision = "0003_add_publication_runs"
down_revision = "0002_add_import_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "publication_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "protocol_id",
            sa.Integer(),
            sa.ForeignKey("protocols.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("gateway_type", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("successful_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(255)),
        sa.Column("error_summary", sa.Text()),
    )
    op.create_table(
        "publication_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "publication_run_id",
            sa.Integer(),
            sa.ForeignKey("publication_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "protocol_task_id",
            sa.Integer(),
            sa.ForeignKey("protocol_tasks.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "assignment_id",
            sa.Integer(),
            sa.ForeignKey("protocol_task_assignments.id", ondelete="SET NULL"),
        ),
        sa.Column("external_key", sa.String(255), nullable=False),
        sa.Column("parent_external_key", sa.String(255)),
        sa.Column("simulated_external_id", sa.String(255)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("request_payload", sa.JSON()),
        sa.Column("response_payload", sa.JSON()),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_publication_items_external_key", "publication_items", ["external_key"])


def downgrade() -> None:
    op.drop_table("publication_items")
    op.drop_table("publication_runs")
