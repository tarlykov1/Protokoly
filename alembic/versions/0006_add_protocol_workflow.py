"""Add protocol workflow history and comments.

Revision ID: 0006_add_protocol_workflow
Revises: 0005_add_protocol_task_control
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_add_protocol_workflow"
down_revision = "0005_add_protocol_task_control"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "protocol_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("protocol_id", sa.Integer(), sa.ForeignKey("protocols.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_status", sa.String(32), nullable=False),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("user", sa.String(255), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "protocol_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("protocol_id", sa.Integer(), sa.ForeignKey("protocols.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user", sa.String(255), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("protocol_comments")
    op.drop_table("protocol_history")
