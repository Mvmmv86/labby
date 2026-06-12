"""social connected content truth

Revision ID: 013_social_connected_truth
Revises: 012_phyllo_social_integration
Create Date: 2026-06-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "013_social_connected_truth"
down_revision: str | None = "012_phyllo_social_integration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "social_connected_contents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("onboarding_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("environment", sa.String(length=30), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("phyllo_account_id", sa.String(length=120), nullable=False),
        sa.Column("external_id", sa.String(length=220), nullable=False),
        sa.Column("phyllo_content_id", sa.String(length=120), nullable=True),
        sa.Column("content_type", sa.String(length=60), nullable=False),
        sa.Column("content_format", sa.String(length=60), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content_url", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metrics_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "raw_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "data_truth",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("engagement_rate_by_followers", sa.Numeric(10, 2), nullable=True),
        sa.Column("engagement_rate_by_reach", sa.Numeric(10, 2), nullable=True),
        sa.Column("performance_score", sa.Numeric(12, 2), nullable=True),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
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
            name="ck_social_connected_contents_provider",
        ),
        sa.CheckConstraint(
            "environment IN ('sandbox', 'staging', 'production')",
            name="ck_social_connected_contents_environment",
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
            "provider",
            "external_id",
            name="uq_social_connected_contents_tenant_env_provider_external",
        ),
    )
    op.create_index(
        "ix_social_connected_contents_tenant_account_published",
        "social_connected_contents",
        ["tenant_id", "environment", "phyllo_account_id", "published_at"],
    )
    op.create_index(
        "ix_social_connected_contents_tenant_session_score",
        "social_connected_contents",
        ["tenant_id", "environment", "onboarding_session_id", "performance_score"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_social_connected_contents_tenant_session_score",
        table_name="social_connected_contents",
    )
    op.drop_index(
        "ix_social_connected_contents_tenant_account_published",
        table_name="social_connected_contents",
    )
    op.drop_table("social_connected_contents")
