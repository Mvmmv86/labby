"""add social public reference foundation

Revision ID: 014_public_references
Revises: 013_social_connected_truth
Create Date: 2026-06-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "014_public_references"
down_revision: str | None = "013_social_connected_truth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "social_public_reference_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("handle", sa.String(length=180), nullable=False),
        sa.Column("display_name", sa.String(length=180), nullable=True),
        sa.Column("profile_url", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=60), nullable=False, server_default="manual"),
        sa.Column(
            "sync_status",
            sa.String(length=40),
            nullable=False,
            server_default="manual_pending",
        ),
        sa.Column(
            "profile_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "raw_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "data_truth",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_sync_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "provider IN ('instagram', 'youtube', 'x', 'linkedin', 'fake')",
            name="ck_social_public_refs_provider",
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'phyllo', 'meta_business_discovery', 'unknown')",
            name="ck_social_public_refs_source",
        ),
        sa.CheckConstraint(
            "sync_status IN ("
            "'manual_pending', 'pending', 'syncing', 'synced', 'unavailable', 'failed'"
            ")",
            name="ck_social_public_refs_sync_status",
        ),
        sa.UniqueConstraint("provider", "handle", name="uq_social_public_refs_provider_handle"),
    )
    op.create_index(
        "ix_social_public_refs_sync",
        "social_public_reference_profiles",
        ["provider", "sync_status", "updated_at"],
    )
    op.create_index(
        "ix_social_public_refs_next_sync",
        "social_public_reference_profiles",
        ["next_sync_after", "sync_status"],
    )

    op.create_table(
        "social_public_reference_contents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "reference_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("social_public_reference_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("external_id", sa.String(length=220), nullable=False),
        sa.Column("content_type", sa.String(length=60), nullable=False),
        sa.Column("content_format", sa.String(length=60), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content_url", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metrics_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "raw_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "data_truth",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("engagement_rate_by_followers", sa.Numeric(10, 2), nullable=True),
        sa.Column("engagement_rate_by_reach", sa.Numeric(10, 2), nullable=True),
        sa.Column("performance_score", sa.Numeric(12, 2), nullable=True),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "provider IN ('instagram', 'youtube', 'x', 'linkedin', 'fake')",
            name="ck_social_public_ref_contents_provider",
        ),
        sa.UniqueConstraint(
            "reference_profile_id",
            "external_id",
            name="uq_social_public_ref_contents_profile_external",
        ),
    )
    op.create_index(
        "ix_social_public_ref_contents_profile_published",
        "social_public_reference_contents",
        ["reference_profile_id", "published_at"],
    )
    op.create_index(
        "ix_social_public_ref_contents_profile_score",
        "social_public_reference_contents",
        ["reference_profile_id", "performance_score"],
    )

    op.add_column(
        "social_reference_profiles",
        sa.Column("public_reference_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "social_reference_profiles",
        sa.Column(
            "sync_status",
            sa.String(length=40),
            nullable=False,
            server_default="manual_pending",
        ),
    )
    op.add_column(
        "social_reference_profiles",
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "social_reference_profiles",
        sa.Column(
            "comparison_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_check_constraint(
        "ck_social_reference_profiles_sync_status",
        "social_reference_profiles",
        "sync_status IN ("
        "'manual_pending', 'pending', 'syncing', 'synced', 'unavailable', 'failed'"
        ")",
    )
    op.create_foreign_key(
        "fk_social_reference_profiles_public_ref",
        "social_reference_profiles",
        "social_public_reference_profiles",
        ["public_reference_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_social_reference_profiles_public_ref",
        "social_reference_profiles",
        ["public_reference_profile_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_social_reference_profiles_public_ref", table_name="social_reference_profiles")
    op.drop_constraint(
        "fk_social_reference_profiles_public_ref",
        "social_reference_profiles",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_social_reference_profiles_sync_status",
        "social_reference_profiles",
        type_="check",
    )
    op.drop_column("social_reference_profiles", "comparison_summary")
    op.drop_column("social_reference_profiles", "last_synced_at")
    op.drop_column("social_reference_profiles", "sync_status")
    op.drop_column("social_reference_profiles", "public_reference_profile_id")

    op.drop_index(
        "ix_social_public_ref_contents_profile_score",
        table_name="social_public_reference_contents",
    )
    op.drop_index(
        "ix_social_public_ref_contents_profile_published",
        table_name="social_public_reference_contents",
    )
    op.drop_table("social_public_reference_contents")

    op.drop_index("ix_social_public_refs_next_sync", table_name="social_public_reference_profiles")
    op.drop_index("ix_social_public_refs_sync", table_name="social_public_reference_profiles")
    op.drop_table("social_public_reference_profiles")
