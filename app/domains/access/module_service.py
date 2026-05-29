from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentMembership
from app.domains.identity.modules import ModuleAccess, module_payload, modules_payload
from app.schemas.modules import (
    CurrentModulesResponse,
    LabbyUserModule,
    UpdateUserModulesResponse,
    UserModulesResponse,
    UserModulesStats,
)

ADMIN_ROLES = {"owner", "admin"}


class ModuleService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def current_modules(self, current: CurrentMembership) -> CurrentModulesResponse:
        default_module = self._membership_default_module(str(current.membership_id))
        return CurrentModulesResponse(
            modules=modules_payload(current.modules),
            default_module=default_module,
        )

    def list_users(
        self,
        *,
        current: CurrentMembership,
        limit: int = 50,
        offset: int = 0,
        search: str | None = None,
    ) -> UserModulesResponse:
        self._require_admin(current)
        limit = min(max(limit, 1), 100)
        offset = max(offset, 0)

        search_filter = ""
        params: dict[str, object] = {
            "tenant_id": str(current.tenant_id),
            "limit": limit,
            "offset": offset,
        }
        if search:
            search_filter = "AND (u.nome ILIKE :search OR u.email_normalized ILIKE :search)"
            params["search"] = f"%{search.strip()}%"

        rows = self.db.execute(
            text(
                f"""
                SELECT
                  u.id,
                  u.nome,
                  u.email_normalized,
                  u.ativo,
                  m.role,
                  m.default_module,
                  m.updated_at,
                  COALESCE(
                    array_agg(mm.module_key) FILTER (WHERE mm.module_key IS NOT NULL),
                    '{{}}'
                  ) AS modules
                FROM memberships m
                JOIN users u ON u.id = m.user_id
                LEFT JOIN membership_modules mm ON mm.membership_id = m.id
                WHERE m.tenant_id = :tenant_id
                  AND m.status = 'active'
                  {search_filter}
                GROUP BY m.id, u.id
                ORDER BY m.created_at ASC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()

        total = self.db.execute(
            text(
                f"""
                SELECT COUNT(*) AS total
                FROM memberships m
                JOIN users u ON u.id = m.user_id
                WHERE m.tenant_id = :tenant_id
                  AND m.status = 'active'
                  {search_filter}
                """
            ),
            params,
        ).mappings().one()
        stats = self._stats(str(current.tenant_id))
        return UserModulesResponse(
            users=[self._user_module_response(row) for row in rows],
            total=int(total["total"] or 0),
            limit=limit,
            offset=offset,
            stats=stats,
        )

    def update_user_modules(
        self,
        *,
        current: CurrentMembership,
        user_id: str,
        module_keys: list[str],
        default_module: str | None,
        expected_updated_at: datetime | None,
    ) -> UpdateUserModulesResponse:
        self._require_admin(current)
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
                detail="Nao e permitido conceder modulo sem acesso",
            )

        target = self.db.execute(
            text(
                """
                SELECT m.id AS membership_id, m.role, m.updated_at
                FROM memberships m
                WHERE m.user_id = :user_id
                  AND m.tenant_id = :tenant_id
                  AND m.status = 'active'
                """
            ),
            {"user_id": user_id, "tenant_id": str(current.tenant_id)},
        ).mappings().first()
        if not target:
            raise HTTPException(status_code=404, detail="Usuario nao encontrado neste tenant")
        if target["role"] == "owner":
            raise HTTPException(status_code=403, detail="Acesso do owner nao pode ser alterado")

        if expected_updated_at and target["updated_at"] != expected_updated_at:
            raise HTTPException(status_code=409, detail="Acesso alterado por outra sessao")

        self.db.execute(
            text("DELETE FROM membership_modules WHERE membership_id = :membership_id"),
            {"membership_id": str(target["membership_id"])},
        )
        for module_key in access.modules:
            self.db.execute(
                text(
                    """
                    INSERT INTO membership_modules
                      (membership_id, module_key, granted_by_membership_id)
                    VALUES (:membership_id, :module_key, :granted_by)
                    """
                ),
                {
                    "membership_id": str(target["membership_id"]),
                    "module_key": module_key,
                    "granted_by": str(current.membership_id),
                },
            )

        updated = self.db.execute(
            text(
                """
                UPDATE memberships
                SET default_module = :default_module, updated_at = NOW()
                WHERE id = :membership_id
                RETURNING updated_at
                """
            ),
            {
                "membership_id": str(target["membership_id"]),
                "default_module": access.default_module,
            },
        ).mappings().one()
        self.db.commit()

        return UpdateUserModulesResponse(
            user_id=user_id,
            modules=modules_payload(access.modules),
            default_module=access.default_module,
            updated_at=updated["updated_at"],
        )

    def _membership_default_module(self, membership_id: str) -> str:
        row = self.db.execute(
            text("SELECT default_module FROM memberships WHERE id = :membership_id"),
            {"membership_id": membership_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=403, detail="Membership nao encontrada")
        return row["default_module"]

    def _stats(self, tenant_id: str) -> UserModulesStats:
        row = self.db.execute(
            text(
                """
                SELECT
                  COUNT(DISTINCT m.id) AS total,
                  COUNT(DISTINCT m.id) FILTER (WHERE mm.module_key = 'sales') AS sales,
                  COUNT(DISTINCT m.id) FILTER (WHERE mm.module_key = 'social_media') AS social_media
                FROM memberships m
                LEFT JOIN membership_modules mm ON mm.membership_id = m.id
                WHERE m.tenant_id = :tenant_id
                  AND m.status = 'active'
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().one()
        return UserModulesStats(
            total=int(row["total"] or 0),
            sales=int(row["sales"] or 0),
            social_media=int(row["social_media"] or 0),
        )

    @staticmethod
    def _user_module_response(row) -> LabbyUserModule:
        module_keys = tuple(row["modules"] or ())
        return LabbyUserModule(
            id=str(row["id"]),
            nome=row["nome"],
            email=row["email_normalized"],
            role=row["role"],
            ativo=row["ativo"],
            default_module=row["default_module"],
            updated_at=row["updated_at"],
            modules=[module_payload(module_key) for module_key in module_keys],
        )

    @staticmethod
    def _require_admin(current: CurrentMembership) -> None:
        if current.role not in ADMIN_ROLES:
            raise HTTPException(status_code=403, detail="Permissao insuficiente")
