"""add apify public reference sync state

Revision ID: 015_apify_public_reference_sync
Revises: 014_public_references
Create Date: 2026-06-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "015_apify_public_reference_sync"
down_revision: str | None = "014_public_references"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PUBLIC_REFERENCE_STATUSES = (
    "'manual_pending', 'pending', 'syncing', 'partially_synced', "
    "'synced', 'unavailable', 'failed'"
)
OLD_PUBLIC_REFERENCE_STATUSES = (
    "'manual_pending', 'pending', 'syncing', 'synced', 'unavailable', 'failed'"
)


def upgrade() -> None:
    op.add_column(
        "social_public_reference_profiles",
        sa.Column(
            "sync_generation",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "social_public_reference_profiles",
        sa.Column(
            "failure_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    op.drop_constraint(
        "ck_social_public_refs_source",
        "social_public_reference_profiles",
        type_="check",
    )
    op.create_check_constraint(
        "ck_social_public_refs_source",
        "social_public_reference_profiles",
        "source IN ('manual', 'phyllo', 'apify', 'meta_business_discovery', 'unknown')",
    )

    op.drop_constraint(
        "ck_social_public_refs_sync_status",
        "social_public_reference_profiles",
        type_="check",
    )
    op.create_check_constraint(
        "ck_social_public_refs_sync_status",
        "social_public_reference_profiles",
        f"sync_status IN ({PUBLIC_REFERENCE_STATUSES})",
    )

    op.drop_constraint(
        "ck_social_reference_profiles_sync_status",
        "social_reference_profiles",
        type_="check",
    )
    op.create_check_constraint(
        "ck_social_reference_profiles_sync_status",
        "social_reference_profiles",
        f"sync_status IN ({PUBLIC_REFERENCE_STATUSES})",
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE social_reference_profiles
        SET sync_status = 'synced'
        WHERE sync_status = 'partially_synced'
        """
    )
    op.execute(
        """
        UPDATE social_public_reference_profiles
        SET sync_status = 'synced'
        WHERE sync_status = 'partially_synced'
        """
    )
    op.execute(
        """
        UPDATE social_public_reference_profiles
        SET source = 'unknown'
        WHERE source = 'apify'
        """
    )

    op.drop_constraint(
        "ck_social_reference_profiles_sync_status",
        "social_reference_profiles",
        type_="check",
    )
    op.create_check_constraint(
        "ck_social_reference_profiles_sync_status",
        "social_reference_profiles",
        f"sync_status IN ({OLD_PUBLIC_REFERENCE_STATUSES})",
    )

    op.drop_constraint(
        "ck_social_public_refs_sync_status",
        "social_public_reference_profiles",
        type_="check",
    )
    op.create_check_constraint(
        "ck_social_public_refs_sync_status",
        "social_public_reference_profiles",
        f"sync_status IN ({OLD_PUBLIC_REFERENCE_STATUSES})",
    )

    op.drop_constraint(
        "ck_social_public_refs_source",
        "social_public_reference_profiles",
        type_="check",
    )
    op.create_check_constraint(
        "ck_social_public_refs_source",
        "social_public_reference_profiles",
        "source IN ('manual', 'phyllo', 'meta_business_discovery', 'unknown')",
    )

    op.drop_column("social_public_reference_profiles", "failure_count")
    op.drop_column("social_public_reference_profiles", "sync_generation")
