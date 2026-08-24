"""Reporting, saved views and immutable report archive.

Revision ID: 0019_reporting
Revises: 0018
"""

import sqlalchemy as sa

from alembic import op

revision = "0019_reporting"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("protocol_tasks") as batch:
        batch.add_column(sa.Column("original_deadline", sa.Date()))
        batch.add_column(
            sa.Column("include_in_report", sa.Boolean(), nullable=False, server_default=sa.true())
        )
    op.create_table(
        "saved_report_views",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("owner", sa.String(255), nullable=False),
        sa.Column("filters_json", sa.JSON(), nullable=False),
        sa.Column("report_type", sa.String(64), nullable=False),
        sa.Column("shared", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_saved_report_views_owner", "saved_report_views", ["owner"])
    op.create_table(
        "report_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_type", sa.String(64), nullable=False),
        sa.Column("user", sa.String(255), nullable=False),
        sa.Column("filters_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("file_path", sa.String(1000)),
        sa.Column("file_url", sa.String(1000)),
        sa.Column("error_message", sa.Text()),
    )
    op.create_index("ix_report_runs_report_type", "report_runs", ["report_type"])
    op.create_index("ix_report_runs_user", "report_runs", ["user"])
    op.create_index("ix_report_runs_status", "report_runs", ["status"])


def downgrade():
    op.drop_table("report_runs")
    op.drop_table("saved_report_views")
    with op.batch_alter_table("protocol_tasks") as batch:
        batch.drop_column("include_in_report")
        batch.drop_column("original_deadline")
