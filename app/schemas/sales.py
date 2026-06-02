from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

ChannelType = Literal[
    "whatsapp_evolution",
    "whatsapp_cloud",
    "telegram",
    "discord",
    "web_chatbot",
]
ChannelStatus = Literal["desconectado", "conectando", "conectado", "erro"]


class SalesContactCreateRequest(BaseModel):
    nome: str = Field(min_length=1, max_length=180)
    telefone: str | None = Field(default=None, max_length=40)
    email: EmailStr | None = None
    grupo: str | None = Field(default=None, max_length=120)
    tags: list[str] | None = None
    notas: str | None = None
    campos_custom: dict[str, Any] | None = None


class SalesContactUpdateRequest(BaseModel):
    nome: str | None = Field(default=None, min_length=1, max_length=180)
    telefone: str | None = Field(default=None, max_length=40)
    email: EmailStr | None = None
    grupo: str | None = Field(default=None, max_length=120)
    tags: list[str] | None = None
    notas: str | None = None
    campos_custom: dict[str, Any] | None = None
    optout: bool | None = None
    status: Literal["active", "archived", "blocked"] | None = None


class SalesContactBatchRequest(BaseModel):
    contacts: list[dict[str, Any]] = Field(min_length=1, max_length=1000)
    on_duplicate: Literal["skip", "update"] = "skip"


class SalesContactListItem(BaseModel):
    id: UUID
    nome: str
    telefone: str | None = None
    email: str | None = None
    tags: list[str]
    grupo: str | None = None
    total_conversas: int
    canais_vinculados: list[str]
    ultima_interacao: datetime | None = None
    created_at: datetime


class SalesContactDetail(SalesContactListItem):
    notas: str | None = None
    campos_custom: dict[str, Any]
    total_mensagens_enviadas: int
    total_mensagens_recebidas: int
    optout: bool
    status: str
    updated_at: datetime
    canais: list[dict[str, Any]]
    conversas_recentes: list[dict[str, Any]]


class SalesContactsResponse(BaseModel):
    contacts: list[SalesContactListItem]
    total: int
    page: int
    per_page: int
    pages: int


class SalesContactMutationResponse(BaseModel):
    id: UUID
    nome: str
    telefone: str | None = None
    email: str | None = None
    grupo: str | None = None
    tags: list[str]
    notas: str | None = None
    campos_custom: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    message: str


class SalesContactDeleteResponse(BaseModel):
    id: UUID
    message: str


class SalesContactBatchResponse(BaseModel):
    total_enviados: int
    importados: int
    duplicados: int
    erros: int
    sem_telefone: int
    detalhes_erros: list[dict[str, Any]]


class SalesConversationUpdateRequest(BaseModel):
    status: Literal["aberta", "fechada", "pendente"] | None = None
    atendente_id: UUID | None = None
    tags: list[str] | None = None
    assunto: str | None = Field(default=None, max_length=255)


class SalesMessageCreateRequest(BaseModel):
    conteudo: str = Field(min_length=1)
    tipo: Literal["text", "image", "video", "document"] = "text"


class SalesConversationListItem(BaseModel):
    id: UUID
    contato_id: UUID
    contato_nome: str
    contato_telefone: str | None = None
    channel_id: UUID | None = None
    channel_tipo: str | None = None
    channel_nome: str | None = None
    status: str
    assunto: str | None = None
    tags: list[str]
    atendente_id: UUID | None = None
    atendente_nome: str | None = None
    bot_ativo: bool
    aguardando_humano: bool
    ultima_mensagem: str | None = None
    ultima_mensagem_at: datetime | None = None
    mensagens_nao_lidas: int
    created_at: datetime


class SalesConversationsResponse(BaseModel):
    conversations: list[SalesConversationListItem]
    total: int
    page: int
    per_page: int
    pages: int


class SalesConversationContactInfo(BaseModel):
    id: UUID
    nome: str
    telefone: str | None = None
    email: str | None = None
    tags: list[str]
    grupo: str | None = None
    notas: str | None = None
    ultima_interacao: datetime | None = None
    created_at: datetime | None = None


