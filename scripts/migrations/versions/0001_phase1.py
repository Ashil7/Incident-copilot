"""Frozen Phase 1 schema; adopt only after verifying the existing table."""

import sqlalchemy as sa
from alembic import op

revision = "0001_phase1"
down_revision = None
branch_labels = None
depends_on = None


def baseline_metadata():
    metadata = sa.MetaData()
    sa.Table(
        "incidents",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("service_name", sa.String(200)),
        sa.Column(
            "environment",
            sa.Enum("DEV", "UAT", "PROD", name="incident_environment"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "CREATED",
                "UPLOADED",
                "PARSING",
                "CALCULATING",
                "GENERATING_ANALYSIS",
                "VALIDATING",
                "COMPLETED",
                "FAILED",
                name="incident_status",
            ),
            nullable=False,
        ),
        sa.Column("original_filename", sa.Text()),
        sa.Column("stored_file_path", sa.Text()),
        sa.Column("statistics", sa.JSON()),
        sa.Column("analysis", sa.JSON()),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    return metadata


def upgrade():
    baseline_metadata().tables["incidents"].create(op.get_bind())


def downgrade():
    baseline_metadata().tables["incidents"].drop(op.get_bind())
