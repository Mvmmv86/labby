"""sales outbound dispatch

Revision ID: 010_sales_outbound_dispatch
Revises: 009_sales_bots_widget_foundation
Create Date: 2026-06-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "010_sales_outbound_dispatch"
down_revision: str | None = "009_sales_bots_widget_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE sales_messages
        DROP CONSTRAINT ck_sales_messages_status
        """
    )
    op.execute(
        """
        ALTER TABLE sales_messages
        ADD CONSTRAINT ck_sales_messages_status
        CHECK (status IN ('pending', 'sending', 'sent', 'delivered', 'read', 'failed'))
        """
    )
    op.execute(
        """
        ALTER TABLE sales_messages
        ADD COLUMN delivery_provider VARCHAR(40),
        ADD COLUMN delivery_external_id VARCHAR(255),
        ADD COLUMN dispatched_at TIMESTAMPTZ
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_messages_tenant_outbound_pending
        ON sales_messages(tenant_id, status, created_at)
        WHERE direction = 'saida' AND status IN ('pending', 'sending')
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_sales_messages_tenant_delivery_external
        ON sales_messages(tenant_id, delivery_provider, delivery_external_id)
        WHERE delivery_provider IS NOT NULL AND delivery_external_id IS NOT NULL
        """
    )

    op.execute(
        """
        CREATE TABLE sales_message_dispatch_attempts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            message_id UUID NOT NULL REFERENCES sales_messages(id) ON DELETE CASCADE,
            channel_id UUID REFERENCES sales_channels(id) ON DELETE SET NULL,
            provider VARCHAR(40) NOT NULL,
            idempotency_key VARCHAR(255) NOT NULL,
            status VARCHAR(30) NOT NULL,
            provider_external_id VARCHAR(255),
            request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            response_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            error_code VARCHAR(120),
            error_message TEXT,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_sales_message_dispatch_attempts_status
                CHECK (status IN ('sending', 'sent', 'failed', 'skipped'))
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_sales_message_dispatch_attempts_tenant_provider_key
        ON sales_message_dispatch_attempts(tenant_id, provider, idempotency_key)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_message_dispatch_attempts_message
        ON sales_message_dispatch_attempts(message_id)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_message_dispatch_attempts_tenant_status_created
        ON sales_message_dispatch_attempts(tenant_id, status, created_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_sales_message_dispatch_attempts_tenant_status_created")
    op.execute("DROP INDEX IF EXISTS ix_sales_message_dispatch_attempts_message")
    op.execute("DROP INDEX IF EXISTS uq_sales_message_dispatch_attempts_tenant_provider_key")
    op.execute("DROP TABLE IF EXISTS sales_message_dispatch_attempts")
    op.execute("DROP INDEX IF EXISTS uq_sales_messages_tenant_delivery_external")
    op.execute("DROP INDEX IF EXISTS ix_sales_messages_tenant_outbound_pending")
    op.execute(
        """
        ALTER TABLE sales_messages
        DROP COLUMN IF EXISTS dispatched_at,
        DROP COLUMN IF EXISTS delivery_external_id,
        DROP COLUMN IF EXISTS delivery_provider
        """
    )
    op.execute("ALTER TABLE sales_messages DROP CONSTRAINT ck_sales_messages_status")
    op.execute(
        """
        ALTER TABLE sales_messages
        ADD CONSTRAINT ck_sales_messages_status
        CHECK (status IN ('pending', 'sent', 'delivered', 'read', 'failed'))
        """
    )
