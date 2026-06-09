import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
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
        Index(
            "ix_social_reference_profiles_tenant_session_status",
            "tenant_id",
            "onboarding_session_id",
            "status",
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
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    handle: Mapped[str] = mapped_column(String(180), nullable=False)
    label: Mapped[str | None] = mapped_column(String(180))
    profile_url: Mapped[str | None] = mapped_column(Text)
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