class SalesConversationDetail(BaseModel):
    id: UUID
    contato: SalesConversationContactInfo
    channel: dict[str, Any]
    status: str
    assunto: str | None = None
    tags: list[str]
    atendente_id: UUID | None = None
    atendente_nome: str | None = None
    bot_ativo: bool
    ultima_mensagem_at: datetime | None = None
    fechado_at: datetime | None = None
    created_at: datetime | None = None


class SalesMessageResponse(BaseModel):
    id: UUID
    conversa_id: UUID
    contato_id: UUID | None = None
    direcao: str
    remetente_tipo: str
    remetente_id: UUID | None = None
    tipo: str
    conteudo: str
    media_url: str | None = None
    media_caption: str | None = None
    status: str
    created_at: datetime


class SalesMessagesResponse(BaseModel):
    messages: list[SalesMessageResponse]
    has_more: bool
    next_cursor: UUID | None = None


class SalesConversationMarkReadResponse(BaseModel):
    marked: int


class SalesConversationMutationResponse(BaseModel):
    id: UUID
    status: str
    atendente_id: UUID | None = None
    assunto: str | None = None
    tags: list[str] = Field(default_factory=list)
    message: str


class SalesNotificationAwaitingConversation(BaseModel):
    id: UUID
    contato_nome: str
    channel_tipo: str | None = None
    ultima_mensagem: str | None = None
    ultima_mensagem_at: datetime | None = None
    mensagens_nao_lidas: int


class SalesNotificationSummary(BaseModel):
    transferencias_pendentes: int
    total_nao_lidas: int
    conversas_aguardando: list[SalesNotificationAwaitingConversation]


class SalesChannelCreateRequest(BaseModel):
    tipo: ChannelType
    nome: str = Field(min_length=1, max_length=120)
    config: dict[str, Any] | None = None


class SalesChannelUpdateRequest(BaseModel):
    nome: str | None = Field(default=None, min_length=1, max_length=120)
    config: dict[str, Any] | None = None


class SalesChannelConnectRequest(BaseModel):
    bot_token: str | None = None
    phone_number_id: str | None = None
    access_token: str | None = None
    waba_id: str | None = None
    guild_id: str | None = None
    greeting: str | None = Field(default=None, max_length=500)
    position: str | None = Field(default=None, max_length=40)
    widget_color: str | None = Field(default=None, max_length=40)


class SalesChannelResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    tipo: ChannelType
    nome: str
    status: ChannelStatus
    config: dict[str, Any]
    webhook_configured: bool
    ultimo_evento_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SalesChannelsResponse(BaseModel):
    channels: list[SalesChannelResponse]


class SalesChannelStatusResponse(BaseModel):
    id: UUID
    tipo: ChannelType
    nome: str
    status: ChannelStatus
    numero: str | None = None
    phone_number: str | None = None
    bot_username: str | None = None
    guild_name: str | None = None
    widget_id: str | None = None
    config: dict[str, Any] | None = None
    ultimo_evento_at: datetime | None = None


class SalesChannelDeleteResponse(BaseModel):
    id: UUID
    message: str


class SalesChannelConnectionResponse(BaseModel):
    status: ChannelStatus
    message: str | None = None
    qr_code: str | None = None
    instance_name: str | None = None
    phone_number: str | None = None
    numero: str | None = None
    bot_username: str | None = None
    bot_name: str | None = None
    oauth_url: str | None = None
    widget_id: str | None = None
    snippet: str | None = None


class SalesWebhookReceiveResponse(BaseModel):
    status: str
    webhook_event_id: UUID | None = None
    job_id: UUID | None = None
    duplicate: bool = False


class SalesDashboardStats(BaseModel):
    mensagens_hoje: int
    mensagens_semana: int
    contatos_total: int
    conversas_abertas: int
    campanhas_ativas: int
    taxa_resposta: float


class SalesMessageVolumeItem(BaseModel):
    date: str
    enviadas: int
    recebidas: int


class SalesMessageVolumeResponse(BaseModel):
    period: Literal["7d", "30d", "90d"]
    data: list[SalesMessageVolumeItem]


class SalesRecentActivityItem(BaseModel):
    tipo: Literal["conversa", "campanha"]
    titulo: str
    descricao: str | None = None
    canal: str | None = None
    timestamp: datetime | None = None
    link_id: UUID
    status: str
    aguardando_humano: bool
