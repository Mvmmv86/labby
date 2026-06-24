import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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


class SocialOnboardingSession(Base):
    __tablename__ = "social_onboarding_sessions"
    __table_args__ = (
        CheckConstraint(
            "objective IS NULL OR objective IN ("
            "'grow_audience', 'sell_more', 'authority', 'content_ops', 'benchmarking'"
            ")",
            name="ck_social_onboarding_sessions_objective",
        ),
        CheckConstraint(
            "status IN ('draft', 'connecting', 'analyzing', 'ready', 'failed', 'archived')",
            name="ck_social_onboarding_sessions_status",
        ),
        CheckConstraint(
            "primary_provider IS NULL OR primary_provider IN "
            "('instagram', 'youtube', 'x', 'linkedin', 'fake')",
            name="ck_social_onboarding_sessions_provider",
        ),
        CheckConstraint(
            "connection_mode IN ('none', 'simulated', 'oauth')",
            name="ck_social_onboarding_sessions_connection_mode",
        ),
        Index(
            "ix_social_onboarding_sessions_tenant_status_created",
            "tenant_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_social_onboarding_sessions_tenant_provider_account",
            "tenant_id",
            "primary_provider",
            "connected_account_id",
        ),
        Index(
            "uq_social_onboarding_sessions_one_active_per_tenant",
            "tenant_id",
            unique=True,
            postgresql_where=text("status <> 'archived'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL")
    )
    updated_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL")
    )
    objective: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    primary_provider: Mapped[str | None] = mapped_column(String(40))
    connection_mode: Mapped[str] = mapped_column(String(30), nullable=False, default="none")
    connected_account_id: Mapped[str | None] = mapped_column(String(180))
    connected_account_handle: Mapped[str | None] = mapped_column(String(180))
    connected_account_name: Mapped[str | None] = mapped_column(String(180))
    profile_url: Mapped[str | None] = mapped_column(Text)
    progress_steps: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    profile_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    analysis_report: Mapped[dict | None] = mapped_column(JSONB)
    analysis_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    analysis_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    analysis_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SocialReferenceProfile(Base):
    __tablename__ = "social_reference_profiles"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('instagram', 'youtube', 'x', 'linkedin', 'fake')",
            name="ck_social_reference_profiles_provider",
        ),
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_social_reference_profiles_status",
        ),
        CheckConstraint(
            "sync_status IN ("
            "'manual_pending', 'pending', 'syncing', 'partially_synced', "
            "'synced', 'unavailable', 'failed'"
            ")",
            name="ck_social_reference_profiles_sync_status",
        ),
        Index(
            "ix_social_reference_profiles_tenant_session_status",
            "tenant_id",
            "onboarding_session_id",
            "status",
        ),
        Index("ix_social_reference_profiles_public_ref", "public_reference_profile_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    onboarding_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("social_onboarding_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    public_reference_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("social_public_reference_profiles.id", ondelete="SET NULL"),
    )
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    handle: Mapped[str] = mapped_column(String(180), nullable=False)
    label: Mapped[str | None] = mapped_column(String(180))
    profile_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    sync_status: Mapped[str] = mapped_column(String(40), nullable=False, default="manual_pending")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    comparison_summary: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SocialPublicReferenceProfile(Base):
    __tablename__ = "social_public_reference_profiles"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('instagram', 'youtube', 'x', 'linkedin', 'fake')",
            name="ck_social_public_refs_provider",
        ),
        CheckConstraint(
            "source IN ('manual', 'phyllo', 'apify', 'meta_business_discovery', 'unknown')",
            name="ck_social_public_refs_source",
        ),
        CheckConstraint(
            "sync_status IN ("
            "'manual_pending', 'pending', 'syncing', 'partially_synced', "
            "'synced', 'unavailable', 'failed'"
            ")",
            name="ck_social_public_refs_sync_status",
        ),
        UniqueConstraint("provider", "handle", name="uq_social_public_refs_provider_handle"),
        Index("ix_social_public_refs_sync", "provider", "sync_status", "updated_at"),
        Index("ix_social_public_refs_next_sync", "next_sync_after", "sync_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    handle: Mapped[str] = mapped_column(String(180), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(180))
    profile_url: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(60), nullable=False, default="manual")
    sync_status: Mapped[str] = mapped_column(String(40), nullable=False, default="manual_pending")
    sync_generation: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    failure_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    profile_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    raw_payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    data_truth: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_sync_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SocialPublicReferenceContent(Base):
    __tablename__ = "social_public_reference_contents"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('instagram', 'youtube', 'x', 'linkedin', 'fake')",
            name="ck_social_public_ref_contents_provider",
        ),
        UniqueConstraint(
            "reference_profile_id",
            "external_id",
            name="uq_social_public_ref_contents_profile_external",
        ),
        Index(
            "ix_social_public_ref_contents_profile_published",
            "reference_profile_id",
            "published_at",
        ),
        Index(
            "ix_social_public_ref_contents_profile_score",
            "reference_profile_id",
            "performance_score",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reference_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("social_public_reference_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    external_id: Mapped[str] = mapped_column(String(220), nullable=False)
    content_type: Mapped[str] = mapped_column(String(60), nullable=False)
    content_format: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    content_url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metrics_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    raw_payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    data_truth: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    engagement_rate_by_followers: Mapped[float | None] = mapped_column(Numeric(10, 2))
    engagement_rate_by_reach: Mapped[float | None] = mapped_column(Numeric(10, 2))
    performance_score: Mapped[float | None] = mapped_column(Numeric(12, 2))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SocialPhylloUser(Base):
    __tablename__ = "social_phyllo_users"
    __table_args__ = (
        CheckConstraint(
            "environment IN ('sandbox', 'staging', 'production')",
            name="ck_social_phyllo_users_environment",
        ),
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_social_phyllo_users_status",
        ),
        Index("ix_social_phyllo_users_tenant_status", "tenant_id", "status"),
        Index(
            "uq_social_phyllo_users_tenant_environment",
            "tenant_id",
            "environment",
            unique=True,
        ),
        Index(
            "uq_social_phyllo_users_environment_user",
            "environment",
            "phyllo_user_id",
            unique=True,
        ),
        Index(
            "uq_social_phyllo_users_environment_external",
            "environment",
            "external_id",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL")
    )
    environment: Mapped[str] = mapped_column(String(30), nullable=False)
    phyllo_user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    external_id: Mapped[str] = mapped_column(String(220), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    metadata_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SocialPhylloAccount(Base):
    __tablename__ = "social_phyllo_accounts"
    __table_args__ = (
        CheckConstraint(
            "environment IN ('sandbox', 'staging', 'production')",
            name="ck_social_phyllo_accounts_environment",
        ),
        CheckConstraint(
            "provider IN ('instagram', 'youtube', 'x', 'linkedin', 'fake')",
            name="ck_social_phyllo_accounts_provider",
        ),
        Index(
            "ix_social_phyllo_accounts_tenant_provider_status",
            "tenant_id",
            "provider",
            "account_status",
        ),
        Index(
            "ix_social_phyllo_accounts_environment_user",
            "environment",
            "phyllo_user_id",
        ),
        Index(
            "uq_social_phyllo_accounts_tenant_environment_account",
            "tenant_id",
            "environment",
            "phyllo_account_id",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    onboarding_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("social_onboarding_sessions.id", ondelete="SET NULL")
    )
    environment: Mapped[str] = mapped_column(String(30), nullable=False)
    phyllo_user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    phyllo_account_id: Mapped[str] = mapped_column(String(120), nullable=False)
    phyllo_profile_id: Mapped[str | None] = mapped_column(String(120))
    work_platform_id: Mapped[str | None] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    handle: Mapped[str | None] = mapped_column(String(180))
    display_name: Mapped[str | None] = mapped_column(String(180))
    profile_url: Mapped[str | None] = mapped_column(Text)
    account_status: Mapped[str | None] = mapped_column(String(60))
    raw_account: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    raw_profile: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SocialConnectedContent(Base):
    __tablename__ = "social_connected_contents"
    __table_args__ = (
        CheckConstraint(
            "environment IN ('sandbox', 'staging', 'production')",
            name="ck_social_connected_contents_environment",
        ),
        CheckConstraint(
            "provider IN ('instagram', 'youtube', 'x', 'linkedin', 'fake')",
            name="ck_social_connected_contents_provider",
        ),
        UniqueConstraint(
            "tenant_id",
            "environment",
            "provider",
            "external_id",
            name="uq_social_connected_contents_tenant_env_provider_external",
        ),
        Index(
            "ix_social_connected_contents_tenant_account_published",
            "tenant_id",
            "environment",
            "phyllo_account_id",
            "published_at",
        ),
        Index(
            "ix_social_connected_contents_tenant_session_score",
            "tenant_id",
            "environment",
            "onboarding_session_id",
            "performance_score",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    onboarding_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("social_onboarding_sessions.id", ondelete="SET NULL")
    )
    environment: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    phyllo_account_id: Mapped[str] = mapped_column(String(120), nullable=False)
    external_id: Mapped[str] = mapped_column(String(220), nullable=False)
    phyllo_content_id: Mapped[str | None] = mapped_column(String(120))
    content_type: Mapped[str] = mapped_column(String(60), nullable=False)
    content_format: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    content_url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metrics_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    raw_payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    data_truth: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    engagement_rate_by_followers: Mapped[float | None] = mapped_column(Numeric(10, 2))
    engagement_rate_by_reach: Mapped[float | None] = mapped_column(Numeric(10, 2))
    performance_score: Mapped[float | None] = mapped_column(Numeric(12, 2))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SocialActionPlan(Base):
    __tablename__ = "social_action_plans"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_social_action_plans_status",
        ),
        Index(
            "ix_social_action_plans_tenant_session_status",
            "tenant_id",
            "onboarding_session_id",
            "status",
        ),
        Index(
            "uq_social_action_plans_active_session",
            "tenant_id",
            "onboarding_session_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    onboarding_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("social_onboarding_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL")
    )
    updated_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    source_analysis_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_specialist_version: Mapped[str] = mapped_column(String(80), nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    metadata_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SocialActionPlanItem(Base):
    __tablename__ = "social_action_plan_items"
    __table_args__ = (
        CheckConstraint(
            "priority IN ('low', 'medium', 'high')",
            name="ck_social_action_plan_items_priority",
        ),
        CheckConstraint(
            "status IN ("
            "'pending', 'in_progress', 'approved', 'sent_to_calendar', 'done', 'archived'"
            ")",
            name="ck_social_action_plan_items_status",
        ),
        UniqueConstraint(
            "action_plan_id",
            "position",
            name="uq_social_action_plan_items_plan_position",
        ),
        Index(
            "ix_social_action_plan_items_tenant_plan_position",
            "tenant_id",
            "action_plan_id",
            "position",
        ),
        Index(
            "ix_social_action_plan_items_tenant_status",
            "tenant_id",
            "status",
            "updated_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    action_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("social_action_plans.id", ondelete="CASCADE"), nullable=False
    )
    onboarding_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("social_onboarding_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    why_it_matters: Mapped[str | None] = mapped_column(Text)
    how_to_execute: Mapped[str | None] = mapped_column(Text)
    expected_signal: Mapped[str | None] = mapped_column(Text)
    measurement: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    source_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SocialContentCalendarEntry(Base):
    __tablename__ = "social_content_calendar_entries"
    __table_args__ = (
        CheckConstraint(
            "channel IN ('instagram', 'youtube', 'x', 'linkedin', 'multi')",
            name="ck_social_content_calendar_entries_channel",
        ),
        CheckConstraint(
            "status IN ('draft', 'planned', 'approved', 'scheduled', 'published', 'archived')",
            name="ck_social_content_calendar_entries_status",
        ),
        Index(
            "ix_social_content_calendar_tenant_plan_day",
            "tenant_id",
            "action_plan_id",
            "day_index",
        ),
        Index(
            "ix_social_content_calendar_tenant_scheduled",
            "tenant_id",
            "scheduled_at",
            "status",
        ),
        Index("ix_social_content_calendar_action_item", "action_item_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    action_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("social_action_plans.id", ondelete="CASCADE"), nullable=False
    )
    action_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("social_action_plan_items.id", ondelete="SET NULL")
    )
    onboarding_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("social_onboarding_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    day_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(String(40), nullable=False)
    channel: Mapped[str] = mapped_column(String(40), nullable=False, default="instagram")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    theme: Mapped[str | None] = mapped_column(Text)
    hook: Mapped[str | None] = mapped_column(Text)
    caption_outline: Mapped[str | None] = mapped_column(Text)
    cta: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[str | None] = mapped_column(Text)
    objective: Mapped[str | None] = mapped_column(Text)
    source_reference_handle: Mapped[str | None] = mapped_column(String(180))
    metrics_goal_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    metadata_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SocialContentDraft(Base):
    __tablename__ = "social_content_drafts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'in_review', 'approved', 'archived')",
            name="ck_social_content_drafts_status",
        ),
        CheckConstraint(
            "draft_version > 0",
            name="ck_social_content_drafts_version_positive",
        ),
        CheckConstraint(
            "production_status IN ('not_started', 'queued', 'running', 'ready', 'failed')",
            name="ck_social_content_drafts_production_status",
        ),
        CheckConstraint(
            "production_version >= 0",
            name="ck_social_content_drafts_production_version_nonnegative",
        ),
        UniqueConstraint(
            "tenant_id",
            "calendar_entry_id",
            "draft_version",
            name="uq_social_content_drafts_entry_version",
        ),
        Index(
            "uq_social_content_drafts_current_entry",
            "tenant_id",
            "calendar_entry_id",
            unique=True,
            postgresql_where=text("is_current = true"),
        ),
        Index(
            "ix_social_content_drafts_tenant_entry_current",
            "tenant_id",
            "calendar_entry_id",
            "is_current",
        ),
        Index(
            "ix_social_content_drafts_tenant_status_updated",
            "tenant_id",
            "status",
            "updated_at",
        ),
        Index(
            "ix_social_content_drafts_tenant_production_status",
            "tenant_id",
            "production_status",
            "updated_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    calendar_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("social_content_calendar_entries.id", ondelete="CASCADE"),
        nullable=False,
    )
    action_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("social_action_plans.id", ondelete="CASCADE"), nullable=False
    )
    onboarding_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("social_onboarding_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL")
    )
    updated_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL")
    )
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    format: Mapped[str] = mapped_column(String(40), nullable=False)
    channel: Mapped[str] = mapped_column(String(40), nullable=False, default="instagram")
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    angle: Mapped[str | None] = mapped_column(Text)
    hook: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text)
    cta: Mapped[str | None] = mapped_column(Text)
    visual_direction: Mapped[str | None] = mapped_column(Text)
    script_json: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    production_checklist_json: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    evidence_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    metadata_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    production_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="not_started"
    )
    production_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    production_payload_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    production_error_code: Mapped[str | None] = mapped_column(String(120))
    production_error_message: Mapped[str | None] = mapped_column(Text)
    production_provider: Mapped[str | None] = mapped_column(String(80))
    production_model: Mapped[str | None] = mapped_column(String(120))
    production_input_tokens: Mapped[int | None] = mapped_column(Integer)
    production_output_tokens: Mapped[int | None] = mapped_column(Integer)
    production_cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    production_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    production_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
