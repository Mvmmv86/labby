"""sales contacts foundation

Revision ID: 006_sales_contacts_foundation
Revises: 005_social_news_schedules
Create Date: 2026-06-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "006_sales_contacts_foundation"
down_revision: str | None = "005_social_news_schedules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE sales_contacts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            name VARCHAR(180) NOT NULL,
            phone VARCHAR(40),
            phone_normalized VARCHAR(40),
            email_normalized VARCHAR(320),
            group_name VARCHAR(120),
            tags JSONB NOT NULL DEFAULT '[]'::jsonb,
            notes TEXT,
            custom_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(30) NOT NULL DEFAULT 'active',
            optout BOOLEAN NOT NULL DEFAULT false,
            total_messages_sent INTEGER NOT NULL DEFAULT 0,
            total_messages_received INTEGER NOT NULL DEFAULT 0,
            last_interaction_at TIMESTAMPTZ,
            created_by_membership_id UUID REFERENCES memberships(id) ON DELETE SET NULL,
            updated_by_membership_id UUID REFERENCES memberships(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_sales_contacts_status
                CHECK (status IN ('active', 'archived', 'blocked')),
            CONSTRAINT ck_sales_contacts_total_messages_sent_non_negative
                CHECK (total_messages_sent >= 0),
            CONSTRAINT ck_sales_contacts_total_messages_received_non_negative
                CHECK (total_messages_received >= 0)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_sales_contacts_tenant_phone_normalized
        ON sales_contacts(tenant_id, phone_normalized)
        WHERE phone_normalized IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_contacts_tenant_status_created_at
        ON sales_contacts(tenant_id, status, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_contacts_tenant_group_name
        ON sales_contacts(tenant_id, group_name)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_contacts_tenant_last_interaction
        ON sales_contacts(tenant_id, last_interaction_at)
        """
    )
    op.execute("CREATE INDEX ix_sales_contacts_tags_gin ON sales_contacts USING gin(tags)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_sales_contacts_tags_gin")
    op.execute("DROP INDEX IF EXISTS ix_sales_contacts_tenant_last_interaction")
    op.execute("DROP INDEX IF EXISTS ix_sales_contacts_tenant_group_name")
    op.execute("DROP INDEX IF EXISTS ix_sales_contacts_tenant_status_created_at")
    op.execute("DROP INDEX IF EXISTS uq_sales_contacts_tenant_phone_normalized")
    op.execute("DROP TABLE IF EXISTS sales_contacts")
