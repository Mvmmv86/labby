"""jobs outbox foundation

Revision ID: 003_jobs_outbox_foundation
Revises: 002_scalability_indexes
Create Date: 2026-06-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003_jobs_outbox_foundation"
down_revision: str | None = "002_scalability_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_type", sa.String(length=120), nullable=False),
        sa.Column("queue_name", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="pending", nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column(
            "run_after",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=160), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'retrying', 'running', 'succeeded', "
            "'dead_letter', 'cancelled')",
            name="ck_jobs_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_jobs_attempts_non_negative"),
        sa.CheckConstraint("max_attempts > 0", name="ck_jobs_max_attempts_positive"),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "job_type",
            "idempotency_key",
            name="uq_jobs_tenant_type_idempotency",
        ),
    )
    op.create_index("ix_jobs_tenant_status_run_after", "jobs", ["tenant_id", "status", "run_after"])
    op.create_index(
        "ix_jobs_queue_status_priority_run_after",
        "jobs",
        ["queue_name", "status", "priority", "run_after"],
    )
    op.create_index(
        "ix_jobs_tenant_type_created_at",
        "jobs",
        ["tenant_id", "job_type", "created_at"],
    )

    op.create_table(
        "job_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="running", nullable=False),
        sa.Column("worker_name", sa.String(length=160), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_job_attempts_status",
        ),
        sa.CheckConstraint("attempt_number > 0", name="ck_job_attempts_attempt_positive"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_job_attempts_job_attempt_number",
        "job_attempts",
        ["job_id", "attempt_number"],
    )
    op.create_index(
        "ix_job_attempts_tenant_status_started_at",
        "job_attempts",
        ["tenant_id", "status", "started_at"],
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("aggregate_type", sa.String(length=120), nullable=False),
        sa.Column("aggregate_id", sa.String(length=160), nullable=True),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=30), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column(
            "run_after",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=160), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'publishing', 'published', 'retrying', "
            "'dead_letter', 'cancelled')",
            name="ck_outbox_events_status",
        ),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "event_type",
            "idempotency_key",
            name="uq_outbox_events_tenant_type_idempotency",
        ),
    )
    op.create_index(
        "ix_outbox_events_tenant_status_run_after",
        "outbox_events",
        ["tenant_id", "status", "run_after"],
    )
    op.create_index(
        "ix_outbox_events_aggregate",
        "outbox_events",
        ["tenant_id", "aggregate_type", "aggregate_id"],
    )

    op.create_table(
        "webhook_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("external_event_id", sa.String(length=180), nullable=True),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False),
        sa.Column("signature_valid", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "headers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=30), server_default="received", nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('received', 'processing', 'processed', 'failed', 'ignored')",
            name="ck_webhook_events_status",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "provider",
            "idempotency_key",
            name="uq_webhook_events_tenant_provider_idempotency",
        ),
    )
    op.create_index(
        "ix_webhook_events_tenant_status_received_at",
        "webhook_events",
        ["tenant_id", "status", "received_at"],
    )
    op.create_index(
        "ix_webhook_events_provider_external_id",
        "webhook_events",
        ["provider", "external_event_id"],
    )

    op.create_table(
        "rate_limit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("rate_limit_key", sa.String(length=180), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("outcome", sa.String(length=30), nullable=False),
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "outcome IN ('allowed', 'blocked')",
            name="ck_rate_limit_events_outcome",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rate_limit_events_tenant_provider_created_at",
        "rate_limit_events",
        ["tenant_id", "provider", "created_at"],
    )
    op.create_index(
        "ix_rate_limit_events_tenant_key_created_at",
        "rate_limit_events",
        ["tenant_id", "rate_limit_key", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_rate_limit_events_tenant_key_created_at", table_name="rate_limit_events")
    op.drop_index("ix_rate_limit_events_tenant_provider_created_at", table_name="rate_limit_events")
    op.drop_table("rate_limit_events")
    op.drop_index("ix_webhook_events_provider_external_id", table_name="webhook_events")
    op.drop_index("ix_webhook_events_tenant_status_received_at", table_name="webhook_events")
    op.drop_table("webhook_events")
    op.drop_index("ix_outbox_events_aggregate", table_name="outbox_events")
    op.drop_index("ix_outbox_events_tenant_status_run_after", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_job_attempts_tenant_status_started_at", table_name="job_attempts")
    op.drop_index("ix_job_attempts_job_attempt_number", table_name="job_attempts")
    op.drop_table("job_attempts")
    op.drop_index("ix_jobs_tenant_type_created_at", table_name="jobs")
    op.drop_index("ix_jobs_queue_status_priority_run_after", table_name="jobs")
    op.drop_index("ix_jobs_tenant_status_run_after", table_name="jobs")
    op.drop_table("jobs")
