"""Persistent job scheduling and one active job per incident."""

import sqlalchemy as sa
from alembic import op

revision = "0004_analysis_jobs"
down_revision = "0003_storage_cleanup"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    duplicate = connection.execute(
        sa.text(
            "SELECT incident_id FROM analysis_jobs WHERE status IN ('PENDING', 'RUNNING', 'RETRY') "
            "GROUP BY incident_id HAVING COUNT(*) > 1"
        )
    ).first()
    if duplicate:
        raise RuntimeError("Multiple active jobs exist; resolve them before migration.")
    with op.batch_alter_table(
        "analysis_jobs", recreate="always" if connection.dialect.name == "sqlite" else "auto"
    ) as batch:
        batch.add_column(
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        batch.add_column(sa.Column("request_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("retry_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column("analyze", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
        batch.add_column(
            sa.Column("cleanup", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    op.create_index(
        "uq_analysis_jobs_active",
        "analysis_jobs",
        ["incident_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING', 'RUNNING', 'RETRY')"),
        sqlite_where=sa.text("status IN ('PENDING', 'RUNNING', 'RETRY')"),
    )


def downgrade():
    op.drop_index("uq_analysis_jobs_active", table_name="analysis_jobs")
    with op.batch_alter_table("analysis_jobs") as batch:
        for name in ("cleanup", "analyze", "retry_at", "request_id", "created_at"):
            batch.drop_column(name)
