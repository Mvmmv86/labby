"""add social action plan and calendar

Revision ID: 016_social_plan_calendar
Revises: 015_apify_public_reference_sync
Create Date: 2026-06-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "016_social_plan_calendar"
down_revision: str | None = "015_apify_public_reference_sync"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "social_action_plans",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "onboarding_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("social_onboarding_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_membership_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by_membership_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
        sa.Column("source_analysis_version", sa.Integer(), nullable=False),
        sa.Column("source_specialist_version", sa.String(length=80), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
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
            "status IN ('active', 'archived')",
            name="ck_social_action_plans_status",
        ),
    )
    op.create_index(
        "ix_social_action_plans_tenant_session_status",
        "social_action_plans",
        ["tenant_id", "onboarding_session_id", "status"],
    )
    op.create_index(
        "uq_social_action_plans_active_session",
        "social_action_plans",
        ["tenant_id", "onboarding_session_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "social_action_plan_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "action_plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("social_action_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "onboarding_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("social_onboarding_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("why_it_matters", sa.Text(), nullable=True),
        sa.Column("how_to_execute", sa.Text(), nullable=True),
        sa.Column("expected_signal", sa.Text(), nullable=True),
        sa.Column("measurement", sa.Text(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column(
            "source_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
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
            "priority IN ('low', 'medium', 'high')",
            name="ck_social_action_plan_items_priority",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'pending', 'in_progress', 'approved', 'sent_to_calendar', 'done', 'archived'"
            ")",
            name="ck_social_action_plan_items_status",
        ),
        sa.UniqueConstraint(
            "action_plan_id",
            "position",
            name="uq_social_action_plan_items_plan_position",
        ),
    )
    op.create_index(
        "ix_social_action_plan_items_tenant_plan_position",
        "social_action_plan_items",
        ["tenant_id", "action_plan_id", "position"],
    )
    op.create_index(
        "ix_social_action_plan_items_tenant_status",
        "social_action_plan_items",
        ["tenant_id", "status", "updated_at"],
    )

    op.create_table(
        "social_content_calendar_entries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "action_plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("social_action_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "action_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("social_action_plan_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "onboarding_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("social_onboarding_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("day_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("format", sa.String(length=40), nullable=False),
        sa.Column("channel", sa.String(length=40), nullable=False, server_default="instagram"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("theme", sa.Text(), nullable=True),
        sa.Column("hook", sa.Text(), nullable=True),
        sa.Column("caption_outline", sa.Text(), nullable=True),
        sa.Column("cta", sa.Text(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("source_reference_handle", sa.String(length=180), nullable=True),
        sa.Column(
            "metrics_goal_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
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
            "channel IN ('instagram', 'youtube', 'x', 'linkedin', 'multi')",
            name="ck_social_content_calendar_entries_channel",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'planned', 'approved', 'scheduled', 'published', 'archived')",
            name="ck_social_content_calendar_entries_status",
        ),
    )
    op.create_index(
        "ix_social_content_calendar_tenant_plan_day",
        "social_content_calendar_entries",
        ["tenant_id", "action_plan_id", "day_index"],
    )
    op.create_index(
        "ix_social_content_calendar_tenant_scheduled",
        "social_content_calendar_entries",
        ["tenant_id", "scheduled_at", "status"],
    )
    op.create_index(
        "ix_social_content_calendar_action_item",
        "social_content_calendar_entries",
        ["action_item_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_social_content_calendar_action_item",
        table_name="social_content_calendar_entries",
    )
    op.drop_index(
        "ix_social_content_calendar_tenant_scheduled",
        table_name="social_content_calendar_entries",
    )
    op.drop_index(
        "ix_social_content_calendar_tenant_plan_day",
        table_name="social_content_calendar_entries",
    )
    op.drop_table("social_content_calendar_entries")

    op.drop_index(
        "ix_social_action_plan_items_tenant_status",
        table_name="social_action_plan_items",
    )
    op.drop_index(
        "ix_social_action_plan_items_tenant_plan_position",
        table_name="social_action_plan_items",
    )
    op.drop_table("social_action_plan_items")

    op.drop_index(
        "uq_social_action_plans_active_session",
        table_name="social_action_plans",
    )
    op.drop_index(
        "ix_social_action_plans_tenant_session_status",
        table_name="social_action_plans",
    )
    op.drop_table("social_action_plans")
