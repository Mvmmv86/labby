"""add social content drafts

Revision ID: 017_social_content_drafts
Revises: 016_social_plan_calendar
Create Date: 2026-06-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "017_social_content_drafts"
down_revision: str | None = "016_social_plan_calendar"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "social_content_drafts",
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
            "calendar_entry_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("social_content_calendar_entries.id", ondelete="CASCADE"),
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
        sa.Column("draft_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("format", sa.String(length=40), nullable=False),
        sa.Column("channel", sa.String(length=40), nullable=False, server_default="instagram"),
        sa.Column("title", sa.String(length=220), nullable=False),
        sa.Column("angle", sa.Text(), nullable=True),
        sa.Column("hook", sa.Text(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("cta", sa.Text(), nullable=True),
        sa.Column("visual_direction", sa.Text(), nullable=True),
        sa.Column(
            "script_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "production_checklist_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "evidence_json",
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
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
            "status IN ('draft', 'in_review', 'approved', 'archived')",
            name="ck_social_content_drafts_status",
        ),
        sa.CheckConstraint("draft_version > 0", name="ck_social_content_drafts_version_positive"),
        sa.UniqueConstraint(
            "tenant_id",
            "calendar_entry_id",
            "draft_version",
            name="uq_social_content_drafts_entry_version",
        ),
    )
    op.create_index(
        "uq_social_content_drafts_current_entry",
        "social_content_drafts",
        ["tenant_id", "calendar_entry_id"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
    )
    op.create_index(
        "ix_social_content_drafts_tenant_entry_current",
        "social_content_drafts",
        ["tenant_id", "calendar_entry_id", "is_current"],
    )
    op.create_index(
        "ix_social_content_drafts_tenant_status_updated",
        "social_content_drafts",
        ["tenant_id", "status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_social_content_drafts_tenant_status_updated",
        table_name="social_content_drafts",
    )
    op.drop_index(
        "ix_social_content_drafts_tenant_entry_current",
        table_name="social_content_drafts",
    )
    op.drop_index(
        "uq_social_content_drafts_current_entry",
        table_name="social_content_drafts",
    )
    op.drop_table("social_content_drafts")
