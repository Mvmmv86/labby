"""scalability indexes

Revision ID: 002_scalability_indexes
Revises: 001_identity_foundation
Create Date: 2026-05-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "002_scalability_indexes"
down_revision: str | None = "001_identity_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_memberships_tenant_status_created_at",
        "memberships",
        ["tenant_id", "status", "created_at"],
    )
    op.create_index(
        "ix_memberships_user_status_last_access_at",
        "memberships",
        ["user_id", "status", "last_access_at"],
    )
    op.create_index(
        "ix_membership_modules_module_key_membership_id",
        "membership_modules",
        ["module_key", "membership_id"],
    )
    op.create_index(
        "ix_team_invites_tenant_status_created_at",
        "team_invites",
        ["tenant_id", "status", "created_at"],
    )
    op.create_index(
        "ix_team_invites_tenant_email_status",
        "team_invites",
        ["tenant_id", "email_normalized", "status"],
    )
    op.create_index(
        "ix_team_invites_pending_expires_at",
        "team_invites",
        ["expires_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("ix_team_invites_pending_expires_at", table_name="team_invites")
    op.drop_index("ix_team_invites_tenant_email_status", table_name="team_invites")
    op.drop_index("ix_team_invites_tenant_status_created_at", table_name="team_invites")
    op.drop_index(
        "ix_membership_modules_module_key_membership_id",
        table_name="membership_modules",
    )
    op.drop_index("ix_memberships_user_status_last_access_at", table_name="memberships")
    op.drop_index("ix_memberships_tenant_status_created_at", table_name="memberships")
