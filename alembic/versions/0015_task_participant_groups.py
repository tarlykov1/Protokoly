"""support multiple participant groups per task

Revision ID: 0015_task_participant_groups
Revises: 0014_employee_directory
"""

import sqlalchemy as sa

from alembic import op

revision = "0015_task_participant_groups"
down_revision = "0014_employee_directory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "protocol_task_participant_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "protocol_task_id",
            sa.Integer(),
            sa.ForeignKey("protocol_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "participant_group_id",
            sa.Integer(),
            sa.ForeignKey("protocol_participant_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("protocol_task_id", "participant_group_id"),
    )
    op.create_index(
        "ix_task_participant_group_task", "protocol_task_participant_groups", ["protocol_task_id"]
    )
    op.create_index(
        "ix_task_participant_group_group",
        "protocol_task_participant_groups",
        ["participant_group_id"],
    )
    op.execute("""
        INSERT INTO protocol_task_participant_groups (protocol_task_id, participant_group_id, sort_order)
        SELECT protocol_task_id, source_participant_group_id, 0
        FROM protocol_task_assignments
        WHERE source_participant_group_id IS NOT NULL
        GROUP BY protocol_task_id, source_participant_group_id
    """)


def downgrade() -> None:
    op.drop_table("protocol_task_participant_groups")
