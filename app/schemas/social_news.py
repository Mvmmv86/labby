from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class SocialNewsSegmentCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=180)
    description: str | None = None
    base_knowledge: str | None = None
    disclaimer: str | None = None
    min_engagement_score: int = Field(default=0, ge=0)
    config: dict[str, Any] = Field(default_factory=dict)


class SocialNewsSegmentResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    slug: str
    name: str
    description: str | None = None
    base_knowledge: str | None = None
    disclaimer: str | None = None
    min_engagement_score: int
    status: str
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SocialNewsSegmentsResponse(BaseModel):
    segments: list[SocialNewsSegmentResponse]


class SocialNewsSourceCreate(BaseModel):
    source_type: Literal["x_handle", "x_keyword", "x_query"]
    value: str = Field(min_length=1, max_length=500)
    provider: Literal["x"] = "x"
    min_likes: int = Field(default=0, ge=0)
    min_reposts: int = Field(default=0, ge=0)
    min_replies: int = Field(default=0, ge=0)
    min_impressions: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SocialNewsSourceResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    segment_id: UUID
    provider: str
    source_type: str
    value: str
    min_likes: int
    min_reposts: int
    min_replies: int
    min_impressions: int
    status: str
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SocialNewsSourcesResponse(BaseModel):
    sources: list[SocialNewsSourceResponse]


class SocialNewsRunCreate(BaseModel):
    segment_id: UUID
    idempotency_key: str | None = Field(default=None, max_length=180)
    run_type: Literal["manual", "scheduled", "calibration"] = "manual"


class SocialNewsRunResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    membership_id: UUID | None = None
    segment_id: UUID
    job_id: UUID | None = None
    run_type: str
    status: str
    idempotency_key: str
    window_start_at: datetime | None = None
    candidates_count: int
    ranked_count: int
    approved_stage1_count: int
    approved_stage2_count: int
    sent_count: int
    failed_count: int
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class EnqueuedJobResponse(BaseModel):
    id: UUID
    job_type: str
    queue_name: str
    status: str
    idempotency_key: str


class SocialNewsRunCreatedResponse(BaseModel):
    run: SocialNewsRunResponse
    job: EnqueuedJobResponse


class SocialNewsRunsResponse(BaseModel):
    runs: list[SocialNewsRunResponse]


class SocialNewsItemResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    run_id: UUID
    segment_id: UUID
    source_id: UUID | None = None
    provider: str
    external_id: str
    external_url: str | None = None
    published_at: datetime | None = None
    author_handle: str | None = None
    author_name: str | None = None
    original_content: str
    rewritten_content: str | None = None
    rewritten_model: str | None = None
    rewritten_at: datetime | None = None
    media_urls: list[Any]
    metrics: dict[str, Any]
    ranking_score: int | None = None
    ranking_reason: str | None = None
    ranking_source: str | None = None
    type_match: str | None = None
    status: str
    approved_stage1_by_membership_id: UUID | None = None
    approved_stage1_at: datetime | None = None
    approved_stage2_by_membership_id: UUID | None = None
    approved_stage2_at: datetime | None = None
    rejection_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class SocialNewsItemsResponse(BaseModel):
    items: list[SocialNewsItemResponse]


class SocialNewsFrontendItemResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    run_id: UUID
    segment_id: UUID
    source_id: UUID | None = None
    source_type: str | None = None
    source_valor: str | None = None
    external_id: str
    external_url: str
    published_at: datetime | None = None
    autor_handle: str
    autor_nome: str | None = None
    autor_verified: bool
    autor_followers_count: int | None = None
    conteudo_original: str
    media_urls: list[Any]
    metrics: dict[str, Any]
    ranking_score: int | None = None
    ranking_motivo: str | None = None
    ranking_origem: str | None = None
    tipo_match: str | None = None
    conteudo_reescrito: str | None = None
    reescrito_modelo: str | None = None
    reescrito_at: datetime | None = None
    rejeitado_motivo: str | None = None
    aprovado_stage1_por: str | None = None
    aprovado_stage1_at: datetime | None = None
    aprovado_stage2_por: str | None = None
    aprovado_stage2_at: datetime | None = None
    feedback_label: str | None = None
    status: str
    created_at: datetime


class SocialNewsFrontendItemsResponse(BaseModel):
    items: list[SocialNewsFrontendItemResponse]


class SocialNewsCurationRequest(BaseModel):
    idempotency_key: str | None = Field(default=None, max_length=180)
    rejection_reason: str | None = Field(default=None, max_length=2000)


class SocialNewsStageDecisionRequest(BaseModel):
    action: Literal["approve", "reject"]
    motivo: str | None = Field(default=None, max_length=2000)
    rewrite_on_approve: bool = True
    idempotency_key: str | None = Field(default=None, max_length=180)


class SocialNewsJobRequest(BaseModel):
    idempotency_key: str | None = Field(default=None, max_length=180)


class SocialNewsJobResponse(BaseModel):
    job: EnqueuedJobResponse


class SocialNewsCurationResponse(BaseModel):
    item: SocialNewsItemResponse
    job: EnqueuedJobResponse | None = None


class SocialNewsDispatchConfigResponse(BaseModel):
    email_enabled: bool
    from_email: str | None = None
    resend_api_key_configured: bool


class SocialNewsDispatchResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    run_id: UUID
    subscriber_id: UUID
    email_normalized: str
    subject: str
    status: str
    idempotency_key: str
    provider: str
    provider_message_id: str | None = None
    error_message: str | None = None
    sent_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SocialNewsDispatchesResponse(BaseModel):
    dispatches: list[SocialNewsDispatchResponse]


class SocialNewsFrontendDispatchResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    run_id: UUID
    subscriber_id: UUID
    email: str
    subject: str
    status: str
    idempotency_key: str
    resend_id: str | None = None
    error_message: str | None = None
    sent_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SocialNewsFrontendDispatchesResponse(BaseModel):
    dispatches: list[SocialNewsFrontendDispatchResponse]


class SocialNewsDispatchEnqueuedResponse(BaseModel):
    run_id: UUID
    sent: int
    failed: int
    skipped: int
    subscribers: int
    items: int
    job: EnqueuedJobResponse


class SocialNewsFrontendDispatchRunResponse(BaseModel):
    run_id: UUID
    sent: int
    failed: int
    skipped: int
    subscribers: int
    items: int


class SocialNewsSubscriberCreate(BaseModel):
    email: EmailStr
    name: str | None = Field(default=None, max_length=180)
    origin: str = Field(default="manual", max_length=80)
    consent_source: str = Field(default="admin", max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SocialNewsSubscriberResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    segment_id: UUID
    email_normalized: str
    name: str | None = None
    status: str
    origin: str
    consent_status: str
    consent_source: str | None = None
    consent_given_at: datetime | None = None
    unsubscribed_at: datetime | None = None
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SocialNewsSubscriberCreatedResponse(BaseModel):
    subscriber: SocialNewsSubscriberResponse
    unsubscribe_token: str


class SocialNewsSubscribersResponse(BaseModel):
    subscribers: list[SocialNewsSubscriberResponse]


class SocialNewsUnsubscribeResponse(BaseModel):
    status: str
    subscriber_id: UUID
