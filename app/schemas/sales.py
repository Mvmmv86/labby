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
