"""Add protocol participant groups and reusable templates.

Revision ID: 0011_participant_groups
Revises: 0010_add_integration_settings
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_participant_groups"
down_revision = "0010_add_integration_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("participant_group_templates", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(255), nullable=False, unique=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_table("protocol_participant_groups", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("protocol_id", sa.Integer(), sa.ForeignKey("protocols.id", ondelete="CASCADE"), nullable=False), sa.Column("name", sa.String(255), nullable=False), sa.Column("type", sa.String(32), nullable=False, server_default="custom"), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.UniqueConstraint("protocol_id", "name"))
    op.create_table("participant_group_template_members", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("template_id", sa.Integer(), sa.ForeignKey("participant_group_templates.id", ondelete="CASCADE"), nullable=False), sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False), sa.Column("name_snapshot", sa.String(255), nullable=False), sa.UniqueConstraint("template_id", "employee_id"))
    op.create_table("protocol_participant_group_members", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("group_id", sa.Integer(), sa.ForeignKey("protocol_participant_groups.id", ondelete="CASCADE"), nullable=False), sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False), sa.Column("name_snapshot", sa.String(255), nullable=False), sa.Column("source", sa.String(32), nullable=False, server_default="manual"), sa.UniqueConstraint("group_id", "employee_id"))
    op.add_column("protocol_task_assignments", sa.Column("source_participant_group_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_assignment_participant_group", "protocol_task_assignments", "protocol_participant_groups", ["source_participant_group_id"], ["id"], ondelete="SET NULL")
    op.execute("INSERT INTO protocol_participant_groups (protocol_id, name, type) SELECT id, 'Присутствовали', 'attendees' FROM protocols")


def downgrade() -> None:
    op.drop_constraint("fk_assignment_participant_group", "protocol_task_assignments", type_="foreignkey")
    op.drop_column("protocol_task_assignments", "source_participant_group_id")
    op.drop_table("protocol_participant_group_members")
    op.drop_table("participant_group_template_members")
    op.drop_table("protocol_participant_groups")
    op.drop_table("participant_group_templates")
