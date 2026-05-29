"""identity foundation

Revision ID: 001_identity_foundation
Revises:
Create Date: 2026-05-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_identity_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("nome", sa.String(length=160), nullable=False),
        sa.Column("email_normalized", sa.String(length=320), nullable=False),
        sa.Column("senha_hash", sa.Text(), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ativo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email_normalized", name="uq_users_email_normalized"),
    )
    op.create_index("ix_users_email_normalized", "users", ["email_normalized"])

    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("nome", sa.String(length=180), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("plano", sa.String(length=40), server_default="trial", nullable=False),
        sa.Column("ativo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "config",
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"])

    op.create_table(
        "memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("default_module", sa.String(length=40), server_default="sales", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("last_access_at", sa.DateTime(timezone=True), nullable=True),
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
            "role IN ('owner', 'admin', 'agent', 'viewer')",
            name="ck_memberships_role",
        ),
        sa.CheckConstraint(
            "default_module IN ('sales', 'social_media')",
            name="ck_memberships_default_module",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled', 'invited')",
            name="ck_memberships_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "tenant_id", name="uq_memberships_user_tenant"),
    )
    op.create_index("ix_memberships_tenant_id", "memberships", ["tenant_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    op.create_table(
        "membership_modules",
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module_key", sa.String(length=40), nullable=False),
        sa.Column("granted_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "module_key IN ('sales', 'social_media')",
            name="ck_membership_modules_module_key",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_membership_id"], ["memberships.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("membership_id", "module_key"),
    )

    op.create_table(
        "team_invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invited_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email_normalized", sa.String(length=320), nullable=False),
        sa.Column("nome", sa.String(length=160), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("default_module", sa.String(length=40), nullable=False),
        sa.Column(
            "module_keys",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resend_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
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
            "role IN ('admin', 'agent', 'viewer')",
            name="ck_team_invites_role",
        ),
        sa.CheckConstraint(
            "default_module IN ('sales', 'social_media')",
            name="ck_team_invites_default_module",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked', 'expired')",
            name="ck_team_invites_status",
        ),
        sa.ForeignKeyConstraint(
            ["accepted_by_membership_id"], ["memberships.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["invited_by_membership_id"], ["memberships.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_team_invites_token_hash"),
    )
    op.create_index("ix_team_invites_email_normalized", "team_invites", ["email_normalized"])
    op.create_index("ix_team_invites_tenant_id", "team_invites", ["tenant_id"])
    op.create_index(
        "uq_team_invites_pending_tenant_email",
        "team_invites",
        ["tenant_id", "email_normalized"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_team_invites_pending_tenant_email", table_name="team_invites")
    op.drop_index("ix_team_invites_tenant_id", table_name="team_invites")
    op.drop_index("ix_team_invites_email_normalized", table_name="team_invites")
    op.drop_table("team_invites")
    op.drop_table("membership_modules")
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_index("ix_memberships_tenant_id", table_name="memberships")
    op.drop_table("memberships")
    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")
    op.drop_index("ix_users_email_normalized", table_name="users")
    op.drop_table("users")
