from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class SocialNewsSegmentMutationResponse(BaseModel):
    id: UUID
    slug: str | None = None
    seed_origem: str | None = None
    updated: bool | None = None


class SocialNewsSegmentCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=120)
    name: str | None = Field(default=None, min_length=1, max_length=180)
    nome: str | None = Field(default=None, min_length=1, max_length=180)
    idioma: str = Field(default="pt", max_length=12)
    description: str | None = None
    descricao: str | None = None
    base_knowledge: str | None = None
    base_conhecimento: str | None = None
    disclaimer: str | None = None
    min_engagement_score: int = Field(default=0, ge=0)
    config: dict[str, Any] = Field(default_factory=dict)


class SocialNewsSegmentFromSeedCreate(BaseModel):
    seed_origem: str = Field(min_length=1, max_length=120)


class SocialNewsSegmentPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    nome: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = None
    descricao: str | None = None
    base_knowledge: str | None = None
    base_conhecimento: str | None = None
    disclaimer: str | None = None
    status: Literal["active", "inactive", "archived"] | None = None
    ativo: bool | None = None
    min_engagement_score: int | None = Field(default=None, ge=0)
    tipos_evento: list[str] | None = None
    vocabulario: list[str] | None = None
    config: dict[str, Any] | None = None


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


class SocialNewsFrontendSegmentResponse(BaseModel):
    id: UUID
    slug: str
    nome: str
    idioma: str
    descricao: str | None = None
    disclaimer: str | None = None
    base_conhecimento: str | None = None
    min_engagement_score: int
    tipos_evento: list[str] = Field(default_factory=list)
    vocabulario: list[str] = Field(default_factory=list)
    ativo: bool
    created_at: datetime


class SocialNewsFrontendSegmentsResponse(BaseModel):
    segments: list[SocialNewsFrontendSegmentResponse]


class SocialNewsSourceCreate(BaseModel):
    source_type: Literal["x_handle", "x_keyword", "x_query"]
    value: str | None = Field(default=None, min_length=1, max_length=500)
    valor: str | None = Field(default=None, min_length=1, max_length=500)
    provider: Literal["x"] = "x"
    min_likes: int = Field(default=100, ge=0)
    min_reposts: int = Field(default=50, ge=0)
    min_replies: int = Field(default=10, ge=0)
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


class SocialNewsFrontendSourceResponse(BaseModel):
    id: UUID
    source_type: str
    valor: str
    min_likes: int
    min_reposts: int
    min_replies: int
    min_impressions: int
    ativo: bool
    origem: str
    created_at: datetime


class SocialNewsFrontendSourcesResponse(BaseModel):
    sources: list[SocialNewsFrontendSourceResponse]


class SocialNewsSourceMutationResponse(BaseModel):
    id: UUID


class SocialNewsCuratorUpsertRequest(BaseModel):
    nome: str = Field(min_length=1, max_length=180)
    modelo: str = Field(default="gpt-4o-mini", max_length=80)
    temperatura: float = Field(default=0.4, ge=0, le=2)
    max_tokens: int = Field(default=600, gt=0)
    system_prompt_complementar: str | None = None
    base_conhecimento: str | None = None
    ativo: bool | None = None


class SocialNewsFrontendCuratorResponse(BaseModel):
    id: UUID
    segment_id: UUID
    nome: str
    modelo: str
    temperatura: float
    max_tokens: int
    system_prompt_complementar: str | None = None
    base_conhecimento: str | None = None
    ativo: bool


class SocialNewsCuratorMutationResponse(BaseModel):
    id: UUID
    segment_id: UUID


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


class SocialNewsManualRunCreate(BaseModel):
    segment_id: UUID


class SocialNewsManualRunResponse(BaseModel):
    id: UUID
    status: str


class SocialNewsFrontendRunResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    segment_id: UUID
    run_type: str
    schedule_id: UUID | None = None
    window_start_at: datetime | None = None
    status: str
    candidatos_count: int
    ranqueados_count: int
    aprovados_stage1: int
    aprovados_stage2: int
    enviados_count: int
    falhas_count: int
    erro_mensagem: str | None = None
    iniciado_at: datetime
    concluido_at: datetime | None = None
    updated_at: datetime
    iniciado_por: str | None = None
    custo_estimado_usd: float
    custo_x_api_usd: float
    custo_llm_usd: float
    custo_resend_usd: float


class SocialNewsFrontendRunsResponse(BaseModel):
    runs: list[SocialNewsFrontendRunResponse]


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


class SocialNewsSchedulePatch(BaseModel):
    ativo: bool | None = None
    scheduled_hour: int | None = Field(default=None, ge=0, le=23)
    scheduled_minute: int | None = Field(default=None, ge=0, le=59)
    confidence_score: float | None = Field(default=None, ge=0, le=100)
    nome: str | None = Field(default=None, min_length=1, max_length=120)


class SocialNewsFrontendScheduleResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    segment_id: UUID
    nome: str | None = None
    timezone: str
    day_of_week: int | None = None
    window_start_hour: int
    window_end_hour: int
    scheduled_hour: int
    scheduled_minute: int
    confidence_score: float
    amostras_count: int
    score_medio: float | None = None
    descoberto_por: str
    origem_run_id: UUID | None = None
    ativo: bool
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SocialNewsFrontendSchedulesResponse(BaseModel):
    schedules: list[SocialNewsFrontendScheduleResponse]


class SocialNewsScheduleRecalibrationResponse(BaseModel):
    run_id: UUID
    schedules: list[SocialNewsFrontendScheduleResponse]


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


class SocialNewsFrontendSubscriberCreate(BaseModel):
    segment_id: UUID
    email: EmailStr
    nome: str | None = Field(default=None, max_length=180)
    origem: str = Field(default="manual", max_length=80)


class SocialNewsFrontendSubscriberPatch(BaseModel):
    nome: str | None = Field(default=None, max_length=180)
    status: Literal["active", "unsubscribed", "bounced", "complained", "removed"] | None = None
    metadata: dict[str, Any] | None = None


class SocialNewsSubscriberCsvImportRequest(BaseModel):
    segment_id: UUID
    csv_text: str = Field(min_length=3)


class SocialNewsSubscriberCsvImportResponse(BaseModel):
    created: int
    skipped: int
    errors: list[str]


class SocialNewsFrontendSubscriberResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    segment_id: UUID
    email: str
    nome: str | None = None
    status: str
    origem: str
    consent_status: str
    consent_given_at: datetime | None = None
    consent_source: str | None = None
    unsubscribed_at: datetime | None = None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SocialNewsFrontendSubscribersResponse(BaseModel):
    subscribers: list[SocialNewsFrontendSubscriberResponse]


class SocialNewsUnsubscribeResponse(BaseModel):
    status: str
    subscriber_id: UUID
    email: str | None = None
    segment_id: UUID | None = None
