"""Add protocol audit history and DOCX version registry."""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017_corporate_governance"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table("protocol_history", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("protocol_id", sa.Integer(), nullable=False), sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("user", sa.String(255), nullable=False), sa.Column("details", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["protocol_id"], ["protocols.id"], ondelete="CASCADE"))
    op.create_index("ix_protocol_history_protocol_id", "protocol_history", ["protocol_id"])
    op.create_index("ix_protocol_history_event_type", "protocol_history", ["event_type"])
    op.create_table("protocol_document_versions", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("protocol_id", sa.Integer(), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("user", sa.String(255), nullable=False), sa.Column("file_url", sa.String(1000), nullable=False),
        sa.Column("exported_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["protocol_id"], ["protocols.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("protocol_id", "version"))
    op.create_index("ix_protocol_document_versions_protocol_id", "protocol_document_versions", ["protocol_id"])


def downgrade() -> None:
    op.drop_table("protocol_document_versions")
    op.drop_table("protocol_history")
