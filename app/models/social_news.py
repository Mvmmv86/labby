import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SocialNewsSegment(Base):
    __tablename__ = "social_news_segments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_social_news_segments_tenant_slug"),
        CheckConstraint(
            "status IN ('active', 'inactive', 'archived')",
            name="ck_social_news_segments_status",
        ),
        CheckConstraint(
            "min_engagement_score >= 0",
            name="ck_social_news_segments_min_engagement_non_negative",
        ),
        Index(
            "ix_social_news_segments_tenant_status_created_at",
            "tenant_id",
            "status",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    base_knowledge: Mapped[str | None] = mapped_column(Text)
    disclaimer: Mapped[str | None] = mapped_column(Text)
    min_engagement_score: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active", server_default="active"
    )
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
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


class SocialNewsSource(Base):
    __tablename__ = "social_news_sources"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "segment_id",
            "provider",
            "source_type",
            "value",
            name="uq_social_news_sources_tenant_segment_source",
        ),
        CheckConstraint("provider IN ('x')", name="ck_social_news_sources_provider"),
        CheckConstraint(
            "source_type IN ('x_handle', 'x_keyword', 'x_query')",
            name="ck_social_news_sources_type",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive', 'archived')",
            name="ck_social_news_sources_status",
        ),
        CheckConstraint("min_likes >= 0", name="ck_social_news_sources_min_likes_non_negative"),
        CheckConstraint("min_reposts >= 0", name="ck_social_news_sources_min_reposts_non_negative"),
        CheckConstraint("min_replies >= 0", name="ck_social_news_sources_min_replies_non_negative"),
        CheckConstraint(
            "min_impressions >= 0",
            name="ck_social_news_sources_min_impressions_non_negative",
        ),
        Index("ix_social_news_sources_tenant_segment_status", "tenant_id", "segment_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("social_news_segments.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="x",
        server_default="x",
    )
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    min_likes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    min_reposts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    min_replies: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    min_impressions: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active", server_default="active"
    )
    metadata_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SocialNewsCurator(Base):
    __tablename__ = "social_news_curators"
    __table_args__ = (
        UniqueConstraint("tenant_id", "segment_id", name="uq_social_news_curators_tenant_segment"),
        CheckConstraint(
            "status IN ('active', 'inactive', 'archived')",
            name="ck_social_news_curators_status",
        ),
        CheckConstraint("temperature >= 0", name="ck_social_news_curators_temperature_min"),
        CheckConstraint("temperature <= 2", name="ck_social_news_curators_temperature_max"),
        CheckConstraint("max_tokens > 0", name="ck_social_news_curators_max_tokens_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("social_news_segments.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    model: Mapped[str] = mapped_column(
        String(80), nullable=False, default="gpt-4o-mini", server_default="gpt-4o-mini"
    )
    temperature: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, server_default="0.30"
    )
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="600")
    system_prompt: Mapped[str | None] = mapped_column(Text)
    base_knowledge: Mapped[str | None] = mapped_column(Text)
    vocabulary: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    event_types: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active", server_default="active"
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


