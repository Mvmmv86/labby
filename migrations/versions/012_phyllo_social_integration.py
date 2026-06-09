"""phyllo social integration

Revision ID: 012_phyllo_social_integration
Revises: 011_social_onboarding_foundation
Create Date: 2026-06-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "012_phyllo_social_integration"
down_revision: str | None = "011_social_onboarding_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "social_phyllo_users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("environment", sa.String(length=30), nullable=False),
        sa.Column("phyllo_user_id", sa.String(length=120), nullable=False),
        sa.Column("external_id", sa.String(length=220), nullable=False),
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
            "environment IN ('sandbox', 'staging', 'production')",
            name="ck_social_phyllo_users_environment",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_social_phyllo_users_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id"],
            ["memberships.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "environment",
            name="uq_social_phyllo_users_tenant_environment",
        ),
        sa.UniqueConstraint(
            "environment",
            "phyllo_user_id",
            name="uq_social_phyllo_users_environment_user",
        ),
        sa.UniqueConstraint(
            "environment",
            "external_id",
            name="uq_social_phyllo_users_environment_external",
        ),
    )
    op.create_index(
        "ix_social_phyllo_users_tenant_status",
        "social_phyllo_users",
        ["tenant_id", "status"],
    )

    op.create_table(
        "social_phyllo_accounts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("onboarding_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("environment", sa.String(length=30), nullable=False),
        sa.Column("phyllo_user_id", sa.String(length=120), nullable=False),
        sa.Column("phyllo_account_id", sa.String(length=120), nullable=False),
        sa.Column("phyllo_profile_id", sa.String(length=120), nullable=True),
        sa.Column("work_platform_id", sa.String(length=120), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("handle", sa.String(length=180), nullable=True),
        sa.Column("display_name", sa.String(length=180), nullable=True),
        sa.Column("profile_url", sa.Text(), nullable=True),
        sa.Column("account_status", sa.String(length=60), nullable=True),
        sa.Column(
            "raw_account",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "raw_profile",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "connected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
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
            "environment IN ('sandbox', 'staging', 'production')",
            name="ck_social_phyllo_accounts_environment",
        ),
        sa.CheckConstraint(
            "provider IN ('instagram', 'youtube', 'x', 'linkedin', 'fake')",
            name="ck_social_phyllo_accounts_provider",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["onboarding_session_id"],
            ["social_onboarding_sessions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "environment",
            "phyllo_account_id",
            name="uq_social_phyllo_accounts_tenant_environment_account",
        ),
    )
    op.create_index(
        "ix_social_phyllo_accounts_tenant_provider_status",
        "social_phyllo_accounts",
        ["tenant_id", "provider", "account_status"],
    )
    op.create_index(
        "ix_social_phyllo_accounts_environment_user",
        "social_phyllo_accounts",
        ["environment", "phyllo_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_social_phyllo_accounts_environment_user",
        table_name="social_phyllo_accounts",
    )
    op.drop_index(
        "ix_social_phyllo_accounts_tenant_provider_status",
        table_name="social_phyllo_accounts",
    )
    op.drop_table("social_phyllo_accounts")
    op.drop_index("ix_social_phyllo_users_tenant_status", table_name="social_phyllo_users")
    op.drop_table("social_phyllo_users")
