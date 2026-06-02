import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func, text

from app.models.base import Base


class SalesContact(Base):
    __tablename__ = "sales_contacts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'archived', 'blocked')",
            name="ck_sales_contacts_status",
        ),
        CheckConstraint(
            "total_messages_sent >= 0",
            name="ck_sales_contacts_total_messages_sent_non_negative",
        ),
        CheckConstraint(
            "total_messages_received >= 0",
            name="ck_sales_contacts_total_messages_received_non_negative",
        ),
        Index("ix_sales_contacts_tenant_status_created_at", "tenant_id", "status", "created_at"),
        Index("ix_sales_contacts_tenant_group_name", "tenant_id", "group_name"),
        Index("ix_sales_contacts_tenant_last_interaction", "tenant_id", "last_interaction_at"),
        Index("ix_sales_contacts_tags_gin", "tags", postgresql_using="gin"),
        Index(
            "uq_sales_contacts_tenant_phone_normalized",
            "tenant_id",
            "phone_normalized",
            unique=True,
            postgresql_where=text("phone_normalized IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40))
    phone_normalized: Mapped[str | None] = mapped_column(String(40))
    email_normalized: Mapped[str | None] = mapped_column(String(320))
    group_name: Mapped[str | None] = mapped_column(String(120))
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    notes: Mapped[str | None] = mapped_column(Text)
    custom_fields: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active", server_default="active"
    )
    optout: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    total_messages_sent: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total_messages_received: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    last_interaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL")
    )
    updated_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SalesChannel(Base):
    __tablename__ = "sales_channels"
    __table_args__ = (
        CheckConstraint(
            "channel_type IN ("
            "'whatsapp_evolution', 'whatsapp_cloud', 'telegram', 'discord', 'web_chatbot'"
            ")",
            name="ck_sales_channels_channel_type",
        ),
        CheckConstraint(
            "status IN ('desconectado', 'conectando', 'conectado', 'erro')",
            name="ck_sales_channels_status",
        ),
        Index("ix_sales_channels_tenant_status", "tenant_id", "status"),
        Index("ix_sales_channels_tenant_type", "tenant_id", "channel_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    channel_type: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="desconectado", server_default="desconectado"
    )
    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    webhook_secret: Mapped[str | None] = mapped_column(String(128))
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SalesContactChannel(Base):
    __tablename__ = "sales_contact_channels"
    __table_args__ = (
        CheckConstraint(
            "channel_type IN ("
            "'whatsapp_evolution', 'whatsapp_cloud', 'telegram', 'discord', 'web_chatbot'"
            ")",
            name="ck_sales_contact_channels_channel_type",
        ),
        Index(
            "uq_sales_contact_channels_tenant_type_identifier",
            "tenant_id",
            "channel_type",
            "identifier",
            unique=True,
        ),
        Index("ix_sales_contact_channels_contact", "contact_id"),
        Index("ix_sales_contact_channels_channel", "channel_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_contacts.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_channels.id", ondelete="SET NULL")
    )
    channel_type: Mapped[str] = mapped_column(String(30), nullable=False)
    identifier: Mapped[str] = mapped_column(String(160), nullable=False)
    channel_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SalesConversation(Base):
    __tablename__ = "sales_conversations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('aberta', 'fechada', 'pendente')",
            name="ck_sales_conversations_status",
        ),
        Index(
            "ix_sales_conversations_tenant_status_last_message",
            "tenant_id",
            "status",
            "last_message_at",
        ),
        Index("ix_sales_conversations_tenant_contact", "tenant_id", "contact_id"),
        Index("ix_sales_conversations_tenant_assigned", "tenant_id", "assigned_to_membership_id"),
        Index("ix_sales_conversations_tenant_waiting", "tenant_id", "waiting_for_human"),
        Index("ix_sales_conversations_channel", "channel_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_contacts.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_channels.id", ondelete="SET NULL")
    )
    assigned_to_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="aberta", server_default="aberta"
    )
    subject: Mapped[str | None] = mapped_column(String(255))
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    bot_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    bot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    waiting_for_human: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL")
    )
    updated_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SalesMessage(Base):
    __tablename__ = "sales_messages"
    __table_args__ = (
        CheckConstraint(
            "direction IN ('entrada', 'saida')",
            name="ck_sales_messages_direction",
        ),
        CheckConstraint(
            "sender_type IN ('contato', 'usuario', 'bot', 'sistema')",
            name="ck_sales_messages_sender_type",
        ),
        CheckConstraint(
            "message_type IN ('text', 'image', 'video', 'document')",
            name="ck_sales_messages_message_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'sent', 'delivered', 'read', 'failed')",
            name="ck_sales_messages_status",
        ),
        Index("ix_sales_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_sales_messages_tenant_created", "tenant_id", "created_at"),
        Index(
            "uq_sales_messages_tenant_provider_external",
            "tenant_id",
            "provider",
            "external_id",
            unique=True,
            postgresql_where=text("provider IS NOT NULL AND external_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sales_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_contacts.id", ondelete="SET NULL")
    )
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    sender_type: Mapped[str] = mapped_column(String(20), nullable=False)
    sender_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL")
    )
    message_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="text", server_default="text"
    )
    content: Mapped[str | None] = mapped_column(Text)
    media_url: Mapped[str | None] = mapped_column(String(500))
    media_caption: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(40))
    external_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    error: Mapped[str | None] = mapped_column(Text)
    message_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SalesCampaign(Base):
    __tablename__ = "sales_campaigns"
    __table_args__ = (
        CheckConstraint(
            "message_type IN ('text', 'image', 'video', 'document')",
            name="ck_sales_campaigns_message_type",
        ),
        CheckConstraint(
            "status IN ("
            "'draft', 'ativa', 'scheduled', 'sending', 'queued', "
            "'sent', 'paused', 'cancelled', 'failed'"
            ")",
            name="ck_sales_campaigns_status",
        ),
        CheckConstraint(
            "total_recipients >= 0 "
            "AND queued_count >= 0 "
            "AND sent_count >= 0 "
            "AND failed_count >= 0 "
            "AND skipped_count >= 0",
            name="ck_sales_campaigns_counts_non_negative",
        ),
        Index(
            "uq_sales_campaigns_tenant_idempotency",
            "tenant_id",
            "idempotency_key",
            unique=True,
        ),
        Index(
            "ix_sales_campaigns_tenant_status_created",
            "tenant_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_sales_campaigns_tenant_scheduled",
            "tenant_id",
            "scheduled_at",
            postgresql_where=text("scheduled_at IS NOT NULL"),
        ),
        Index("ix_sales_campaigns_channel", "channel_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_channels.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    message_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="text", server_default="text"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="draft", server_default="draft"
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_recipients: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    queued_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL")
    )
    updated_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SalesCampaignRecipient(Base):
    __tablename__ = "sales_campaign_recipients"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'queued', 'sent', 'failed', 'skipped')",
            name="ck_sales_campaign_recipients_status",
        ),
        Index(
            "uq_sales_campaign_recipients_campaign_contact",
            "tenant_id",
            "campaign_id",
            "contact_id",
            unique=True,
            postgresql_where=text("contact_id IS NOT NULL"),
        ),
        Index(
            "ix_sales_campaign_recipients_campaign_status",
            "tenant_id",
            "campaign_id",
            "status",
        ),
        Index("ix_sales_campaign_recipients_contact", "contact_id"),
        Index("ix_sales_campaign_recipients_message", "message_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_campaigns.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_contacts.id", ondelete="SET NULL")
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_conversations.id", ondelete="SET NULL")
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_messages.id", ondelete="SET NULL")
    )
    recipient_name: Mapped[str | None] = mapped_column(String(180))
    phone_normalized: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending", server_default="pending"
    )
    error: Mapped[str | None] = mapped_column(Text)
    recipient_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
