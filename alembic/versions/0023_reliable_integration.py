"""Durable integration operations, jobs and explicit task ownership."""
import sqlalchemy as sa

from alembic import op

revision = "0023_reliable_integration"
down_revision = "0022_document_snapshots"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("integration_settings") as batch:
        batch.alter_column("webhook_url", existing_type=sa.String(1000), type_=sa.Text())
    with op.batch_alter_table("protocol_tasks") as batch:
        batch.add_column(sa.Column("primary_employee_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_task_primary_employee", "employees", ["primary_employee_id"], ["id"], ondelete="SET NULL")
    with op.batch_alter_table("protocol_task_links") as batch:
        batch.add_column(sa.Column("publication_key", sa.String(255), nullable=True))
        batch.add_column(sa.Column("link_kind", sa.String(32), server_default="legacy", nullable=False))
        batch.add_column(sa.Column("responsible_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("remote_snapshot", sa.JSON(), nullable=True))
        batch.create_unique_constraint("uq_link_publication_key", ["publication_key"])
    op.create_table("integration_operations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("protocol_id", sa.Integer(), sa.ForeignKey("protocols.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("protocol_task_id", sa.Integer(), sa.ForeignKey("protocol_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation_key", sa.String(255), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("link_kind", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("external_task_id", sa.String(255)),
        sa.Column("error", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("integration_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("protocol_id", sa.Integer(), sa.ForeignKey("protocols.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, index=True),
        sa.Column("requested_by", sa.String(255), nullable=False),
        sa.Column("bitrix_user_id", sa.Integer()),
        sa.Column("update_existing", sa.Boolean(), nullable=False),
        sa.Column("message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))


def downgrade():
    op.drop_table("integration_jobs")
    op.drop_table("integration_operations")
    with op.batch_alter_table("protocol_task_links") as batch:
        batch.drop_constraint("uq_link_publication_key", type_="unique")
        for name in ("remote_snapshot", "responsible_id", "link_kind", "publication_key"):
            batch.drop_column(name)
    with op.batch_alter_table("protocol_tasks") as batch:
        batch.drop_constraint("fk_task_primary_employee", type_="foreignkey")
        batch.drop_column("primary_employee_id")
