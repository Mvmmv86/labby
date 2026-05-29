import secrets
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password, verify_password
from app.domains.identity.modules import (
    DEFAULT_OWNER_MODULES,
    module_payload,
    modules_payload,
)
from app.domains.identity.normalization import normalize_email, slugify
from app.domains.identity.token_store import (
    PasswordResetStore,
    RefreshTokenNotFoundError,
    RefreshTokenReuseError,
    RefreshTokenStore,
    make_jti,
)
from app.schemas.auth import (
    AuthResponse,
    MembershipResponse,
    MeResponse,
    TenantResponse,
    UserResponse,
)

DUMMY_PASSWORD_HASH = "$2b$12$O6tiWjU/E9DC558mqqEdgO7moENkt0KYbwvJ1ptNek2k.uMa6GRRu"


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    tenant_id: str
    membership_id: str
    nome: str
    email: str
    role: str
    tenant_nome: str
    tenant_slug: str
    tenant_plano: str
    tenant_ativo: bool
    modules: tuple[str, ...]
    default_module: str


class AuthService:
    def __init__(
        self,
        db: Session,
        refresh_store: RefreshTokenStore,
        password_reset_store: PasswordResetStore,
    ) -> None:
        self.db = db
        self.refresh_store = refresh_store
        self.password_reset_store = password_reset_store

    def register(
        self,
        *,
        nome: str,
        email: str,
        senha: str,
        empresa: str,
    ) -> tuple[AuthResponse, str]:
        email_normalized = normalize_email(email)
        slug = self._unique_slug(slugify(empresa))

        try:
            tenant = self.db.execute(
                text(
                    """
                    INSERT INTO tenants (nome, slug, plano, ativo)
                    VALUES (:nome, :slug, 'trial', true)
                    RETURNING id, nome, slug, plano, ativo
                    """
                ),
                {"nome": empresa, "slug": slug},
            ).mappings().one()

            user = self.db.execute(
                text(
                    """
                    INSERT INTO users (nome, email_normalized, senha_hash, ativo)
                    VALUES (:nome, :email, :senha_hash, true)
                    RETURNING id, nome, email_normalized
                    """
                ),
                {
                    "nome": nome,
                    "email": email_normalized,
                    "senha_hash": hash_password(senha),
                },
            ).mappings().one()

            membership = self.db.execute(
                text(
                    """
                    INSERT INTO memberships (user_id, tenant_id, role, default_module, status)
                    VALUES (:user_id, :tenant_id, 'owner', 'sales', 'active')
                    RETURNING id, role, default_module
                    """
                ),
                {"user_id": str(user["id"]), "tenant_id": str(tenant["id"])},
            ).mappings().one()

            for module_key in DEFAULT_OWNER_MODULES:
                self.db.execute(
                    text(
                        """
                        INSERT INTO membership_modules
                          (membership_id, module_key, granted_by_membership_id)
                        VALUES (:membership_id, :module_key, :granted_by)
                        """
                    ),
                    {
                        "membership_id": str(membership["id"]),
                        "module_key": module_key,
                        "granted_by": str(membership["id"]),
                    },
                )

            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(status_code=409, detail="Email ou empresa ja cadastrados") from exc
        except Exception:
            self.db.rollback()
            raise

        context = AuthContext(
            user_id=str(user["id"]),
            tenant_id=str(tenant["id"]),
            membership_id=str(membership["id"]),
            nome=user["nome"],
            email=user["email_normalized"],
            role=membership["role"],
            tenant_nome=tenant["nome"],
            tenant_slug=tenant["slug"],
            tenant_plano=tenant["plano"],
            tenant_ativo=tenant["ativo"],
            modules=DEFAULT_OWNER_MODULES,
            default_module=membership["default_module"],
        )
        return self._auth_response(context)

    def login(self, *, email: str, senha: str) -> tuple[AuthResponse, str]:
        email_normalized = normalize_email(email)
        user = self.db.execute(
            text(
                """
                SELECT id, nome, email_normalized, senha_hash, ativo
                FROM users
                WHERE email_normalized = :email
                """
            ),
            {"email": email_normalized},
        ).mappings().first()

        password_hash = user["senha_hash"] if user else DUMMY_PASSWORD_HASH
        password_valid = verify_password(senha, password_hash)

        if not user or not user["ativo"] or not password_valid:
            raise HTTPException(status_code=401, detail="Email ou senha incorretos")

        context = self._default_context_for_user(str(user["id"]))
        if context is None:
            raise HTTPException(status_code=403, detail="Usuario sem tenant ativo")

        self.db.execute(
            text("UPDATE memberships SET last_access_at = NOW() WHERE id = :membership_id"),
            {"membership_id": context.membership_id},
        )
        self.db.commit()
        return self._auth_response(context)

    def me(self, membership_id: str) -> MeResponse:
        context = self._context_for_membership(membership_id)
        memberships = self._memberships_for_user(context.user_id)
        return MeResponse(
            user=self._user_response(context),
            tenant=self._tenant_response(context),
            memberships=memberships,
        )

    def refresh(self, refresh_token: str) -> tuple[AuthResponse, str]:
        try:
            record, new_refresh_token = self.refresh_store.rotate(refresh_token)
        except (RefreshTokenNotFoundError, RefreshTokenReuseError) as exc:
            raise HTTPException(status_code=401, detail="Refresh token invalido") from exc

        context = self._context_for_membership(record.membership_id)
        response = self._access_response(context)
        return response, new_refresh_token

    def logout(self, refresh_token: str | None) -> None:
        if refresh_token:
            self.refresh_store.revoke(refresh_token)

    def issue_for_membership(self, membership_id: str) -> tuple[AuthResponse, str]:
        return self._auth_response(self._context_for_membership(membership_id))

    def switch_tenant(
        self,
        *,
        user_id: str,
        membership_id: str,
        current_refresh_token: str | None = None,
    ) -> tuple[AuthResponse, str]:
        context = self._context_for_membership(membership_id)
        if context.user_id != user_id:
            raise HTTPException(status_code=403, detail="Membership nao pertence ao usuario")
        self.db.execute(
            text("UPDATE memberships SET last_access_at = NOW() WHERE id = :membership_id"),
            {"membership_id": membership_id},
        )
        self.db.commit()
        auth_response = self._auth_response(context)
        if current_refresh_token:
            self.refresh_store.revoke(current_refresh_token)
        return auth_response

    def forgot_password(self, *, email: str) -> str | None:
        email_normalized = normalize_email(email)
        row = self.db.execute(
            text("SELECT id FROM users WHERE email_normalized = :email AND ativo = true"),
            {"email": email_normalized},
        ).mappings().first()
        if not row:
            return None
        return self.password_reset_store.issue(user_id=str(row["id"]))

    def reset_password(self, *, token: str, senha: str) -> None:
        record = self.password_reset_store.consume(token)
        if record is None:
            raise HTTPException(status_code=400, detail="Token de reset invalido ou expirado")
        self.db.execute(
            text(
                """
                UPDATE users
                SET senha_hash = :senha_hash, updated_at = NOW()
                WHERE id = :user_id AND ativo = true
                """
            ),
            {"senha_hash": hash_password(senha), "user_id": record.user_id},
        )
        self.db.commit()
        self.refresh_store.revoke_user(record.user_id)

    def _auth_response(self, context: AuthContext) -> tuple[AuthResponse, str]:
        response = self._access_response(context)
        refresh_token = self.refresh_store.issue(
            user_id=context.user_id,
            membership_id=context.membership_id,
        )
        return response, refresh_token

    def _access_response(self, context: AuthContext) -> AuthResponse:
        access_token = create_access_token(
            user_id=context.user_id,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            role=context.role,
            modules=list(context.modules),
            jti=make_jti(),
        )
        return AuthResponse(
            access_token=access_token,
            token_type="bearer",
            user=self._user_response(context),
            tenant=self._tenant_response(context),
        )

    @staticmethod
    def _user_response(context: AuthContext) -> UserResponse:
        return UserResponse(
            id=context.user_id,
            tenant_id=context.tenant_id,
            nome=context.nome,
            email=context.email,
            avatar_url=None,
            role=context.role,
        )

    @staticmethod
    def _tenant_response(context: AuthContext) -> TenantResponse:
        return TenantResponse(
            id=context.tenant_id,
            nome=context.tenant_nome,
            slug=context.tenant_slug,
            plano=context.tenant_plano,
            ativo=context.tenant_ativo,
            modules=modules_payload(context.modules),
            default_module=context.default_module,
        )

    def _unique_slug(self, base_slug: str) -> str:
        slug = base_slug
        exists = self.db.execute(
            text("SELECT 1 FROM tenants WHERE slug = :slug"),
            {"slug": slug},
        ).first()
        if not exists:
            return slug
        return f"{base_slug}-{secrets.token_hex(3)}"

    def _default_context_for_user(self, user_id: str) -> AuthContext | None:
        row = self.db.execute(
            text(
                """
                SELECT m.id AS membership_id
                FROM memberships m
                JOIN tenants t ON t.id = m.tenant_id
                WHERE m.user_id = :user_id
                  AND m.status = 'active'
                  AND t.ativo = true
                ORDER BY m.last_access_at DESC NULLS LAST, m.created_at ASC
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        ).mappings().first()
        if not row:
            return None
        return self._context_for_membership(str(row["membership_id"]))

    def _context_for_membership(self, membership_id: str) -> AuthContext:
        row = self.db.execute(
            text(
                """
                SELECT
                  u.id AS user_id,
                  u.nome,
                  u.email_normalized,
                  m.id AS membership_id,
                  m.role,
                  m.default_module,
                  t.id AS tenant_id,
                  t.nome AS tenant_nome,
                  t.slug AS tenant_slug,
                  t.plano AS tenant_plano,
                  t.ativo AS tenant_ativo,
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
                GROUP BY u.id, m.id, t.id
                """
            ),
            {"membership_id": membership_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=403, detail="Membership nao encontrada ou inativa")

        modules = tuple(row["modules"] or ())
        return AuthContext(
            user_id=str(row["user_id"]),
            tenant_id=str(row["tenant_id"]),
            membership_id=str(row["membership_id"]),
            nome=row["nome"],
            email=row["email_normalized"],
            role=row["role"],
            tenant_nome=row["tenant_nome"],
            tenant_slug=row["tenant_slug"],
            tenant_plano=row["tenant_plano"],
            tenant_ativo=row["tenant_ativo"],
            modules=modules,
            default_module=row["default_module"],
        )

    def _memberships_for_user(self, user_id: str) -> list[MembershipResponse]:
        rows = self.db.execute(
            text(
                """
                SELECT
                  m.id,
                  m.tenant_id,
                  m.role,
                  m.default_module,
                  t.nome AS tenant_nome,
                  t.slug AS tenant_slug,
                  COALESCE(
                    array_agg(mm.module_key) FILTER (WHERE mm.module_key IS NOT NULL),
                    '{}'
                  ) AS modules
                FROM memberships m
                JOIN tenants t ON t.id = m.tenant_id
                LEFT JOIN membership_modules mm ON mm.membership_id = m.id
                WHERE m.user_id = :user_id
                  AND m.status = 'active'
                  AND t.ativo = true
                GROUP BY m.id, t.id
                ORDER BY t.nome ASC
                """
            ),
            {"user_id": user_id},
        ).mappings().all()

        return [
            MembershipResponse(
                id=str(row["id"]),
                tenant_id=str(row["tenant_id"]),
                tenant_nome=row["tenant_nome"],
                tenant_slug=row["tenant_slug"],
                role=row["role"],
                modules=[module_payload(module_key) for module_key in tuple(row["modules"] or ())],
                default_module=row["default_module"],
            )
            for row in rows
        ]
