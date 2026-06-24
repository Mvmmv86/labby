"""add final content production state

Revision ID: 018_content_production
Revises: 017_social_content_drafts
Create Date: 2026-06-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "018_content_production"
down_revision: str | None = "017_social_content_drafts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "social_content_drafts",
        sa.Column(
            "production_status",
            sa.String(length=30),
            nullable=False,
            server_default="not_started",
        ),
    )
    op.add_column(
        "social_content_drafts",
        sa.Column(
            "production_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "social_content_drafts",
        sa.Column(
            "production_payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "social_content_drafts",
        sa.Column("production_error_code", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "social_content_drafts",
        sa.Column("production_error_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "social_content_drafts",
        sa.Column("production_provider", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "social_content_drafts",
        sa.Column("production_model", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "social_content_drafts",
        sa.Column("production_input_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "social_content_drafts",
        sa.Column("production_output_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "social_content_drafts",
        sa.Column(
            "production_cost_usd",
            sa.Numeric(12, 6),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "social_content_drafts",
        sa.Column("production_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "social_content_drafts",
        sa.Column("production_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_social_content_drafts_production_status",
        "social_content_drafts",
        "production_status IN ('not_started', 'queued', 'running', 'ready', 'failed')",
    )
    op.create_check_constraint(
        "ck_social_content_drafts_production_version_nonnegative",
        "social_content_drafts",
        "production_version >= 0",
    )
    op.create_index(
        "ix_social_content_drafts_tenant_production_status",
        "social_content_drafts",
        ["tenant_id", "production_status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_social_content_drafts_tenant_production_status",
        table_name="social_content_drafts",
    )
    op.drop_constraint(
        "ck_social_content_drafts_production_version_nonnegative",
        "social_content_drafts",
        type_="check",
    )
    op.drop_constraint(
        "ck_social_content_drafts_production_status",
        "social_content_drafts",
        type_="check",
    )
    op.drop_column("social_content_drafts", "production_completed_at")
    op.drop_column("social_content_drafts", "production_started_at")
    op.drop_column("social_content_drafts", "production_cost_usd")
    op.drop_column("social_content_drafts", "production_output_tokens")
    op.drop_column("social_content_drafts", "production_input_tokens")
    op.drop_column("social_content_drafts", "production_model")
    op.drop_column("social_content_drafts", "production_provider")
    op.drop_column("social_content_drafts", "production_error_message")
    op.drop_column("social_content_drafts", "production_error_code")
    op.drop_column("social_content_drafts", "production_payload_json")
    op.drop_column("social_content_drafts", "production_version")
    op.drop_column("social_content_drafts", "production_status")
