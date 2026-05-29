from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.auth import LabbyModule


class CurrentModulesResponse(BaseModel):
    modules: list[LabbyModule]
    default_module: str


class LabbyUserModule(BaseModel):
    id: str
    nome: str
    email: str
    role: str
    ativo: bool
    default_module: str
    updated_at: datetime | None
    modules: list[LabbyModule]


class UserModulesStats(BaseModel):
    total: int
    sales: int
    social_media: int


class UserModulesResponse(BaseModel):
    users: list[LabbyUserModule]
    total: int
    limit: int
    offset: int
    stats: UserModulesStats


class UpdateUserModulesRequest(BaseModel):
    module_keys: list[str] = Field(min_length=1)
    default_module: str | None = None
    expected_updated_at: datetime | None = None


class UpdateUserModulesResponse(BaseModel):
    user_id: str
    modules: list[LabbyModule]
    default_module: str
    updated_at: datetime | None
