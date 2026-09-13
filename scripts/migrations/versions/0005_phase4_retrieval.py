"""Runbooks, vector chunks, and incident embeddings."""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0005_phase4_retrieval"
down_revision = "0004_analysis_jobs"
branch_labels = None
depends_on = None
DIMENSIONS = 1536
EMBEDDING_TYPE = Vector(DIMENSIONS).with_variant(sa.JSON(), "sqlite")


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "runbooks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("is_global", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("storage_scope", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="PENDING"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_runbooks_owner_user_id", "runbooks", ["owner_user_id"])
    op.create_index("ix_runbooks_is_global", "runbooks", ["is_global"])
    op.create_index("ix_runbooks_status", "runbooks", ["status"])
    op.create_table(
        "runbook_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "runbook_id",
            sa.String(36),
            sa.ForeignKey("runbooks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section_name", sa.String(300), nullable=True),
        sa.Column("embedding", EMBEDDING_TYPE, nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.UniqueConstraint("runbook_id", "chunk_index", name="uq_runbook_chunk"),
    )
    op.create_index("ix_runbook_chunks_runbook_id", "runbook_chunks", ["runbook_id"])
    op.create_table(
        "incident_embeddings",
        sa.Column(
            "incident_id",
            sa.String(36),
            sa.ForeignKey("incidents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("searchable_summary", sa.Text(), nullable=False),
        sa.Column("embedding", EMBEDDING_TYPE, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def downgrade():
    op.drop_table("incident_embeddings")
    op.drop_index("ix_runbook_chunks_runbook_id", table_name="runbook_chunks")
    op.drop_table("runbook_chunks")
    for name in ("ix_runbooks_status", "ix_runbooks_is_global", "ix_runbooks_owner_user_id"):
        op.drop_index(name, table_name="runbooks")
    op.drop_table("runbooks")
