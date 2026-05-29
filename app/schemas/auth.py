from pydantic import BaseModel, EmailStr, Field


class LabbyModule(BaseModel):
    key: str
    label: str
    description: str
    accent: str
    accent_bright: str


class UserResponse(BaseModel):
    id: str
    tenant_id: str
    nome: str
    email: EmailStr
    avatar_url: str | None = None
    role: str


class TenantResponse(BaseModel):
    id: str
    nome: str
    slug: str
    plano: str
    whatsapp_conectado: bool = False
    whatsapp_numero: str | None = None
    whatsapp_status: str = "disconnected"
    limite_mensagens_mes: int = 1000
    mensagens_mes_atual: int = 0
    limite_contatos: int = 500
    limite_bots: int = 1
    limite_atendentes: int = 3
    ativo: bool
    canais_conectados: int = 0
    canais: list[dict] = Field(default_factory=list)
    modules: list[LabbyModule] = Field(default_factory=list)
    default_module: str


class MembershipResponse(BaseModel):
    id: str
    tenant_id: str
    tenant_nome: str
    tenant_slug: str
    role: str
    modules: list[LabbyModule]
    default_module: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse
    tenant: TenantResponse


class MeResponse(BaseModel):
    user: UserResponse
    tenant: TenantResponse
    memberships: list[MembershipResponse]


class LoginRequest(BaseModel):
    email: EmailStr
    senha: str


class RegisterRequest(BaseModel):
    nome: str = Field(min_length=1, max_length=160)
    email: EmailStr
    senha: str = Field(min_length=8, max_length=128)
    empresa: str = Field(min_length=1, max_length=180)
    telefone: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class SwitchTenantRequest(BaseModel):
    membership_id: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    senha: str = Field(min_length=8, max_length=128)
