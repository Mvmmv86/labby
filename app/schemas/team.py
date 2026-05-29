from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.schemas.auth import AuthResponse, LabbyModule


class LabbyTeamInvite(BaseModel):
    id: str
    tenant_id: str
    email: str
    nome: str
    role: str
    default_module: str
    status: str
    expires_at: datetime | None
    last_sent_at: datetime | None
    resend_count: int
    invited_by_id: str | None
    invited_by_nome: str | None = None
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None
    modules: list[LabbyModule]


class TeamInvitesResponse(BaseModel):
    invites: list[LabbyTeamInvite]
    total: int
    limit: int
    offset: int


class CreateTeamInviteRequest(BaseModel):
    nome: str = Field(min_length=1, max_length=160)
    email: EmailStr
    role: str
    module_keys: list[str] = Field(min_length=1)
    default_module: str | None = None


class InviteMutationResponse(BaseModel):
    invite: LabbyTeamInvite
    email_sent: bool
    email_error: str | None = None


class PublicTeamInvite(BaseModel):
    id: str
    tenant: dict[str, str]
    email: str
    nome: str
    role: str
    default_module: str
    expires_at: datetime | None
    modules: list[LabbyModule]


class AcceptTeamInviteRequest(BaseModel):
    senha: str = Field(min_length=8, max_length=128)
    nome: str | None = Field(default=None, max_length=160)


class AcceptTeamInviteResponse(AuthResponse):
    pass
