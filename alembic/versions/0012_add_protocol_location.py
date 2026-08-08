"""add protocol meeting location

Revision ID: 0012_add_protocol_location
Revises: 0011_participant_groups
"""

import sqlalchemy as sa

from alembic import op

revision = "0012_add_protocol_location"
down_revision = "0011_participant_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("protocols", sa.Column("location", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("protocols", "location")
