import json
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.dependencies import CurrentMembership
from app.core.security import hash_password, hash_token, make_opaque_token, verify_password
from app.domains.identity.auth_service import AuthService
from app.domains.identity.modules import ModuleAccess, module_payload
from app.domains.identity.normalization import normalize_email
from app.integrations.email import EmailDeliveryResult, EmailService
from app.schemas.team import (
    LabbyTeamInvite,
    PublicTeamInvite,
    TeamInvitesResponse,
)

ADMIN_ROLES = {"owner", "admin"}
INVITE_ROLES = {"admin", "agent", "viewer"}
INVITE_TTL_DAYS = 7


class TeamService:
    def __init__(
        self,
        db: Session,
        auth_service: AuthService,
        email_service: EmailService,
    ) -> None:
        self.db = db
        self.auth_service = auth_service
        self.email_service = email_service

    def list_invites(
        self,
        *,
        current: CurrentMembership,
        status: str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> TeamInvitesResponse:
        self._require_admin(current)
        limit = min(max(limit, 1), 100)
        offset = max(offset, 0)
        filters = []
        params: dict[str, object] = {
            "tenant_id": str(current.tenant_id),
            "limit": limit,
            "offset": offset,
        }
        if status:
            filters.append("ti.status = :status")
            params["status"] = status
        if search:
            filters.append("(ti.nome ILIKE :search OR ti.email_normalized ILIKE :search)")
            params["search"] = f"%{search.strip()}%"

        filter_sql = f"AND {' AND '.join(filters)}" if filters else ""
        rows = self.db.execute(
            text(
                f"""
                SELECT
                  ti.*,
                  iu.nome AS invited_by_nome
                FROM team_invites ti
                LEFT JOIN memberships im ON im.id = ti.invited_by_membership_id
                LEFT JOIN users iu ON iu.id = im.user_id
                WHERE ti.tenant_id = :tenant_id
                  {filter_sql}
                ORDER BY ti.created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
        total = self.db.execute(
            text(
                f"""
                SELECT COUNT(*) AS total
                FROM team_invites ti
                WHERE ti.tenant_id = :tenant_id
                  {filter_sql}
                """
            ),
            params,
        ).mappings().one()
        return TeamInvitesResponse(
            invites=[self._invite_response(row) for row in rows],
            total=int(total["total"] or 0),
            limit=limit,
            offset=offset,
        )

    def create_invite(
        self,
        *,
        current: CurrentMembership,
        nome: str,
        email: str,
        role: str,
        module_keys: list[str],
        default_module: str | None,
    ) -> tuple[LabbyTeamInvite, EmailDeliveryResult]:
        access = self._validate_invite_access(
            current=current,
            role=role,
            module_keys=module_keys,
            default_module=default_module,
        )
        email_normalized = normalize_email(email)
        self._ensure_email_not_member(
            tenant_id=str(current.tenant_id),
            email_normalized=email_normalized,
        )

        token = make_opaque_token()
        try:
            invite_id = self.db.execute(
                text(
                    """
                    INSERT INTO team_invites (
                      tenant_id,
                      invited_by_membership_id,
                      email_normalized,
                      nome,
                      role,
                      default_module,
                      module_keys,
                      token_hash,
                      status,
                      expires_at
                    )
                    VALUES (
                      :tenant_id,
                      :invited_by,
                      :email,
                      :nome,
                      :role,
                      :default_module,
                      CAST(:module_keys AS jsonb),
                      :token_hash,
                      'pending',
                      :expires_at
                    )
                    RETURNING id
                    """
                ),
                {
                    "tenant_id": str(current.tenant_id),
                    "invited_by": str(current.membership_id),
                    "email": email_normalized,
                    "nome": nome.strip(),
                    "role": role,
                    "default_module": access.default_module,
                    "module_keys": json.dumps(list(access.modules)),
                    "token_hash": hash_token(token),
                    "expires_at": self._new_expiration(),
                },
            ).scalar_one()
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(status_code=409, detail="Convite pendente ja existe") from exc

        result = self._send_invite(invite_id=str(invite_id), token=token)
        invite = self._invite_by_id(
            invite_id=str(invite_id),
            tenant_id=str(current.tenant_id),
        )
        return invite, result

    def resend_invite(
        self,
        *,
        current: CurrentMembership,
        invite_id: str,
    ) -> tuple[LabbyTeamInvite, EmailDeliveryResult]:
        self._require_admin(current)
        invite = self._invite_row(invite_id=invite_id, tenant_id=str(current.tenant_id))
        if not invite or invite["status"] != "pending":
            raise HTTPException(status_code=404, detail="Convite pendente nao encontrado")
        if self._is_expired(invite["expires_at"]):
            self._mark_expired(invite_id)
            raise HTTPException(status_code=410, detail="Convite expirado")

        token = make_opaque_token()
        self.db.execute(
            text(
                """
                UPDATE team_invites
                SET token_hash = :token_hash,
                    expires_at = :expires_at,
                    resend_count = resend_count + 1,
                    updated_at = NOW()
                WHERE id = :invite_id
                  AND tenant_id = :tenant_id
                  AND status = 'pending'
                """
            ),
            {
                "invite_id": invite_id,
                "tenant_id": str(current.tenant_id),
                "token_hash": hash_token(token),
                "expires_at": self._new_expiration(),
            },
        )
        self.db.commit()

        result = self._send_invite(invite_id=invite_id, token=token)
        updated_invite = self._invite_by_id(invite_id=invite_id, tenant_id=str(current.tenant_id))
        return updated_invite, result

    def revoke_invite(self, *, current: CurrentMembership, invite_id: str) -> LabbyTeamInvite:
        self._require_admin(current)
        row = self.db.execute(
            text(
                """
                UPDATE team_invites
                SET status = 'revoked', revoked_at = NOW(), updated_at = NOW()
                WHERE id = :invite_id
                  AND tenant_id = :tenant_id
                  AND status = 'pending'
                RETURNING id
                """
            ),
            {"invite_id": invite_id, "tenant_id": str(current.tenant_id)},
        ).mappings().first()
        if not row:
            self.db.rollback()
            raise HTTPException(status_code=404, detail="Convite pendente nao encontrado")
        self.db.commit()
        return self._invite_by_id(invite_id=invite_id, tenant_id=str(current.tenant_id))

    def public_invite(self, *, token: str) -> PublicTeamInvite:
        invite = self._invite_by_token(token)
        if not invite or invite["status"] != "pending":
            raise HTTPException(status_code=404, detail="Convite nao encontrado")
        if self._is_expired(invite["expires_at"]):
            self._mark_expired(str(invite["id"]))
            raise HTTPException(status_code=410, detail="Convite expirado")

        return PublicTeamInvite(
            id=str(invite["id"]),
            tenant={"id": str(invite["tenant_id"]), "nome": invite["tenant_nome"]},
            email=invite["email_normalized"],
            nome=invite["nome"],
            role=invite["role"],
            default_module=invite["default_module"],
            expires_at=invite["expires_at"],
            modules=[module_payload(key) for key in self._module_keys(invite["module_keys"])],
        )

    def accept_invite(
        self,
        *,
        token: str,
        senha: str,
        nome: str | None = None,
    ):
        invite = self._invite_by_token(token, for_update=True)
        if not invite or invite["status"] != "pending":
            self.db.rollback()
            raise HTTPException(status_code=404, detail="Convite nao encontrado")
        if self._is_expired(invite["expires_at"]):
            self._mark_expired(str(invite["id"]))
            raise HTTPException(status_code=410, detail="Convite expirado")

        user = self.db.execute(
            text(
                """
                SELECT id, senha_hash, ativo
                FROM users
                WHERE email_normalized = :email
                """
            ),
            {"email": invite["email_normalized"]},
        ).mappings().first()

        try:
            if user:
                if not user["ativo"] or not verify_password(senha, user["senha_hash"]):
                    self.db.rollback()
                    raise HTTPException(status_code=401, detail="Senha incorreta")
                user_id = str(user["id"])
            else:
                user_id = str(
                    self.db.execute(
                        text(
                            """
                            INSERT INTO users (
                              nome, email_normalized, senha_hash, email_verified_at, ativo
                            )
                            VALUES (:nome, :email, :senha_hash, NOW(), true)
                            RETURNING id
                            """
                        ),
                        {
                            "nome": (nome or invite["nome"]).strip(),
                            "email": invite["email_normalized"],
                            "senha_hash": hash_password(senha),
                        },
                    ).scalar_one()
                )

            existing_membership = self._membership_for_user(
                user_id=user_id,
                tenant_id=str(invite["tenant_id"]),
            )
            if existing_membership:
                membership_id = str(existing_membership["id"])
            else:
                membership_id = self._create_membership_from_invite(
                    user_id=user_id,
                    invite=invite,
                )

            self.db.execute(
                text(
                    """
                    UPDATE team_invites
                    SET status = 'accepted',
                        accepted_by_membership_id = :membership_id,
                        accepted_at = NOW(),
                        updated_at = NOW()
                    WHERE id = :invite_id
                    """
                ),
                {"invite_id": str(invite["id"]), "membership_id": membership_id},
            )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(status_code=409, detail="Convite ja aceito") from exc

        return self.auth_service.issue_for_membership(membership_id)

    def _create_membership_from_invite(self, *, user_id: str, invite) -> str:
        membership_id = str(
            self.db.execute(
                text(
                    """
                    INSERT INTO memberships (
                      user_id, tenant_id, role, default_module, status, last_access_at
                    )
                    VALUES (:user_id, :tenant_id, :role, :default_module, 'active', NOW())
                    RETURNING id
                    """
                ),
                {
                    "user_id": user_id,
                    "tenant_id": str(invite["tenant_id"]),
                    "role": invite["role"],
                    "default_module": invite["default_module"],
                },
            ).scalar_one()
        )
        for module_key in self._module_keys(invite["module_keys"]):
            self.db.execute(
                text(
                    """
                    INSERT INTO membership_modules (membership_id, module_key)
                    VALUES (:membership_id, :module_key)
                    """
                ),
                {"membership_id": membership_id, "module_key": module_key},
            )
        return membership_id

    def _send_invite(self, *, invite_id: str, token: str) -> EmailDeliveryResult:
        row = self._invite_row(invite_id=invite_id, tenant_id=None)
        if not row:
            return EmailDeliveryResult(sent=False, error="Convite nao encontrado")

        invite_url = f"{get_settings().app_base_url}/convite/{token}"
        result = self.email_service.send_team_invite(
            to_email=row["email_normalized"],
            to_name=row["nome"],
            tenant_name=row["tenant_nome"],
            invite_url=invite_url,
        )
        if result.sent:
            self.db.execute(
                text(
                    """
                    UPDATE team_invites
                    SET last_sent_at = NOW(), updated_at = NOW()
                    WHERE id = :invite_id
                    """
                ),
                {"invite_id": invite_id},
            )
            self.db.commit()
        return result

    def _ensure_email_not_member(self, *, tenant_id: str, email_normalized: str) -> None:
        row = self.db.execute(
            text(
                """
                SELECT 1
                FROM memberships m
                JOIN users u ON u.id = m.user_id
                WHERE m.tenant_id = :tenant_id
                  AND u.email_normalized = :email
                  AND m.status = 'active'
                """
            ),
            {"tenant_id": tenant_id, "email": email_normalized},
        ).first()
        if row:
            raise HTTPException(status_code=409, detail="Usuario ja faz parte deste tenant")

    def _validate_invite_access(
        self,
        *,
        current: CurrentMembership,
        role: str,
        module_keys: list[str],
        default_module: str | None,
    ) -> ModuleAccess:
        self._require_admin(current)
        if role not in INVITE_ROLES:
            raise HTTPException(status_code=422, detail="Perfil de convite invalido")

        modules = tuple(dict.fromkeys(module_keys))
        if not modules:
            raise HTTPException(
                status_code=422,
                detail="Pelo menos um modulo precisa estar habilitado",
            )
        access = ModuleAccess(
            modules=modules,
            default_module=default_module or modules[0],
        )
        try:
            access.validate()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        if current.role != "owner" and not set(access.modules).issubset(set(current.modules)):
            raise HTTPException(
                status_code=403,
                detail="Nao e permitido convidar modulo sem acesso",
            )
        return access

    def _membership_for_user(self, *, user_id: str, tenant_id: str):
        return self.db.execute(
            text(
                """
                SELECT id
                FROM memberships
                WHERE user_id = :user_id
                  AND tenant_id = :tenant_id
                  AND status = 'active'
                """
            ),
            {"user_id": user_id, "tenant_id": tenant_id},
        ).mappings().first()

    def _invite_by_id(self, *, invite_id: str, tenant_id: str) -> LabbyTeamInvite:
        row = self._invite_row(invite_id=invite_id, tenant_id=tenant_id)
        if not row:
            raise HTTPException(status_code=404, detail="Convite nao encontrado")
        return self._invite_response(row)

    def _invite_row(self, *, invite_id: str, tenant_id: str | None):
        tenant_filter = "AND ti.tenant_id = :tenant_id" if tenant_id else ""
        params = {"invite_id": invite_id}
        if tenant_id:
            params["tenant_id"] = tenant_id
        return self.db.execute(
            text(
                f"""
                SELECT
                  ti.*,
                  t.nome AS tenant_nome,
                  iu.nome AS invited_by_nome
                FROM team_invites ti
                JOIN tenants t ON t.id = ti.tenant_id
                LEFT JOIN memberships im ON im.id = ti.invited_by_membership_id
                LEFT JOIN users iu ON iu.id = im.user_id
                WHERE ti.id = :invite_id
                  {tenant_filter}
                """
            ),
            params,
        ).mappings().first()

    def _invite_by_token(self, token: str, *, for_update: bool = False):
        lock = "FOR UPDATE" if for_update else ""
        return self.db.execute(
            text(
                f"""
                SELECT
                  ti.*,
                  t.nome AS tenant_nome
                FROM team_invites ti
                JOIN tenants t ON t.id = ti.tenant_id
                WHERE ti.token_hash = :token_hash
                {lock}
                """
            ),
            {"token_hash": hash_token(token)},
        ).mappings().first()

    def _mark_expired(self, invite_id: str) -> None:
        self.db.execute(
            text(
                """
                UPDATE team_invites
                SET status = 'expired', updated_at = NOW()
                WHERE id = :invite_id
                  AND status = 'pending'
                """
            ),
            {"invite_id": invite_id},
        )
        self.db.commit()

    @staticmethod
    def _invite_response(row) -> LabbyTeamInvite:
        module_keys = TeamService._module_keys(row["module_keys"])
        return LabbyTeamInvite(
            id=str(row["id"]),
            tenant_id=str(row["tenant_id"]),
            email=row["email_normalized"],
            nome=row["nome"],
            role=row["role"],
            default_module=row["default_module"],
            status=row["status"],
            expires_at=row["expires_at"],
            last_sent_at=row["last_sent_at"],
            resend_count=row["resend_count"],
            invited_by_id=str(row["invited_by_membership_id"])
            if row["invited_by_membership_id"]
            else None,
            invited_by_nome=row["invited_by_nome"] if "invited_by_nome" in row else None,
            accepted_at=row["accepted_at"],
            revoked_at=row["revoked_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            modules=[module_payload(key) for key in module_keys],
        )

    @staticmethod
    def _module_keys(raw) -> tuple[str, ...]:
        if isinstance(raw, str):
            return tuple(json.loads(raw))
        return tuple(raw or ())

    @staticmethod
    def _is_expired(expires_at: datetime) -> bool:
        now = datetime.now(UTC)
        if expires_at.tzinfo is None:
            now = now.replace(tzinfo=None)
        return expires_at <= now

    @staticmethod
    def _new_expiration() -> datetime:
        return datetime.now(UTC) + timedelta(days=INVITE_TTL_DAYS)

    @staticmethod
    def _require_admin(current: CurrentMembership) -> None:
        if current.role not in ADMIN_ROLES:
            raise HTTPException(status_code=403, detail="Permissao insuficiente")
