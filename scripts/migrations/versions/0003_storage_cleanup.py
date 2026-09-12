"""Durable pending storage deletions; no existing data is changed."""

import sqlalchemy as sa
from alembic import op

revision = "0003_storage_cleanup"
down_revision = "0002_normalized"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("log_files", sa.Column("storage_scope", sa.String(64), nullable=True))
    op.create_table(
        "storage_deletions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("storage_key", sa.Text(), nullable=False, unique=True),
        sa.Column("storage_scope", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("storage_deletions")
    with op.batch_alter_table("log_files") as batch_op:
        batch_op.drop_column("storage_scope")
