"""sales inbox foundation

Revision ID: 007_sales_inbox_foundation
Revises: 006_sales_contacts_foundation
Create Date: 2026-06-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "007_sales_inbox_foundation"
down_revision: str | None = "006_sales_contacts_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE sales_channels (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            channel_type VARCHAR(30) NOT NULL,
            name VARCHAR(120) NOT NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'desconectado',
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            webhook_secret VARCHAR(128),
            last_event_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_sales_channels_channel_type
                CHECK (
                    channel_type IN (
                        'whatsapp_evolution', 'whatsapp_cloud', 'telegram',
                        'discord', 'web_chatbot'
                    )
                ),
            CONSTRAINT ck_sales_channels_status
                CHECK (status IN ('desconectado', 'conectando', 'conectado', 'erro'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_channels_tenant_status
        ON sales_channels(tenant_id, status)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_channels_tenant_type
        ON sales_channels(tenant_id, channel_type)
        """
    )

    op.execute(
        """
        CREATE TABLE sales_contact_channels (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            contact_id UUID NOT NULL REFERENCES sales_contacts(id) ON DELETE CASCADE,
            channel_id UUID REFERENCES sales_channels(id) ON DELETE SET NULL,
            channel_type VARCHAR(30) NOT NULL,
            identifier VARCHAR(160) NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_sales_contact_channels_channel_type
                CHECK (
                    channel_type IN (
                        'whatsapp_evolution', 'whatsapp_cloud', 'telegram',
                        'discord', 'web_chatbot'
                    )
                )
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_sales_contact_channels_tenant_type_identifier
        ON sales_contact_channels(tenant_id, channel_type, identifier)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_contact_channels_contact
        ON sales_contact_channels(contact_id)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_contact_channels_channel
        ON sales_contact_channels(channel_id)
        """
    )

    op.execute(
        """
        CREATE TABLE sales_conversations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            contact_id UUID NOT NULL REFERENCES sales_contacts(id) ON DELETE CASCADE,
            channel_id UUID REFERENCES sales_channels(id) ON DELETE SET NULL,
            assigned_to_membership_id UUID REFERENCES memberships(id) ON DELETE SET NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'aberta',
            subject VARCHAR(255),
            tags JSONB NOT NULL DEFAULT '[]'::jsonb,
            bot_active BOOLEAN NOT NULL DEFAULT false,
            bot_id UUID,
            waiting_for_human BOOLEAN NOT NULL DEFAULT false,
            last_message_at TIMESTAMPTZ,
            closed_at TIMESTAMPTZ,
            created_by_membership_id UUID REFERENCES memberships(id) ON DELETE SET NULL,
            updated_by_membership_id UUID REFERENCES memberships(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_sales_conversations_status
                CHECK (status IN ('aberta', 'fechada', 'pendente'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_conversations_tenant_status_last_message
        ON sales_conversations(tenant_id, status, last_message_at)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_conversations_tenant_contact
        ON sales_conversations(tenant_id, contact_id)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_conversations_tenant_assigned
        ON sales_conversations(tenant_id, assigned_to_membership_id)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_conversations_tenant_waiting
        ON sales_conversations(tenant_id, waiting_for_human)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_conversations_channel
        ON sales_conversations(channel_id)
        """
    )

    op.execute(
        """
        CREATE TABLE sales_messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            conversation_id UUID NOT NULL REFERENCES sales_conversations(id) ON DELETE CASCADE,
            contact_id UUID REFERENCES sales_contacts(id) ON DELETE SET NULL,
            direction VARCHAR(20) NOT NULL,
            sender_type VARCHAR(20) NOT NULL,
            sender_membership_id UUID REFERENCES memberships(id) ON DELETE SET NULL,
            message_type VARCHAR(20) NOT NULL DEFAULT 'text',
            content TEXT,
            media_url VARCHAR(500),
            media_caption TEXT,
            provider VARCHAR(40),
            external_id VARCHAR(255),
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            error TEXT,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_sales_messages_direction
                CHECK (direction IN ('entrada', 'saida')),
            CONSTRAINT ck_sales_messages_sender_type
                CHECK (sender_type IN ('contato', 'usuario', 'bot', 'sistema')),
            CONSTRAINT ck_sales_messages_message_type
                CHECK (message_type IN ('text', 'image', 'video', 'document')),
            CONSTRAINT ck_sales_messages_status
                CHECK (status IN ('pending', 'sent', 'delivered', 'read', 'failed'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_messages_conversation_created
        ON sales_messages(conversation_id, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sales_messages_tenant_created
        ON sales_messages(tenant_id, created_at)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_sales_messages_tenant_provider_external
        ON sales_messages(tenant_id, provider, external_id)
        WHERE provider IS NOT NULL AND external_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_sales_messages_tenant_provider_external")
    op.execute("DROP INDEX IF EXISTS ix_sales_messages_tenant_created")
    op.execute("DROP INDEX IF EXISTS ix_sales_messages_conversation_created")
    op.execute("DROP TABLE IF EXISTS sales_messages")
    op.execute("DROP INDEX IF EXISTS ix_sales_conversations_channel")
    op.execute("DROP INDEX IF EXISTS ix_sales_conversations_tenant_waiting")
    op.execute("DROP INDEX IF EXISTS ix_sales_conversations_tenant_assigned")
    op.execute("DROP INDEX IF EXISTS ix_sales_conversations_tenant_contact")
    op.execute("DROP INDEX IF EXISTS ix_sales_conversations_tenant_status_last_message")
    op.execute("DROP TABLE IF EXISTS sales_conversations")
    op.execute("DROP INDEX IF EXISTS ix_sales_contact_channels_channel")
    op.execute("DROP INDEX IF EXISTS ix_sales_contact_channels_contact")
    op.execute("DROP INDEX IF EXISTS uq_sales_contact_channels_tenant_type_identifier")
    op.execute("DROP TABLE IF EXISTS sales_contact_channels")
    op.execute("DROP INDEX IF EXISTS ix_sales_channels_tenant_type")
    op.execute("DROP INDEX IF EXISTS ix_sales_channels_tenant_status")
    op.execute("DROP TABLE IF EXISTS sales_channels")
