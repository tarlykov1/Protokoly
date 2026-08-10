"""Operational resilience, correlation and concurrency metadata.

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa

from alembic import op

revision = "0018"
down_revision = "0017_corporate_governance"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("integration_logs") as batch:
        batch.add_column(sa.Column("request_id", sa.String(128)))
        batch.add_column(sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("resolved_at", sa.DateTime(timezone=True)))
        batch.create_index("ix_integration_logs_request_id", ["request_id"])
    with op.batch_alter_table("protocols") as batch:
        batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    with op.batch_alter_table("protocol_tasks") as batch:
        batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("idempotency_key", sa.String(128)))
        batch.create_unique_constraint("uq_protocol_tasks_idempotency_key", ["idempotency_key"])
    with op.batch_alter_table("publication_runs") as batch:
        batch.add_column(sa.Column("operation_id", sa.String(64)))
        batch.add_column(sa.Column("request_id", sa.String(128)))
        batch.create_unique_constraint("uq_publication_runs_operation_id", ["operation_id"])
        batch.create_index("ix_publication_runs_request_id", ["request_id"])
    op.create_table(
        "edit_presence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("protocol_id", sa.Integer(), sa.ForeignKey("protocols.id", ondelete="CASCADE"), nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("request_id", sa.String(128)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("protocol_id", "username"),
    )
    op.create_index("ix_edit_presence_protocol_id", "edit_presence", ["protocol_id"])
    op.create_index("ix_edit_presence_last_seen_at", "edit_presence", ["last_seen_at"])


def downgrade():
    op.drop_table("edit_presence")
    with op.batch_alter_table("publication_runs") as batch:
        batch.drop_index("ix_publication_runs_request_id")
        batch.drop_constraint("uq_publication_runs_operation_id", type_="unique")
        batch.drop_column("request_id")
        batch.drop_column("operation_id")
    with op.batch_alter_table("protocol_tasks") as batch:
        batch.drop_constraint("uq_protocol_tasks_idempotency_key", type_="unique")
        batch.drop_column("idempotency_key")
        batch.drop_column("version")
    with op.batch_alter_table("protocols") as batch:
        batch.drop_column("version")
    with op.batch_alter_table("integration_logs") as batch:
        batch.drop_index("ix_integration_logs_request_id")
        batch.drop_column("resolved_at")
        batch.drop_column("attempts")
        batch.drop_column("request_id")
