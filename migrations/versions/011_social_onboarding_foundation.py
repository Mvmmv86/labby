"""social onboarding foundation

Revision ID: 011_social_onboarding_foundation
Revises: 010_sales_outbound_dispatch
Create Date: 2026-06-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "011_social_onboarding_foundation"
down_revision: str | None = "010_sales_outbound_dispatch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "social_onboarding_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("objective", sa.String(length=60), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="draft", nullable=False),
        sa.Column("primary_provider", sa.String(length=40), nullable=True),
        sa.Column("connection_mode", sa.String(length=30), server_default="none", nullable=False),
        sa.Column("connected_account_id", sa.String(length=180), nullable=True),
        sa.Column("connected_account_handle", sa.String(length=180), nullable=True),
        sa.Column("connected_account_name", sa.String(length=180), nullable=True),
        sa.Column("profile_url", sa.Text(), nullable=True),
        sa.Column(
            "progress_steps",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "profile_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "analysis_report",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("analysis_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("analysis_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("analysis_completed_at", sa.DateTime(timezone=True), nullable=True),
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
            "objective IS NULL OR objective IN ("
            "'grow_audience', 'sell_more', 'authority', 'content_ops', 'benchmarking'"
            ")",
            name="ck_social_onboarding_sessions_objective",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'connecting', 'analyzing', 'ready', 'failed', 'archived')",
            name="ck_social_onboarding_sessions_status",
        ),
        sa.CheckConstraint(
            "primary_provider IS NULL OR primary_provider IN "
            "('instagram', 'youtube', 'x', 'linkedin', 'fake')",
            name="ck_social_onboarding_sessions_provider",
        ),
        sa.CheckConstraint(
            "connection_mode IN ('none', 'simulated', 'oauth')",
            name="ck_social_onboarding_sessions_connection_mode",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id"],
            ["memberships.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_membership_id"],
            ["memberships.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_social_onboarding_sessions_tenant_status_created",
        "social_onboarding_sessions",
        ["tenant_id", "status", "created_at"],
    )
    op.create_index(
        "ix_social_onboarding_sessions_tenant_provider_account",
        "social_onboarding_sessions",
        ["tenant_id", "primary_provider", "connected_account_id"],
    )
    op.create_index(
        "uq_social_onboarding_sessions_one_active_per_tenant",
        "social_onboarding_sessions",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'archived'"),
    )

    op.create_table(
        "social_reference_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("onboarding_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("handle", sa.String(length=180), nullable=False),
        sa.Column("label", sa.String(length=180), nullable=True),
        sa.Column("profile_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="active", nullable=False),
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "provider IN ('instagram', 'youtube', 'x', 'linkedin', 'fake')",
            name="ck_social_reference_profiles_provider",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_social_reference_profiles_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["onboarding_session_id"],
            ["social_onboarding_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id"],
            ["memberships.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "onboarding_session_id",
            "provider",
            "handle",
            name="uq_social_reference_profiles_session_provider_handle",
        ),
    )
    op.create_index(
        "ix_social_reference_profiles_tenant_session_status",
        "social_reference_profiles",
        ["tenant_id", "onboarding_session_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_social_reference_profiles_tenant_session_status",
        table_name="social_reference_profiles",
    )
    op.drop_table("social_reference_profiles")
    op.drop_index(
        "ix_social_onboarding_sessions_tenant_provider_account",
        table_name="social_onboarding_sessions",
    )
    op.drop_index(
        "uq_social_onboarding_sessions_one_active_per_tenant",
        table_name="social_onboarding_sessions",
    )
    op.drop_index(
        "ix_social_onboarding_sessions_tenant_status_created",
        table_name="social_onboarding_sessions",
    )
    op.drop_table("social_onboarding_sessions")
