"""Store immutable DOCX exports; older registry entries remain without a snapshot."""
import sqlalchemy as sa

from alembic import op

revision = "0022_document_snapshots"
down_revision = "0021_employee_fio_aliases"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("protocol_document_versions", sa.Column("content", sa.LargeBinary(), nullable=True))


def downgrade():
    op.drop_column("protocol_document_versions", "content")
