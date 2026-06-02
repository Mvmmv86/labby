from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


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
