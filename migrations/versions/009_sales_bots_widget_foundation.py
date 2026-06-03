"""sales bots and widget foundation

Revision ID: 009_sales_bots_widget_foundation
Revises: 008_sales_campaigns_foundation
Create Date: 2026-06-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "009_sales_bots_widget_foundation"
down_revision: str | None = "008_sales_campaigns_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX uq_sales_channels_web_chatbot_widget_id
        ON sales_channels((config->>'widget_id'))
        WHERE channel_type = 'web_chatbot'
          AND config ? 'widget_id'
        """
    )

    op.execute(
        """
        CREATE TABLE sales_bots (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            name VARCHAR(180) NOT NULL,
            description TEXT,
            system_prompt TEXT,
            welcome_message TEXT,
            fallback_message TEXT,
            knowledge_base TEXT,
            faqs JSONB NOT NULL DEFAULT '[]'::jsonb,
            model VARCHAR(80) NOT NULL DEFAULT 'gpt-4o-mini',
            temperature NUMERIC(4,2) NOT NULL DEFAULT 0.30,
            max_tokens INTEGER NOT NULL DEFAULT 800,
            trigger_type VARCHAR(40) NOT NULL DEFAULT 'todas_mensagens',
            trigger_value TEXT,
            channel_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            active BOOLEAN NOT NULL DEFAULT false,
            total_triggers INTEGER NOT NULL DEFAULT 0,
            total_completed INTEGER NOT NULL DEFAULT 0,
            total_transferred INTEGER NOT NULL DEFAULT 0,
            created_by_membership_id UUID REFERENCES memberships(id) ON DELETE SET NULL,
            updated_by_membership_id UUID REFERENCES memberships(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_sales_bots_trigger_type
                CHECK (trigger_type IN ('todas_mensagens', 'primeira_mensagem', 'keyword')),
            CONSTRAINT ck_sales_bots_temperature_range
                CHECK (temperature >= 0 AND temperature <= 2),
            CONSTRAINT ck_sales_bots_max_tokens_positive
                CHECK (max_tokens > 0 AND max_tokens <= 8000),
            CONSTRAINT ck_sales_bots_counts_non_negative
                CHECK (
                    total_triggers >= 0
                    AND total_completed >= 0
                    AND total_transferred >= 0
                ),
            CONSTRAINT ck_sales_bots_faqs_array
                CHECK (jsonb_typeof(faqs) = 'array'),
            CONSTRAINT ck_sales_bots_channel_ids_array
                CHECK (jsonb_typeof(channel_ids) = 'array')
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_bots_tenant_active_created
        ON sales_bots(tenant_id, active, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_bots_tenant_name
        ON sales_bots(tenant_id, name)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_bots_channel_ids_gin
        ON sales_bots USING gin(channel_ids)
        """
    )

    op.execute(
        """
        CREATE TABLE sales_bot_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            bot_id UUID NOT NULL REFERENCES sales_bots(id) ON DELETE CASCADE,
            conversation_id UUID REFERENCES sales_conversations(id) ON DELETE SET NULL,
            input_message_id UUID REFERENCES sales_messages(id) ON DELETE SET NULL,
            output_message_id UUID REFERENCES sales_messages(id) ON DELETE SET NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'pending',
            input_text TEXT,
            output_text TEXT,
            error TEXT,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ,
            CONSTRAINT ck_sales_bot_runs_status
                CHECK (status IN ('pending', 'succeeded', 'failed', 'skipped'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_bot_runs_tenant_bot_created
        ON sales_bot_runs(tenant_id, bot_id, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_bot_runs_conversation
        ON sales_bot_runs(conversation_id)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_bot_runs_input_message
        ON sales_bot_runs(input_message_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_sales_bot_runs_input_message")
    op.execute("DROP INDEX IF EXISTS ix_sales_bot_runs_conversation")
    op.execute("DROP INDEX IF EXISTS ix_sales_bot_runs_tenant_bot_created")
    op.execute("DROP TABLE IF EXISTS sales_bot_runs")
    op.execute("DROP INDEX IF EXISTS ix_sales_bots_channel_ids_gin")
    op.execute("DROP INDEX IF EXISTS ix_sales_bots_tenant_name")
    op.execute("DROP INDEX IF EXISTS ix_sales_bots_tenant_active_created")
    op.execute("DROP TABLE IF EXISTS sales_bots")
    op.execute("DROP INDEX IF EXISTS uq_sales_channels_web_chatbot_widget_id")
