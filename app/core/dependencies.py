from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token

security = HTTPBearer()


@dataclass(frozen=True)
class CurrentMembership:
    user_id: UUID
    tenant_id: UUID
    membership_id: UUID
    email: str
    nome: str
    role: str
    modules: tuple[str, ...]


def get_current_membership(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> CurrentMembership:
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido ou expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    membership_id = payload.get("membership_id")
    if not membership_id:
        raise HTTPException(status_code=401, detail="Token sem membership ativa")

    row = db.execute(
        text(
            """
            SELECT
              m.id AS membership_id,
              m.tenant_id,
              m.role,
              u.id AS user_id,
              u.email_normalized AS email,
              u.nome,
              COALESCE(
                array_agg(mm.module_key) FILTER (WHERE mm.module_key IS NOT NULL),
                '{}'
              ) AS modules
            FROM memberships m
            JOIN users u ON u.id = m.user_id
            JOIN tenants t ON t.id = m.tenant_id
            LEFT JOIN membership_modules mm ON mm.membership_id = m.id
            WHERE m.id = :membership_id
              AND m.status = 'active'
              AND u.ativo = true
              AND t.ativo = true
            GROUP BY m.id, u.id
            """
        ),
        {"membership_id": membership_id},
    ).mappings().first()

    if row is None:
        raise HTTPException(status_code=403, detail="Membership nao encontrada ou inativa")

    return CurrentMembership(
        user_id=UUID(str(row["user_id"])),
        tenant_id=UUID(str(row["tenant_id"])),
        membership_id=UUID(str(row["membership_id"])),
        email=row["email"],
        nome=row["nome"],
        role=row["role"],
        modules=tuple(row["modules"] or ()),
    )


def require_role(*allowed_roles: str):
    def dependency(
        current: CurrentMembership = Depends(get_current_membership),
    ) -> CurrentMembership:
        if current.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Permissao insuficiente")
        return current

    return dependency


def require_module(module_key: str):
    def dependency(
        current: CurrentMembership = Depends(get_current_membership),
    ) -> CurrentMembership:
        if module_key not in current.modules:
            raise HTTPException(status_code=403, detail="Modulo nao habilitado")
        return current

    return dependency