class SocialNewsRun(Base):
    __tablename__ = "social_news_runs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "run_type",
            "idempotency_key",
            name="uq_social_news_runs_tenant_type_idempotency",
        ),
        CheckConstraint(
            "run_type IN ('manual', 'scheduled', 'calibration')",
            name="ck_social_news_runs_type",
        ),
        CheckConstraint(
            "status IN ('queued', 'capturing', 'curation_stage1', 'rewriting', "
            "'curation_stage2', 'sending', 'succeeded', 'failed', 'cancelled')",
            name="ck_social_news_runs_status",
        ),
        CheckConstraint("candidates_count >= 0", name="ck_social_news_runs_candidates_count"),
        CheckConstraint("ranked_count >= 0", name="ck_social_news_runs_ranked_count"),
        CheckConstraint("approved_stage1_count >= 0", name="ck_social_news_runs_approved_s1"),
        CheckConstraint("approved_stage2_count >= 0", name="ck_social_news_runs_approved_s2"),
        CheckConstraint("sent_count >= 0", name="ck_social_news_runs_sent_count"),
        CheckConstraint("failed_count >= 0", name="ck_social_news_runs_failed_count"),
        Index("ix_social_news_runs_tenant_status_created_at", "tenant_id", "status", "created_at"),
        Index(
            "ix_social_news_runs_tenant_segment_created_at",
            "tenant_id",
            "segment_id",
            "created_at",
        ),
        Index("ix_social_news_runs_job_id", "job_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL")
    )
    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("social_news_segments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL")
    )
    run_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="manual", server_default="manual"
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="queued", server_default="queued"
    )
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False)
    window_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    candidates_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    ranked_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    approved_stage1_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    approved_stage2_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    x_api_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, server_default="0"
    )
    ai_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, server_default="0"
    )
    email_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, server_default="0"
    )
    estimated_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, server_default="0"
    )
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SocialNewsItem(Base):
    __tablename__ = "social_news_items"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "provider",
            "external_id",
            name="uq_social_news_items_tenant_provider_external",
        ),
        CheckConstraint("provider IN ('x')", name="ck_social_news_items_provider"),
        CheckConstraint(
            "status IN ('captured', 'ranked', 'discarded_rank', 'approved_stage1', "
            "'rejected_stage1', 'rewritten', 'approved_stage2', 'rejected_stage2', 'sent')",
            name="ck_social_news_items_status",
        ),
        Index("ix_social_news_items_tenant_run_status", "tenant_id", "run_id", "status"),
        Index("ix_social_news_items_tenant_segment_status", "tenant_id", "segment_id", "status"),
        Index("ix_social_news_items_tenant_created_at", "tenant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("social_news_runs.id", ondelete="CASCADE"), nullable=False
    )
    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("social_news_segments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("social_news_sources.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="x",
        server_default="x",
    )
    external_id: Mapped[str] = mapped_column(String(180), nullable=False)
    external_url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    author_handle: Mapped[str | None] = mapped_column(String(180))
    author_name: Mapped[str | None] = mapped_column(String(240))
    author_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    original_content: Mapped[str] = mapped_column(Text, nullable=False)
    rewritten_content: Mapped[str | None] = mapped_column(Text)
    rewritten_model: Mapped[str | None] = mapped_column(String(80))
    rewritten_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    media_urls: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    ranking_score: Mapped[int | None] = mapped_column(Integer)
    ranking_reason: Mapped[str | None] = mapped_column(Text)
    ranking_source: Mapped[str | None] = mapped_column(String(80))
    type_match: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="captured", server_default="captured"
    )
    approved_stage1_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL")
    )
    approved_stage1_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_stage2_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL")
    )
    approved_stage2_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SocialNewsSubscriber(Base):
    __tablename__ = "social_news_subscribers"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "segment_id",
            "email_normalized",
            name="uq_social_news_subscribers_tenant_segment_email",
        ),
        CheckConstraint(
            "status IN ('active', 'unsubscribed', 'bounced', 'complained', 'removed')",
            name="ck_social_news_subscribers_status",
        ),
        CheckConstraint(
            "consent_status IN ('granted', 'revoked')",
            name="ck_social_news_subscribers_consent_status",
        ),
        Index(
            "ix_social_news_subscribers_tenant_segment_status",
            "tenant_id",
            "segment_id",
            "status",
        ),
        Index(
            "ix_social_news_subscribers_unsubscribe_hash",
            "unsubscribe_token_hash",
            postgresql_where=text("unsubscribe_token_hash IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("social_news_segments.id", ondelete="CASCADE"),
        nullable=False,
    )
    email_normalized: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str | None] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active", server_default="active"
    )
    origin: Mapped[str] = mapped_column(String(80), nullable=False, default="manual")
    consent_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="granted", server_default="granted"
    )
    consent_source: Mapped[str | None] = mapped_column(String(80))
    consent_given_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unsubscribe_token_hash: Mapped[str | None] = mapped_column(String(128))
    metadata_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SocialNewsSubscriberConsentEvent(Base):
    __tablename__ = "social_news_subscriber_consent_events"
    __table_args__ = (
        Index(
            "ix_social_news_consent_events_subscriber_created_at",
            "subscriber_id",
            "created_at",
        ),
        Index(
            "ix_social_news_consent_events_tenant_type_created_at",
            "tenant_id",
            "event_type",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    subscriber_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("social_news_subscribers.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    consent_source: Mapped[str | None] = mapped_column(String(80))
    ip: Mapped[str | None] = mapped_column(String(80))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    metadata_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SocialNewsDispatch(Base):
    __tablename__ = "social_news_dispatches"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_social_news_dispatches_tenant_idempotency",
        ),
        UniqueConstraint(
            "run_id",
            "subscriber_id",
            name="uq_social_news_dispatches_run_subscriber",
        ),
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'skipped')",
            name="ck_social_news_dispatches_status",
        ),
        Index("ix_social_news_dispatches_tenant_run_status", "tenant_id", "run_id", "status"),
        Index(
            "ix_social_news_dispatches_tenant_subscriber_created_at",
            "tenant_id",
            "subscriber_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("social_news_runs.id", ondelete="CASCADE"), nullable=False
    )
    subscriber_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("social_news_subscribers.id", ondelete="CASCADE"),
        nullable=False,
    )
    email_normalized: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending", server_default="pending"
    )
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(80), nullable=False, default="resend", server_default="resend"
    )
    provider_message_id: Mapped[str | None] = mapped_column(String(180))
    error_message: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
