from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

SocialOnboardingObjective = Literal[
    "grow_audience",
    "sell_more",
    "authority",
    "content_ops",
    "benchmarking",
]
SocialProvider = Literal["instagram", "youtube", "x", "linkedin", "fake"]
SocialOnboardingStatus = Literal["draft", "connecting", "analyzing", "ready", "failed", "archived"]
SocialActionItemStatus = Literal[
    "pending",
    "in_progress",
    "approved",
    "sent_to_calendar",
    "done",
    "archived",
]
SocialCalendarEntryStatus = Literal[
    "draft",
    "planned",
    "approved",
    "scheduled",
    "published",
    "archived",
]


class SocialOnboardingSessionCreate(BaseModel):
    objective: SocialOnboardingObjective


class SocialOnboardingSessionPatch(BaseModel):
    objective: SocialOnboardingObjective | None = None


class SocialOnboardingFakeConnectRequest(BaseModel):
    provider: SocialProvider = "fake"
    handle: str = Field(min_length=1, max_length=180)
    display_name: str | None = Field(default=None, max_length=180)
    profile_url: str | None = Field(default=None, max_length=1000)
    followers_count: int | None = Field(default=None, ge=0)
    posts_count: int | None = Field(default=None, ge=0)
    average_engagement_rate: float | None = Field(default=None, ge=0)


class SocialReferenceProfileCreate(BaseModel):
    provider: SocialProvider
    handle: str = Field(min_length=1, max_length=180)
    label: str | None = Field(default=None, max_length=180)
    profile_url: str | None = Field(default=None, max_length=1000)


class SocialActionPlanItemPatch(BaseModel):
    status: SocialActionItemStatus | None = None
    notes: str | None = Field(default=None, max_length=1000)


class SocialCalendarEntryPatch(BaseModel):
    status: SocialCalendarEntryStatus | None = None
    scheduled_at: datetime | None = None
    title: str | None = Field(default=None, min_length=1, max_length=220)
    format: str | None = Field(default=None, min_length=1, max_length=60)
    channel: str | None = Field(default=None, min_length=1, max_length=60)
    theme: str | None = Field(default=None, max_length=180)
    hook: str | None = Field(default=None, max_length=1000)
    caption_outline: str | None = Field(default=None, max_length=2000)
    cta: str | None = Field(default=None, max_length=1000)
    evidence: str | None = Field(default=None, max_length=1000)
    objective: str | None = Field(default=None, max_length=1000)
    source_reference_handle: str | None = Field(default=None, max_length=180)


class SocialOnboardingPhylloCompleteRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=180)
    account_id: str = Field(min_length=1, max_length=180)
    work_platform_id: str | None = Field(default=None, max_length=180)


class SocialReferenceProfileResponse(BaseModel):
    id: UUID
    public_reference_profile_id: UUID | None = None
    provider: str
    handle: str
    label: str | None = None
    profile_url: str | None = None
    status: str
    sync_status: str = "manual_pending"
    global_sync_status: str | None = None
    public_contents_count: int = 0
    last_synced_at: datetime | None = None
    global_last_synced_at: datetime | None = None
    data_truth: dict[str, Any] | None = None
    comparison_summary: dict[str, Any] | None = None
    created_at: datetime


class SocialActionPlanItemResponse(BaseModel):
    id: UUID
    position: int
    title: str
    description: str
    why_it_matters: str | None = None
    how_to_execute: str | None = None
    expected_signal: str | None = None
    measurement: str | None = None
    evidence: str | None = None
    priority: str
    status: str
    source_json: dict[str, Any] | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class SocialCalendarEntryResponse(BaseModel):
    id: UUID
    action_item_id: UUID | None = None
    scheduled_at: datetime
    day_index: int
    title: str
    format: str
    channel: str
    status: str
    theme: str | None = None
    hook: str | None = None
    caption_outline: str | None = None
    cta: str | None = None
    evidence: str | None = None
    objective: str | None = None
    source_reference_handle: str | None = None
    metrics_goal_json: dict[str, Any] | None = None
    metadata_json: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class SocialActionPlanResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    onboarding_session_id: UUID
    title: str
    summary: str | None = None
    status: str
    source_analysis_version: int
    source_specialist_version: str | None = None
    plan_version: int
    metadata_json: dict[str, Any] | None = None
    items: list[SocialActionPlanItemResponse]
    calendar_entries: list[SocialCalendarEntryResponse]
    created_at: datetime
    updated_at: datetime


class SocialOnboardingJobResponse(BaseModel):
    id: UUID
    job_type: str
    queue_name: str
    status: str
    idempotency_key: str


class SocialReferenceProfileSyncResponse(BaseModel):
    reference: SocialReferenceProfileResponse
    job: SocialOnboardingJobResponse | None = None


class SocialOnboardingSessionResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    objective: str | None = None
    status: SocialOnboardingStatus
    primary_provider: str | None = None
    connection_mode: str
    connected_account_handle: str | None = None
    connected_account_name: str | None = None
    profile_url: str | None = None
    progress_steps: list[dict[str, Any]]
    profile_snapshot: dict[str, Any]
    analysis_report: dict[str, Any] | None = None
    analysis_version: int
    references: list[SocialReferenceProfileResponse]
    error_code: str | None = None
    error_message: str | None = None
    analysis_started_at: datetime | None = None
    analysis_completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SocialOnboardingCurrentResponse(BaseModel):
    session: SocialOnboardingSessionResponse | None = None


class SocialOnboardingMutationResponse(BaseModel):
    session: SocialOnboardingSessionResponse
    job: SocialOnboardingJobResponse | None = None


class SocialOnboardingPhylloConnectTokenResponse(BaseModel):
    user_id: str
    sdk_token: str
    environment: str
    client_display_name: str
    work_platform_id: str
    products: list[str]
