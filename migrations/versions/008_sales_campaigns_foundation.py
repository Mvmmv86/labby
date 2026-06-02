"""sales campaigns foundation

Revision ID: 008_sales_campaigns_foundation
Revises: 007_sales_inbox_foundation
Create Date: 2026-06-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "008_sales_campaigns_foundation"
down_revision: str | None = "007_sales_inbox_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE sales_campaigns (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            channel_id UUID REFERENCES sales_channels(id) ON DELETE SET NULL,
            name VARCHAR(180) NOT NULL,
            description TEXT,
            message_type VARCHAR(20) NOT NULL DEFAULT 'text',
            content TEXT NOT NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'draft',
            idempotency_key VARCHAR(255) NOT NULL,
            scheduled_at TIMESTAMPTZ,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            total_recipients INTEGER NOT NULL DEFAULT 0,
            queued_count INTEGER NOT NULL DEFAULT 0,
            sent_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            skipped_count INTEGER NOT NULL DEFAULT 0,
            created_by_membership_id UUID REFERENCES memberships(id) ON DELETE SET NULL,
            updated_by_membership_id UUID REFERENCES memberships(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_sales_campaigns_message_type
                CHECK (message_type IN ('text', 'image', 'video', 'document')),
            CONSTRAINT ck_sales_campaigns_status
                CHECK (
                    status IN (
                        'draft', 'ativa', 'scheduled', 'sending', 'queued',
                        'sent', 'paused', 'cancelled', 'failed'
                    )
                ),
            CONSTRAINT ck_sales_campaigns_counts_non_negative
                CHECK (
                    total_recipients >= 0
                    AND queued_count >= 0
                    AND sent_count >= 0
                    AND failed_count >= 0
                    AND skipped_count >= 0
                )
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_sales_campaigns_tenant_idempotency
        ON sales_campaigns(tenant_id, idempotency_key)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_campaigns_tenant_status_created
        ON sales_campaigns(tenant_id, status, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_campaigns_tenant_scheduled
        ON sales_campaigns(tenant_id, scheduled_at)
        WHERE scheduled_at IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_campaigns_channel
        ON sales_campaigns(channel_id)
        """
    )

    op.execute(
        """
        CREATE TABLE sales_campaign_recipients (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            campaign_id UUID NOT NULL REFERENCES sales_campaigns(id) ON DELETE CASCADE,
            contact_id UUID REFERENCES sales_contacts(id) ON DELETE SET NULL,
            conversation_id UUID REFERENCES sales_conversations(id) ON DELETE SET NULL,
            message_id UUID REFERENCES sales_messages(id) ON DELETE SET NULL,
            recipient_name VARCHAR(180),
            phone_normalized VARCHAR(40),
            status VARCHAR(30) NOT NULL DEFAULT 'pending',
            error TEXT,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            queued_at TIMESTAMPTZ,
            sent_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_sales_campaign_recipients_status
                CHECK (status IN ('pending', 'queued', 'sent', 'failed', 'skipped'))
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_sales_campaign_recipients_campaign_contact
        ON sales_campaign_recipients(tenant_id, campaign_id, contact_id)
        WHERE contact_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_campaign_recipients_campaign_status
        ON sales_campaign_recipients(tenant_id, campaign_id, status)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_campaign_recipients_contact
        ON sales_campaign_recipients(contact_id)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_campaign_recipients_message
        ON sales_campaign_recipients(message_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_sales_campaign_recipients_message")
    op.execute("DROP INDEX IF EXISTS ix_sales_campaign_recipients_contact")
    op.execute("DROP INDEX IF EXISTS ix_sales_campaign_recipients_campaign_status")
    op.execute("DROP INDEX IF EXISTS uq_sales_campaign_recipients_campaign_contact")
    op.execute("DROP TABLE IF EXISTS sales_campaign_recipients")
    op.execute("DROP INDEX IF EXISTS ix_sales_campaigns_channel")
    op.execute("DROP INDEX IF EXISTS ix_sales_campaigns_tenant_scheduled")
    op.execute("DROP INDEX IF EXISTS ix_sales_campaigns_tenant_status_created")
    op.execute("DROP INDEX IF EXISTS uq_sales_campaigns_tenant_idempotency")
    op.execute("DROP TABLE IF EXISTS sales_campaigns")
