"""Structured protocol document header and signature block.

Revision ID: 0020_protocol_document_fields
Revises: 0019_reporting
"""

import sqlalchemy as sa

from alembic import op

revision = "0020_protocol_document_fields"
down_revision = "0019_reporting"
branch_labels = None
depends_on = None

FIELDS = [
    sa.Column("document_type", sa.String(32), nullable=False, server_default="protocol"),
    sa.Column("meeting_time", sa.Time()),
    sa.Column("meeting_location", sa.String(500)),
    sa.Column("meeting_format", sa.String(32)),
    sa.Column("organization_name", sa.String(500)),
    sa.Column("event_type", sa.String(255)),
    sa.Column("event_title", sa.String(500)),
    sa.Column("meeting_topic", sa.String(500)),
    sa.Column("agenda_basis", sa.Text()),
    sa.Column(
        "chairperson_employee_id",
        sa.Integer(),
        sa.ForeignKey("employees.id", name="fk_protocols_chairperson_employee"),
    ),
    sa.Column("chairperson_snapshot", sa.String(255)),
    sa.Column(
        "secretary_employee_id",
        sa.Integer(),
        sa.ForeignKey("employees.id", name="fk_protocols_secretary_employee"),
    ),
    sa.Column("secretary_snapshot", sa.String(255)),
    sa.Column("responsible_department", sa.String(255)),
    sa.Column("project_label", sa.String(255)),
    sa.Column("footer_notes", sa.Text()),
    sa.Column("prepared_by", sa.String(255)),
    sa.Column("approved_by", sa.String(255)),
]


def upgrade():
    with op.batch_alter_table("protocols") as batch:
        for column in FIELDS:
            batch.add_column(column)
    op.create_table(
        "protocol_signatories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "protocol_id",
            sa.Integer(),
            sa.ForeignKey("protocols.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(255), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="SET NULL")),
        sa.Column("name_snapshot", sa.String(255), nullable=False),
        sa.Column("position_snapshot", sa.String(255)),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_protocol_signatories_protocol_id", "protocol_signatories", ["protocol_id"])


def downgrade():
    op.drop_table("protocol_signatories")
    with op.batch_alter_table("protocols") as batch:
        for column in reversed(FIELDS):
            batch.drop_column(column.name)
