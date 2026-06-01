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
