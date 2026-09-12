"""Add normalized backend tables; retain all Phase 1 incident data."""

import sqlalchemy as sa
from alembic import op

revision = "0002_normalized"
down_revision = "0001_phase1"
branch_labels = None
depends_on = None


def upgrade():
    # Frozen operations reviewed for the Phase 1 transition.
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "ADMIN", "ANALYST", name="user_role", native_enum=False, create_constraint=True
            ),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "email = lower(trim(email)) AND length(email) > 0", name="ck_users_email_normalized"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "audit_events",
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column("resource_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("safe_metadata", sa.JSON(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("audit_events", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_audit_events_resource_id"), ["resource_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_audit_events_user_id"), ["user_id"], unique=False)

    op.create_table(
        "refresh_tokens",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    with op.batch_alter_table("refresh_tokens", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_refresh_tokens_user_id"), ["user_id"], unique=False)

    op.create_table(
        "analysis_jobs",
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("current_stage", sa.String(length=40), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.CheckConstraint("attempt_count >= 0", name="ck_analysis_jobs_attempts"),
        sa.CheckConstraint("progress >= 0 AND progress <= 100", name="ck_analysis_jobs_progress"),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("celery_task_id"),
    )
    with op.batch_alter_table("analysis_jobs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_analysis_jobs_incident_id"), ["incident_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_analysis_jobs_status"), ["status"], unique=False)

    op.create_table(
        "feedback",
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("helpful", sa.Boolean(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("corrected_incident_type", sa.String(length=100), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_feedback_rating"),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("feedback", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_feedback_incident_id"), ["incident_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_feedback_user_id"), ["user_id"], unique=False)

    op.create_table(
        "incident_analyses",
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("incident_analyses", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_incident_analyses_incident_id"), ["incident_id"], unique=False
        )

    op.create_table(
        "log_files",
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.CheckConstraint("size_bytes >= 0", name="ck_log_files_size"),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("log_files", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_log_files_incident_id"), ["incident_id"], unique=False)

    op.create_table(
        "log_events",
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("log_file_id", sa.String(length=36), nullable=False),
        sa.Column("source_line_number", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("service", sa.String(length=200), nullable=True),
        sa.Column("http_method", sa.String(length=20), nullable=True),
        sa.Column("endpoint", sa.Text(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("error_signature", sa.Text(), nullable=True),
        sa.Column("redacted_message", sa.Text(), nullable=False),
        sa.Column("is_evidence", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.CheckConstraint("source_line_number > 0", name="ck_log_events_line"),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
        ),
        sa.ForeignKeyConstraint(
            ["log_file_id"],
            ["log_files.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("log_file_id", "source_line_number", name="uq_log_events_file_line"),
    )
    with op.batch_alter_table("log_events", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_log_events_endpoint"), ["endpoint"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_log_events_incident_id"), ["incident_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_log_events_level"), ["level"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_log_events_log_file_id"), ["log_file_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_log_events_status_code"), ["status_code"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_log_events_timestamp"), ["timestamp"], unique=False)

    with op.batch_alter_table("incidents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("owner_user_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("description", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("severity", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("confirmed_root_cause", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("resolution_notes", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("incident_started_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("incident_ended_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            )
        )
        batch_op.create_index(
            batch_op.f("ix_incidents_owner_user_id"), ["owner_user_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_incidents_status"), ["status"], unique=False)
        batch_op.create_foreign_key(
            "fk_incidents_owner_user_id_users", "users", ["owner_user_id"], ["id"]
        )

    op.execute(sa.text("UPDATE incidents SET updated_at = created_at"))
    with op.batch_alter_table("incidents") as batch_op:
        batch_op.alter_column("updated_at", server_default=None)


def downgrade():
    # Frozen operations reviewed for the Phase 1 transition.
    with op.batch_alter_table("incidents", schema=None) as batch_op:
        batch_op.drop_constraint("fk_incidents_owner_user_id_users", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_incidents_status"))
        batch_op.drop_index(batch_op.f("ix_incidents_owner_user_id"))
        batch_op.drop_column("updated_at")
        batch_op.drop_column("incident_ended_at")
        batch_op.drop_column("incident_started_at")
        batch_op.drop_column("resolution_notes")
        batch_op.drop_column("confirmed_root_cause")
        batch_op.drop_column("severity")
        batch_op.drop_column("description")
        batch_op.drop_column("owner_user_id")

    with op.batch_alter_table("log_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_log_events_timestamp"))
        batch_op.drop_index(batch_op.f("ix_log_events_status_code"))
        batch_op.drop_index(batch_op.f("ix_log_events_log_file_id"))
        batch_op.drop_index(batch_op.f("ix_log_events_level"))
        batch_op.drop_index(batch_op.f("ix_log_events_incident_id"))
        batch_op.drop_index(batch_op.f("ix_log_events_endpoint"))

    op.drop_table("log_events")
    with op.batch_alter_table("log_files", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_log_files_incident_id"))

    op.drop_table("log_files")
    with op.batch_alter_table("incident_analyses", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_incident_analyses_incident_id"))

    op.drop_table("incident_analyses")
    with op.batch_alter_table("feedback", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_feedback_user_id"))
        batch_op.drop_index(batch_op.f("ix_feedback_incident_id"))

    op.drop_table("feedback")
    with op.batch_alter_table("analysis_jobs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_analysis_jobs_status"))
        batch_op.drop_index(batch_op.f("ix_analysis_jobs_incident_id"))

    op.drop_table("analysis_jobs")
    with op.batch_alter_table("refresh_tokens", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_refresh_tokens_user_id"))

    op.drop_table("refresh_tokens")
    with op.batch_alter_table("audit_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_audit_events_user_id"))
        batch_op.drop_index(batch_op.f("ix_audit_events_resource_id"))

    op.drop_table("audit_events")
    op.drop_table("users")
