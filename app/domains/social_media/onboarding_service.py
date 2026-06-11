import hashlib
import json
import logging
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.dependencies import CurrentMembership
from app.domains.jobs.job_service import JobQueueService, JobRecord
from app.integrations.phyllo import (
    PhylloClient,
    PhylloConfigurationError,
    PhylloProviderError,
)

SOCIAL_ONBOARDING_DIAGNOSE_JOB = "social.onboarding.diagnose"
SOCIAL_ONBOARDING_QUEUE = "worker-social-analysis"
PHYLLO_CONNECT_TIMEOUT_MINUTES = 30
logger = logging.getLogger(__name__)

PROVIDERS = {"instagram", "youtube", "x", "linkedin", "fake"}
OBJECTIVE_LABELS = {
    "grow_audience": "crescer audiencia",
    "sell_more": "vender mais",
    "authority": "melhorar autoridade",
    "content_ops": "organizar conteudo",
    "benchmarking": "analisar referencias",
}


class SocialOnboardingService:
    def __init__(
        self,
        db: Session,
        *,
        job_queue: JobQueueService,
        settings: Settings | None = None,
        phyllo_client: Any | None = None,
    ) -> None:
        self.db = db
        self.job_queue = job_queue
        self.settings = settings or get_settings()
        self.phyllo_client = phyllo_client or PhylloClient(self.settings)

    def get_current(self, *, current: CurrentMembership) -> dict[str, Any] | None:
        row = self.db.execute(
            text(
                """
                SELECT *
                FROM social_onboarding_sessions
                WHERE tenant_id = :tenant_id
                  AND status <> 'archived'
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """
            ),
            {"tenant_id": str(current.tenant_id)},
        ).mappings().first()
        if row is None:
            return None
        return self._with_references(dict(row))

    def create_session(
        self,
        *,
        current: CurrentMembership,
        objective: str,
    ) -> dict[str, Any]:
        self.db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant_id, 0))"),
            {"tenant_id": str(current.tenant_id)},
        )
        self.db.execute(
            text(
                """
                UPDATE social_onboarding_sessions
                SET status = 'archived',
                    updated_by_membership_id = :membership_id,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND status <> 'archived'
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "membership_id": str(current.membership_id),
            },
        )
        row = self.db.execute(
            text(
                """
                INSERT INTO social_onboarding_sessions (
                  tenant_id,
                  created_by_membership_id,
                  updated_by_membership_id,
                  objective,
                  status,
                  progress_steps
                )
                VALUES (
                  :tenant_id,
                  :membership_id,
                  :membership_id,
                  :objective,
                  'draft',
                  CAST(:progress_steps AS jsonb)
                )
                RETURNING *
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "membership_id": str(current.membership_id),
                "objective": objective,
                "progress_steps": json.dumps(_initial_progress()),
            },
        ).mappings().one()
        self.db.commit()
        return self._with_references(dict(row))

    def get_session(self, *, current: CurrentMembership, session_id: str) -> dict[str, Any]:
        row = self._get_session(current=current, session_id=session_id)
        return self._with_references(row)

    def update_session(
        self,
        *,
        current: CurrentMembership,
        session_id: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        if not patch:
            return self.get_session(current=current, session_id=session_id)

        row = self.db.execute(
            text(
                """
                UPDATE social_onboarding_sessions
                SET objective = COALESCE(:objective, objective),
                    updated_by_membership_id = :membership_id,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :session_id
                  AND status <> 'archived'
                RETURNING *
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "session_id": session_id,
                "membership_id": str(current.membership_id),
                "objective": patch.get("objective"),
            },
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Onboarding nao encontrado")
        self.db.commit()
        return self._with_references(dict(row))

    def connect_fake_account(
        self,
        *,
        current: CurrentMembership,
        session_id: str,
        provider: str,
        handle: str,
        display_name: str | None,
        profile_url: str | None,
        followers_count: int | None,
        posts_count: int | None,
        average_engagement_rate: float | None,
    ) -> tuple[dict[str, Any], JobRecord]:
        provider = _normalize_provider(provider)
        normalized_handle = _normalize_handle(handle)
        existing = self._get_session(current=current, session_id=session_id)
        if (
            existing.get("connection_mode") == "oauth"
            and existing.get("status") in {"connecting", "analyzing"}
        ):
            raise HTTPException(
                status_code=409,
                detail="Conexao real em andamento; aguarde ou crie um novo diagnostico",
            )
        profile_snapshot = {
            "provider": provider,
            "handle": normalized_handle,
            "display_name": display_name or normalized_handle,
            "profile_url": profile_url,
            "followers_count": followers_count or 0,
            "posts_count": posts_count or 0,
            "average_engagement_rate": average_engagement_rate or 0,
            "source": "fake_onboarding",
        }
        account_id = hashlib.sha256(f"{provider}:{normalized_handle}".encode()).hexdigest()[:32]

        row = self.db.execute(
            text(
                """
                UPDATE social_onboarding_sessions
                SET status = 'analyzing',
                    primary_provider = :provider,
                    connection_mode = 'simulated',
                    connected_account_id = :account_id,
                    connected_account_handle = :handle,
                    connected_account_name = :display_name,
                    profile_url = :profile_url,
                    profile_snapshot = CAST(:profile_snapshot AS jsonb),
                    progress_steps = CAST(:progress_steps AS jsonb),
                    analysis_started_at = NOW(),
                    analysis_completed_at = NULL,
                    analysis_report = NULL,
                    analysis_version = analysis_version + 1,
                    error_code = NULL,
                    error_message = NULL,
                    updated_by_membership_id = :membership_id,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :session_id
                  AND status <> 'archived'
                RETURNING *
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "session_id": session_id,
                "membership_id": str(current.membership_id),
                "provider": provider,
                "account_id": account_id,
                "handle": normalized_handle,
                "display_name": display_name or normalized_handle,
                "profile_url": profile_url,
                "profile_snapshot": json.dumps(profile_snapshot),
                "progress_steps": json.dumps(_analysis_progress()),
            },
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Onboarding nao encontrado")

        job = self._enqueue_diagnostic_job(
            current=current,
            session_id=session_id,
            analysis_version=int(row["analysis_version"]),
            commit=False,
        )
        self.db.commit()
        return self._with_references(dict(row)), job

    def create_phyllo_connect_token(
        self,
        *,
        current: CurrentMembership,
        session_id: str,
    ) -> dict[str, Any]:
        session = self._get_session(current=current, session_id=session_id)
        if session["status"] == "analyzing":
            raise HTTPException(status_code=409, detail="Diagnostico ja esta em andamento")

        phyllo_user = self._get_or_create_phyllo_user(current=current)
        products = self.settings.phyllo_products_list or ["IDENTITY"]
        token_payload = self._call_phyllo(
            lambda: self.phyllo_client.create_sdk_token(
                user_id=str(phyllo_user["phyllo_user_id"]),
                products=products,
            )
        )
        sdk_token = _extract_sdk_token(token_payload or {})
        if not sdk_token:
            raise HTTPException(status_code=502, detail="Phyllo nao retornou token do SDK")

        updated = self.db.execute(
            text(
                """
                UPDATE social_onboarding_sessions
                SET status = 'connecting',
                    primary_provider = 'instagram',
                    connection_mode = 'oauth',
                    connected_account_id = NULL,
                    connected_account_handle = NULL,
                    connected_account_name = NULL,
                    profile_url = NULL,
                    profile_snapshot = '{}'::jsonb,
                    analysis_report = NULL,
                    analysis_started_at = NULL,
                    analysis_completed_at = NULL,
                    progress_steps = CAST(:progress_steps AS jsonb),
                    error_code = NULL,
                    error_message = NULL,
                    updated_by_membership_id = :membership_id,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :session_id
                  AND status <> 'archived'
                RETURNING id
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "session_id": session_id,
                "membership_id": str(current.membership_id),
                "progress_steps": json.dumps(_connecting_progress()),
            },
        ).first()
        if updated is None:
            self.db.rollback()
            raise HTTPException(status_code=404, detail="Onboarding nao encontrado")
        self.db.commit()
        return {
            "user_id": str(phyllo_user["phyllo_user_id"]),
            "sdk_token": sdk_token,
            "environment": self.settings.phyllo_environment,
            "client_display_name": self.settings.phyllo_connect_display_name,
            "work_platform_id": self.settings.phyllo_instagram_work_platform_id,
            "products": products,
        }

    def complete_phyllo_connection(
        self,
        *,
        current: CurrentMembership,
        session_id: str,
        phyllo_user_id: str,
        account_id: str,
        work_platform_id: str | None,
    ) -> tuple[dict[str, Any], JobRecord]:
        session = self._get_session(current=current, session_id=session_id)
        if session.get("status") != "connecting" or session.get("connection_mode") != "oauth":
            raise HTTPException(status_code=409, detail="Conexao Phyllo nao esta em andamento")

        phyllo_user = self.db.execute(
            text(
                """
                SELECT *
                FROM social_phyllo_users
                WHERE tenant_id = :tenant_id
                  AND environment = :environment
                  AND phyllo_user_id = :phyllo_user_id
                  AND status = 'active'
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "environment": self.settings.phyllo_environment,
                "phyllo_user_id": phyllo_user_id,
            },
        ).mappings().first()
        if phyllo_user is None:
            raise HTTPException(status_code=404, detail="Usuario Phyllo nao encontrado")

        self.db.rollback()
        account, profile = self._fetch_phyllo_account_payload(account_id=account_id)
        return self._complete_phyllo_connection_from_payload(
            tenant_id=str(current.tenant_id),
            membership_id=str(current.membership_id),
            session_id=session_id,
            phyllo_user_id=phyllo_user_id,
            account_id=account_id,
            work_platform_id=work_platform_id,
            account=account,
            profile=profile,
        )

    def _fetch_phyllo_account_payload(
        self,
        *,
        account_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        account_payload = self._call_phyllo(lambda: self.phyllo_client.get_account(account_id))
        account = _unwrap_data(account_payload or {})
        profiles = self._call_phyllo(
            lambda: self.phyllo_client.list_profiles(account_id=account_id)
        )
        profile = _unwrap_data(profiles[0]) if profiles else {}
        return account, profile

    def _complete_phyllo_connection_from_payload(
        self,
        *,
        tenant_id: str,
        membership_id: str | None,
        session_id: str,
        phyllo_user_id: str,
        account_id: str,
        work_platform_id: str | None,
        account: dict[str, Any],
        profile: dict[str, Any],
    ) -> tuple[dict[str, Any], JobRecord]:
        payload_user_id = _phyllo_account_owner_id(account, profile)
        if not payload_user_id or payload_user_id != phyllo_user_id:
            raise HTTPException(status_code=409, detail="Conta Phyllo nao pertence ao usuario")

        phyllo_account_id = str(account.get("id") or account_id)
        effective_work_platform_id = (
            work_platform_id
            or _pick_text(account, profile, keys=("work_platform_id", "platform_id"))
            or self.settings.phyllo_instagram_work_platform_id
        )
        provider = _provider_from_phyllo(
            work_platform_id=effective_work_platform_id,
            account=account,
            instagram_work_platform_id=self.settings.phyllo_instagram_work_platform_id,
        )
        handle = _normalize_handle(
            _pick_text(
                account,
                profile,
                keys=("platform_username", "username", "handle", "screen_name"),
            )
            or phyllo_account_id[:12]
        )
        display_name = (
            _pick_text(
                account,
                profile,
                keys=("full_name", "display_name", "name", "platform_profile_name"),
            )
            or handle
        )
        profile_url = _pick_text(account, profile, keys=("profile_url", "url", "account_url"))
        phyllo_profile_id = _pick_text(profile, keys=("id", "profile_id"))
        account_status = _pick_text(
            account,
            profile,
            keys=("status", "account_status", "connection_status"),
        )
        snapshot = _build_phyllo_profile_snapshot(
            provider=provider,
            handle=handle,
            display_name=display_name,
            profile_url=profile_url,
            phyllo_user_id=phyllo_user_id,
            phyllo_account_id=phyllo_account_id,
            phyllo_profile_id=phyllo_profile_id,
            work_platform_id=effective_work_platform_id,
            account_status=account_status,
            account=account,
            profile=profile,
        )

        self.db.execute(
            text(
                """
                INSERT INTO social_phyllo_accounts (
                  tenant_id,
                  onboarding_session_id,
                  environment,
                  phyllo_user_id,
                  phyllo_account_id,
                  phyllo_profile_id,
                  work_platform_id,
                  provider,
                  handle,
                  display_name,
                  profile_url,
                  account_status,
                  raw_account,
                  raw_profile,
                  last_synced_at
                )
                VALUES (
                  :tenant_id,
                  :session_id,
                  :environment,
                  :phyllo_user_id,
                  :phyllo_account_id,
                  :phyllo_profile_id,
                  :work_platform_id,
                  :provider,
                  :handle,
                  :display_name,
                  :profile_url,
                  :account_status,
                  CAST(:raw_account AS jsonb),
                  CAST(:raw_profile AS jsonb),
                  NOW()
                )
                ON CONFLICT (
                  tenant_id,
                  environment,
                  phyllo_account_id
                )
                DO UPDATE SET
                  onboarding_session_id = EXCLUDED.onboarding_session_id,
                  phyllo_profile_id = EXCLUDED.phyllo_profile_id,
                  work_platform_id = EXCLUDED.work_platform_id,
                  provider = EXCLUDED.provider,
                  handle = EXCLUDED.handle,
                  display_name = EXCLUDED.display_name,
                  profile_url = EXCLUDED.profile_url,
                  account_status = EXCLUDED.account_status,
                  raw_account = EXCLUDED.raw_account,
                  raw_profile = EXCLUDED.raw_profile,
                  last_synced_at = NOW(),
                  updated_at = NOW()
                """
            ),
            {
                "tenant_id": tenant_id,
                "session_id": session_id,
                "environment": self.settings.phyllo_environment,
                "phyllo_user_id": phyllo_user_id,
                "phyllo_account_id": phyllo_account_id,
                "phyllo_profile_id": phyllo_profile_id,
                "work_platform_id": effective_work_platform_id,
                "provider": provider,
                "handle": handle,
                "display_name": display_name,
                "profile_url": profile_url,
                "account_status": account_status,
                "raw_account": json.dumps(account),
                "raw_profile": json.dumps(profile),
            },
        )
        row = self.db.execute(
            text(
                """
                UPDATE social_onboarding_sessions
                SET status = 'analyzing',
                    primary_provider = :provider,
                    connection_mode = 'oauth',
                    connected_account_id = :account_id,
                    connected_account_handle = :handle,
                    connected_account_name = :display_name,
                    profile_url = :profile_url,
                    profile_snapshot = CAST(:profile_snapshot AS jsonb),
                    progress_steps = CAST(:progress_steps AS jsonb),
                    analysis_started_at = NOW(),
                    analysis_completed_at = NULL,
                    analysis_report = NULL,
                    analysis_version = analysis_version + 1,
                    error_code = NULL,
                    error_message = NULL,
                    updated_by_membership_id = :membership_id,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :session_id
                  AND status = 'connecting'
                  AND connection_mode = 'oauth'
                RETURNING *
                """
            ),
            {
                "tenant_id": tenant_id,
                "session_id": session_id,
                "membership_id": membership_id,
                "provider": provider,
                "account_id": phyllo_account_id,
                "handle": handle,
                "display_name": display_name,
                "profile_url": profile_url,
                "profile_snapshot": json.dumps(snapshot),
                "progress_steps": json.dumps(_analysis_progress()),
            },
        ).mappings().first()
        if row is None:
            self.db.rollback()
            raise HTTPException(status_code=409, detail="Conexao Phyllo ja processada")

        job = self._enqueue_diagnostic_job_for_ids(
            tenant_id=tenant_id,
            membership_id=membership_id,
            session_id=session_id,
            analysis_version=int(row["analysis_version"]),
            commit=False,
        )
        self.db.commit()
        return self._with_references(dict(row)), job

    def add_reference(
        self,
        *,
        current: CurrentMembership,
        session_id: str,
        provider: str,
        handle: str,
        label: str | None,
        profile_url: str | None,
    ) -> dict[str, Any]:
        self._get_session(current=current, session_id=session_id)
        provider = _normalize_provider(provider)
        normalized_handle = _normalize_handle(handle)
        row = self.db.execute(
            text(
                """
                INSERT INTO social_reference_profiles (
                  tenant_id,
                  onboarding_session_id,
                  created_by_membership_id,
                  provider,
                  handle,
                  label,
                  profile_url,
                  metadata_json
                )
                VALUES (
                  :tenant_id,
                  :session_id,
                  :membership_id,
                  :provider,
                  :handle,
                  :label,
                  :profile_url,
                  '{}'::jsonb
                )
                ON CONFLICT (
                  tenant_id,
                  onboarding_session_id,
                  provider,
                  handle
                )
                DO UPDATE SET
                  label = EXCLUDED.label,
                  profile_url = EXCLUDED.profile_url,
                  status = 'active',
                  updated_at = NOW()
                RETURNING *
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "session_id": session_id,
                "membership_id": str(current.membership_id),
                "provider": provider,
                "handle": normalized_handle,
                "label": label,
                "profile_url": profile_url,
            },
        ).mappings().one()
        self.db.commit()
        return dict(row)

    def enqueue_diagnostic(
        self,
        *,
        current: CurrentMembership,
        session_id: str,
    ) -> tuple[dict[str, Any], JobRecord]:
        existing = self._get_session(current=current, session_id=session_id)
        if not _has_connected_profile(existing):
            raise HTTPException(status_code=400, detail="Conecte um perfil antes do diagnostico")
        if existing["status"] == "analyzing":
            raise HTTPException(status_code=409, detail="Diagnostico ja esta em andamento")

        row = self.db.execute(
            text(
                """
                UPDATE social_onboarding_sessions
                SET status = 'analyzing',
                    progress_steps = CAST(:progress_steps AS jsonb),
                    analysis_started_at = NOW(),
                    analysis_completed_at = NULL,
                    analysis_report = NULL,
                    analysis_version = analysis_version + 1,
                    error_code = NULL,
                    error_message = NULL,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :session_id
                  AND status <> 'archived'
                RETURNING *
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "session_id": session_id,
                "progress_steps": json.dumps(_analysis_progress()),
            },
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Onboarding nao encontrado")
        job = self._enqueue_diagnostic_job(
            current=current,
            session_id=session_id,
            analysis_version=int(row["analysis_version"]),
            commit=False,
        )
        self.db.commit()
        return self._with_references(dict(row)), job

    def run_diagnostic(
        self,
        *,
        tenant_id: str,
        session_id: str,
        analysis_version: int | None = None,
    ) -> dict[str, Any]:
        row = self.db.execute(
            text(
                """
                SELECT *
                FROM social_onboarding_sessions
                WHERE tenant_id = :tenant_id
                  AND id = :session_id
                  AND status <> 'archived'
                FOR UPDATE
                """
            ),
            {"tenant_id": tenant_id, "session_id": session_id},
        ).mappings().first()
        if row is None:
            archived = self.db.execute(
                text(
                    """
                    SELECT 1
                    FROM social_onboarding_sessions
                    WHERE tenant_id = :tenant_id
                      AND id = :session_id
                      AND status = 'archived'
                    """
                ),
                {"tenant_id": tenant_id, "session_id": session_id},
            ).first()
            if archived:
                return {
                    "session_id": session_id,
                    "skipped": True,
                    "status": "archived",
                    "reason": "session_archived",
                    "analysis_version": analysis_version,
                }
            raise ValueError("Onboarding nao encontrado")
        if analysis_version is not None and int(row["analysis_version"]) != analysis_version:
            return {
                "session_id": session_id,
                "skipped": True,
                "status": row["status"],
                "reason": "stale_analysis_version",
                "analysis_version": analysis_version,
                "current_analysis_version": int(row["analysis_version"]),
            }
        if not _has_connected_profile(dict(row)):
            raise ValueError("Perfil principal nao conectado")
        if row["status"] == "ready" and row["analysis_report"]:
            return {"session_id": session_id, "skipped": True, "status": "ready"}
        if row["status"] != "analyzing":
            return {
                "session_id": session_id,
                "skipped": True,
                "status": row["status"],
                "reason": "session_not_analyzing",
                "analysis_version": analysis_version,
            }

        self.db.rollback()
        analysis_session = self._refresh_oauth_analysis_snapshot(dict(row))
        references = self._list_references(tenant_id=tenant_id, session_id=session_id)
        report = _build_report(analysis_session, references)
        progress = _ready_progress()
        updated = self.db.execute(
            text(
                """
                UPDATE social_onboarding_sessions
                SET status = 'ready',
                    profile_snapshot = CAST(:profile_snapshot AS jsonb),
                    analysis_report = CAST(:analysis_report AS jsonb),
                    progress_steps = CAST(:progress_steps AS jsonb),
                    analysis_completed_at = NOW(),
                    error_code = NULL,
                    error_message = NULL,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :session_id
                  AND status <> 'archived'
                  AND status = 'analyzing'
                  AND analysis_version = :analysis_version
                RETURNING *
                """
            ),
            {
                "tenant_id": tenant_id,
                "session_id": session_id,
                "analysis_version": int(row["analysis_version"]),
                "profile_snapshot": json.dumps(analysis_session.get("profile_snapshot") or {}),
                "analysis_report": json.dumps(report),
                "progress_steps": json.dumps(progress),
            },
        ).mappings().first()
        if updated is None:
            return {
                "session_id": session_id,
                "skipped": True,
                "status": "unknown",
                "reason": "session_not_updateable",
                "analysis_version": analysis_version,
            }
        self.db.commit()
        return {"session_id": session_id, "status": "ready"}

    def _refresh_oauth_analysis_snapshot(self, session: dict[str, Any]) -> dict[str, Any]:
        if session.get("connection_mode") != "oauth":
            return session

        snapshot = dict(session.get("profile_snapshot") or {})
        account_id = str(
            snapshot.get("phyllo_account_id") or session.get("connected_account_id") or ""
        )
        if not account_id:
            return session

        account, profile = self._fetch_phyllo_account_payload(account_id=account_id)
        contents = self._call_phyllo(
            lambda: self.phyllo_client.list_contents(account_id=account_id)
        )

        provider = str(snapshot.get("provider") or session.get("primary_provider") or "instagram")
        handle = str(
            snapshot.get("handle") or session.get("connected_account_handle") or account_id[:12]
        )
        display_name = str(
            snapshot.get("display_name") or session.get("connected_account_name") or handle
        )
        profile_url = (
            str(snapshot.get("profile_url"))
            if snapshot.get("profile_url")
            else _pick_text(account, profile, keys=("profile_url", "url", "account_url"))
        )
        phyllo_profile_id = (
            str(snapshot.get("phyllo_profile_id"))
            if snapshot.get("phyllo_profile_id")
            else _pick_text(profile, keys=("id", "profile_id"))
        )
        work_platform_id = (
            str(snapshot.get("work_platform_id"))
            if snapshot.get("work_platform_id")
            else _pick_text(account, profile, keys=("work_platform_id", "platform_id"))
        )
        account_status = _pick_text(
            account,
            profile,
            keys=("status", "account_status", "connection_status"),
        )
        refreshed_snapshot = _build_phyllo_profile_snapshot(
            provider=provider,
            handle=handle,
            display_name=display_name,
            profile_url=profile_url,
            phyllo_user_id=str(snapshot.get("phyllo_user_id") or ""),
            phyllo_account_id=account_id,
            phyllo_profile_id=phyllo_profile_id,
            work_platform_id=work_platform_id,
            account_status=account_status,
            account=account,
            profile=profile,
        )
        content_summary = _summarize_phyllo_contents(
            contents,
            followers_count=int(refreshed_snapshot.get("followers_count") or 0),
        )
        refreshed_snapshot.update(content_summary)

        self.db.execute(
            text(
                """
                UPDATE social_phyllo_accounts
                SET raw_account = CAST(:raw_account AS jsonb),
                    raw_profile = CAST(:raw_profile AS jsonb),
                    account_status = :account_status,
                    last_synced_at = NOW(),
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND environment = :environment
                  AND phyllo_account_id = :phyllo_account_id
                """
            ),
            {
                "tenant_id": str(session["tenant_id"]),
                "environment": self.settings.phyllo_environment,
                "phyllo_account_id": account_id,
                "account_status": account_status,
                "raw_account": json.dumps(account),
                "raw_profile": json.dumps(profile),
            },
        )
        self.db.commit()

        session["profile_snapshot"] = refreshed_snapshot
        return session

    def reconcile_abandoned_analyses(
        self,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = self.db.execute(
            text(
                """
                WITH stale_sessions AS (
                  SELECT s.id
                  FROM social_onboarding_sessions s
                  JOIN jobs j
                    ON j.tenant_id = s.tenant_id
                   AND j.job_type = :job_type
                   AND j.payload ->> 'session_id' = s.id::text
                   AND (j.payload ->> 'analysis_version')::integer = s.analysis_version
                  WHERE s.status = 'analyzing'
                    AND j.status = 'dead_letter'
                  ORDER BY COALESCE(j.updated_at, j.created_at) ASC, s.id ASC
                  FOR UPDATE SKIP LOCKED
                  LIMIT :limit
                )
                UPDATE social_onboarding_sessions s
                SET status = 'failed',
                    error_code = 'analysis_abandoned',
                    error_message = 'Social onboarding analysis timed out before worker completion',
                    analysis_completed_at = NOW(),
                    updated_at = NOW()
                FROM stale_sessions
                WHERE s.id = stale_sessions.id
                RETURNING s.*
                """
            ),
            {
                "job_type": SOCIAL_ONBOARDING_DIAGNOSE_JOB,
                "limit": max(1, limit),
            },
        ).mappings().all()
        self.db.commit()
        return [dict(row) for row in rows]

    def reconcile_phyllo_connecting_sessions(
        self,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        candidates = self.db.execute(
            text(
                """
                SELECT
                  s.id AS session_id,
                  s.tenant_id,
                  COALESCE(s.updated_by_membership_id, s.created_by_membership_id)
                    AS membership_id,
                  s.updated_at,
                  u.phyllo_user_id
                FROM social_onboarding_sessions s
                JOIN social_phyllo_users u
                  ON u.tenant_id = s.tenant_id
                 AND u.environment = :environment
                 AND u.status = 'active'
                WHERE s.status = 'connecting'
                  AND s.connection_mode = 'oauth'
                  AND s.status <> 'archived'
                ORDER BY s.updated_at ASC, s.id ASC
                LIMIT :limit
                """
            ),
            {
                "environment": self.settings.phyllo_environment,
                "limit": max(1, limit),
            },
        ).mappings().all()
        self.db.rollback()

        reconciled: list[dict[str, Any]] = []
        for candidate in candidates:
            tenant_id = str(candidate["tenant_id"])
            session_id = str(candidate["session_id"])
            phyllo_user_id = str(candidate["phyllo_user_id"])
            try:
                accounts = self._call_phyllo(
                    lambda phyllo_user_id=phyllo_user_id: self.phyllo_client.list_accounts(
                        user_id=phyllo_user_id
                    )
                )
                account_id = _preferred_connected_account_id(
                    accounts,
                    instagram_work_platform_id=self.settings.phyllo_instagram_work_platform_id,
                )
                if account_id:
                    account, profile = self._fetch_phyllo_account_payload(account_id=account_id)
                    try:
                        session, job = self._complete_phyllo_connection_from_payload(
                            tenant_id=tenant_id,
                            membership_id=(
                                str(candidate["membership_id"])
                                if candidate["membership_id"]
                                else None
                            ),
                            session_id=session_id,
                            phyllo_user_id=phyllo_user_id,
                            account_id=account_id,
                            work_platform_id=None,
                            account=account,
                            profile=profile,
                        )
                    except HTTPException as exc:
                        if exc.status_code == 409 and exc.detail == "Conexao Phyllo ja processada":
                            continue
                        ownership_error = exc.detail == "Conta Phyllo nao pertence ao usuario"
                        if exc.status_code != 409 or not ownership_error:
                            raise
                        failed = self._mark_phyllo_connection_failed(
                            tenant_id=tenant_id,
                            session_id=session_id,
                            error_code="phyllo_account_owner_mismatch",
                            error_message="Phyllo account ownership could not be verified",
                        )
                        if failed:
                            reconciled.append(
                                {
                                    "session_id": session_id,
                                    "status": "failed",
                                    "reason": "phyllo_account_owner_mismatch",
                                }
                            )
                        continue
                    reconciled.append(
                        {
                            "session_id": str(session["id"]),
                            "status": session["status"],
                            "job_id": str(job.id),
                        }
                    )
                    continue

                expired = self.db.execute(
                    text(
                        """
                        UPDATE social_onboarding_sessions
                        SET status = 'failed',
                            error_code = 'phyllo_connection_timeout',
                            error_message = 'Phyllo connection was not completed in time',
                            updated_at = NOW()
                        WHERE tenant_id = :tenant_id
                          AND id = :session_id
                          AND status = 'connecting'
                          AND connection_mode = 'oauth'
                          AND updated_at < NOW() - (:timeout_minutes * INTERVAL '1 minute')
                        RETURNING *
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "session_id": session_id,
                        "timeout_minutes": PHYLLO_CONNECT_TIMEOUT_MINUTES,
                    },
                ).mappings().first()
                self.db.commit()
                if expired is not None:
                    reconciled.append(
                        {
                            "session_id": str(expired["id"]),
                            "status": "failed",
                            "reason": "phyllo_connection_timeout",
                        }
                    )
            except Exception:
                logger.warning(
                    "phyllo_reconcile_candidate_failed",
                    extra={"tenant_id": tenant_id, "session_id": session_id},
                    exc_info=True,
                )
                self.db.rollback()
                continue

        return reconciled

    def _mark_phyllo_connection_failed(
        self,
        *,
        tenant_id: str,
        session_id: str,
        error_code: str,
        error_message: str,
    ) -> bool:
        failed = self.db.execute(
            text(
                """
                UPDATE social_onboarding_sessions
                SET status = 'failed',
                    error_code = :error_code,
                    error_message = :error_message,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :session_id
                  AND status = 'connecting'
                  AND connection_mode = 'oauth'
                RETURNING id
                """
            ),
            {
                "tenant_id": tenant_id,
                "session_id": session_id,
                "error_code": error_code,
                "error_message": error_message,
            },
        ).first()
        self.db.commit()
        return failed is not None

    def mark_diagnostic_failed(
        self,
        *,
        tenant_id: str,
        session_id: str,
        error_code: str,
        error_message: str,
        analysis_version: int,
    ) -> None:
        self.db.execute(
            text(
                """
                UPDATE social_onboarding_sessions
                SET status = 'failed',
                    error_code = :error_code,
                    error_message = :error_message,
                    analysis_completed_at = NOW(),
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :session_id
                  AND status = 'analyzing'
                  AND analysis_version = :analysis_version
                """
            ),
            {
                "tenant_id": tenant_id,
                "session_id": session_id,
                "analysis_version": analysis_version,
                "error_code": error_code[:120],
                "error_message": error_message[:2000],
            },
        )
        self.db.commit()

    def _enqueue_diagnostic_job(
        self,
        *,
        current: CurrentMembership,
        session_id: str,
        analysis_version: int,
        commit: bool,
    ) -> JobRecord:
        return self._enqueue_diagnostic_job_for_ids(
            tenant_id=str(current.tenant_id),
            membership_id=str(current.membership_id),
            session_id=session_id,
            analysis_version=analysis_version,
            commit=commit,
        )

    def _enqueue_diagnostic_job_for_ids(
        self,
        *,
        tenant_id: str,
        membership_id: str | None,
        session_id: str,
        analysis_version: int,
        commit: bool,
    ) -> JobRecord:
        return self.job_queue.enqueue_job(
            tenant_id=tenant_id,
            membership_id=membership_id,
            job_type=SOCIAL_ONBOARDING_DIAGNOSE_JOB,
            queue_name=SOCIAL_ONBOARDING_QUEUE,
            idempotency_key=f"social.onboarding.diagnose:{session_id}:v{analysis_version}",
            payload={"session_id": session_id, "analysis_version": analysis_version},
            max_attempts=3,
            commit=commit,
        )

    def _get_or_create_phyllo_user(self, *, current: CurrentMembership) -> dict[str, Any]:
        environment = self.settings.phyllo_environment
        existing = self.db.execute(
            text(
                """
                SELECT *
                FROM social_phyllo_users
                WHERE tenant_id = :tenant_id
                  AND environment = :environment
                  AND status = 'active'
                """
            ),
            {"tenant_id": str(current.tenant_id), "environment": environment},
        ).mappings().first()
        if existing is not None:
            self.db.rollback()
            return dict(existing)

        self.db.rollback()
        external_id = f"labby:tenant:{current.tenant_id}:social-onboarding"
        remote_user = self._call_phyllo(
            lambda: self.phyllo_client.get_user_by_external_id(external_id)
        )
        if remote_user is None:
            remote_user = self._call_phyllo(
                lambda: self.phyllo_client.create_user(
                    name=current.nome or current.email,
                    external_id=external_id,
                )
            )
        phyllo_user_id = _pick_text(remote_user or {}, keys=("id", "user_id"))
        if not phyllo_user_id:
            raise HTTPException(status_code=502, detail="Phyllo nao retornou user_id")

        self.db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"phyllo:{environment}:{current.tenant_id}"},
        )
        existing = self.db.execute(
            text(
                """
                SELECT *
                FROM social_phyllo_users
                WHERE tenant_id = :tenant_id
                  AND environment = :environment
                  AND status = 'active'
                """
            ),
            {"tenant_id": str(current.tenant_id), "environment": environment},
        ).mappings().first()
        if existing is not None:
            self.db.commit()
            return dict(existing)

        row = self.db.execute(
            text(
                """
                INSERT INTO social_phyllo_users (
                  tenant_id,
                  created_by_membership_id,
                  environment,
                  phyllo_user_id,
                  external_id,
                  metadata_json
                )
                VALUES (
                  :tenant_id,
                  :membership_id,
                  :environment,
                  :phyllo_user_id,
                  :external_id,
                  CAST(:metadata_json AS jsonb)
                )
                ON CONFLICT (tenant_id, environment)
                DO UPDATE SET
                  phyllo_user_id = EXCLUDED.phyllo_user_id,
                  external_id = EXCLUDED.external_id,
                  status = 'active',
                  metadata_json = EXCLUDED.metadata_json,
                  updated_at = NOW()
                RETURNING *
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "membership_id": str(current.membership_id),
                "environment": environment,
                "phyllo_user_id": phyllo_user_id,
                "external_id": external_id,
                "metadata_json": json.dumps(remote_user or {}),
            },
        ).mappings().one()
        self.db.commit()
        return dict(row)

    def _call_phyllo(self, operation):
        try:
            return operation()
        except PhylloConfigurationError as exc:
            self.db.rollback()
            raise HTTPException(status_code=503, detail="Phyllo nao configurado") from exc
        except PhylloProviderError as exc:
            self.db.rollback()
            logger.warning("phyllo_provider_error", exc_info=True)
            raise HTTPException(status_code=502, detail="Falha ao comunicar com a Phyllo") from exc

    def _get_session(self, *, current: CurrentMembership, session_id: str) -> dict[str, Any]:
        row = self.db.execute(
            text(
                """
                SELECT *
                FROM social_onboarding_sessions
                WHERE tenant_id = :tenant_id
                  AND id = :session_id
                  AND status <> 'archived'
                """
            ),
            {"tenant_id": str(current.tenant_id), "session_id": session_id},
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Onboarding nao encontrado")
        return dict(row)

    def _with_references(self, row: dict[str, Any]) -> dict[str, Any]:
        row["references"] = self._list_references(
            tenant_id=str(row["tenant_id"]),
            session_id=str(row["id"]),
        )
        return row

    def _list_references(self, *, tenant_id: str, session_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            text(
                """
                SELECT *
                FROM social_reference_profiles
                WHERE tenant_id = :tenant_id
                  AND onboarding_session_id = :session_id
                  AND status = 'active'
                ORDER BY created_at ASC, id ASC
                """
            ),
            {"tenant_id": tenant_id, "session_id": session_id},
        ).mappings().all()
        return [dict(row) for row in rows]


def _normalize_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized not in PROVIDERS:
        raise HTTPException(status_code=422, detail="Provider social invalido")
    return normalized


def _normalize_handle(handle: str) -> str:
    return handle.strip().lstrip("@").lower()


def _has_connected_profile(row: dict[str, Any]) -> bool:
    return bool(row.get("connected_account_id") and row.get("connected_account_handle"))


def _initial_progress() -> list[dict[str, str]]:
    return [
        {"key": "objective", "label": "Objetivo", "status": "done"},
        {"key": "connect", "label": "Conectar rede", "status": "pending"},
        {"key": "snapshot", "label": "Ler perfil", "status": "pending"},
        {"key": "analysis", "label": "Diagnostico", "status": "pending"},
        {"key": "report", "label": "Plano inicial", "status": "pending"},
    ]


def _connecting_progress() -> list[dict[str, str]]:
    return [
        {"key": "objective", "label": "Objetivo", "status": "done"},
        {"key": "connect", "label": "Conectar rede", "status": "running"},
        {"key": "snapshot", "label": "Ler perfil", "status": "pending"},
        {"key": "analysis", "label": "Diagnostico", "status": "pending"},
        {"key": "report", "label": "Plano inicial", "status": "pending"},
    ]


def _analysis_progress() -> list[dict[str, str]]:
    return [
        {"key": "objective", "label": "Objetivo", "status": "done"},
        {"key": "connect", "label": "Conectar rede", "status": "done"},
        {"key": "snapshot", "label": "Ler perfil", "status": "running"},
        {"key": "analysis", "label": "Diagnostico", "status": "pending"},
        {"key": "report", "label": "Plano inicial", "status": "pending"},
    ]


def _ready_progress() -> list[dict[str, str]]:
    return [
        {"key": "objective", "label": "Objetivo", "status": "done"},
        {"key": "connect", "label": "Conectar rede", "status": "done"},
        {"key": "snapshot", "label": "Ler perfil", "status": "done"},
        {"key": "analysis", "label": "Diagnostico", "status": "done"},
        {"key": "report", "label": "Plano inicial", "status": "done"},
    ]


def _extract_sdk_token(payload: dict[str, Any]) -> str | None:
    for key in ("sdk_token", "token", "access_token"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested = payload.get("data")
    if isinstance(nested, dict):
        return _extract_sdk_token(nested)
    return None


def _preferred_connected_account_id(
    accounts: list[dict[str, Any]],
    *,
    instagram_work_platform_id: str,
) -> str | None:
    connected_accounts = [account for account in accounts if _is_connected_phyllo_account(account)]
    instagram_accounts = [
        account
        for account in connected_accounts
        if _phyllo_work_platform_id(account) == instagram_work_platform_id
    ]
    for account in [*instagram_accounts, *connected_accounts]:
        account_id = _pick_text(account, keys=("id", "account_id"))
        if account_id:
            return account_id
    return None


def _is_connected_phyllo_account(account: dict[str, Any]) -> bool:
    status = _pick_text(account, keys=("status", "account_status", "connection_status"))
    return bool(status and status.strip().lower() == "connected")


def _phyllo_work_platform_id(account: dict[str, Any]) -> str | None:
    return _pick_text(account, keys=("work_platform_id", "platform_id"))


def _unwrap_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


def _phyllo_account_owner_id(*payloads: dict[str, Any]) -> str | None:
    for payload in payloads:
        user = payload.get("user")
        if isinstance(user, dict):
            owner_id = str(user.get("id") or "").strip()
            if owner_id:
                return owner_id
        owner_id = _pick_text(payload, keys=("user_id", "phyllo_user_id"))
        if owner_id:
            return owner_id
    return None


def _pick_text(*payloads: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for payload in payloads:
        value = _find_value(payload, keys)
        if value is None:
            continue
        text_value = str(value).strip()
        if text_value:
            return text_value
    return None


def _pick_number(
    *payloads: dict[str, Any],
    keys: tuple[str, ...],
    as_float: bool = False,
) -> float | int:
    for payload in payloads:
        value = _find_value(payload, keys)
        if value is None:
            continue
        try:
            number = float(str(value).replace("%", "").strip())
        except (TypeError, ValueError):
            continue
        return number if as_float else int(number)
    return 0.0 if as_float else 0


def _find_value(value: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        for key in keys:
            if key in value and value[key] not in (None, ""):
                return value[key]
        for item in value.values():
            found = _find_value(item, keys)
            if found not in (None, ""):
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_value(item, keys)
            if found not in (None, ""):
                return found
    return None


def _provider_from_phyllo(
    *,
    work_platform_id: str | None,
    account: dict[str, Any],
    instagram_work_platform_id: str,
) -> str:
    if work_platform_id and work_platform_id == instagram_work_platform_id:
        return "instagram"
    platform_text = " ".join(
        filter(
            None,
            [
                work_platform_id,
                _pick_text(account, keys=("work_platform_name", "platform_name", "name")),
            ],
        )
    ).lower()
    if "youtube" in platform_text:
        return "youtube"
    if "linkedin" in platform_text:
        return "linkedin"
    if "twitter" in platform_text or platform_text == "x":
        return "x"
    return "instagram"


def _build_phyllo_profile_snapshot(
    *,
    provider: str,
    handle: str,
    display_name: str,
    profile_url: str | None,
    phyllo_user_id: str,
    phyllo_account_id: str,
    phyllo_profile_id: str | None,
    work_platform_id: str | None,
    account_status: str | None,
    account: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    return {
        "provider": provider,
        "handle": handle,
        "display_name": display_name,
        "profile_url": profile_url,
        "profile_image_url": _pick_text(
            account,
            profile,
            keys=("profile_pic_url", "image_url", "profile_image_url", "avatar_url"),
        ),
        "bio": _pick_text(profile, account, keys=("introduction", "bio", "description")),
        "website": _pick_text(profile, account, keys=("website", "website_url", "link_url")),
        "followers_count": _pick_number(
            account,
            profile,
            keys=("followers_count", "follower_count", "followers", "subscribers_count"),
        ),
        "following_count": _pick_number(
            account,
            profile,
            keys=("following_count", "follows_count", "following"),
        ),
        "posts_count": _pick_number(
            account,
            profile,
            keys=("posts_count", "post_count", "media_count", "content_count"),
        ),
        "average_engagement_rate": _pick_number(
            account,
            profile,
            keys=("average_engagement_rate", "engagement_rate"),
            as_float=True,
        ),
        "is_business": _pick_bool(profile, account, keys=("is_business", "business_account")),
        "is_verified": _pick_bool(profile, account, keys=("is_verified", "verified")),
        "source": "phyllo",
        "connection_mode": "oauth",
        "phyllo_user_id": phyllo_user_id,
        "phyllo_account_id": phyllo_account_id,
        "phyllo_profile_id": phyllo_profile_id,
        "work_platform_id": work_platform_id,
        "account_status": account_status,
        "identity_sync_status": _phyllo_product_status(account, "identity"),
        "engagement_sync_status": _phyllo_product_status(account, "engagement"),
        "engagement_last_sync_at": _phyllo_product_field(account, "engagement", "last_sync_at"),
        "engagement_data_available_from": _phyllo_product_field(
            account, "engagement", "data_available_from"
        ),
    }


def _phyllo_product_status(account: dict[str, Any], product: str) -> str | None:
    value = _phyllo_product_field(account, product, "status")
    return str(value).upper() if value else None


def _phyllo_product_field(account: dict[str, Any], product: str, field: str) -> Any:
    data = account.get("data")
    if not isinstance(data, dict):
        return None
    product_data = data.get(product)
    if not isinstance(product_data, dict):
        return None
    return product_data.get(field)


def _pick_bool(*payloads: dict[str, Any], keys: tuple[str, ...]) -> bool | None:
    for payload in payloads:
        value = _find_value(payload, keys)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "sim"}:
                return True
            if normalized in {"false", "0", "no", "nao", "não"}:
                return False
    return None


def _summarize_phyllo_contents(
    contents: list[dict[str, Any]],
    *,
    followers_count: int,
) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    totals = {
        "likes": 0,
        "comments": 0,
        "shares": 0,
        "saves": 0,
        "views": 0,
        "reach": 0,
        "impressions": 0,
        "profile_visits": 0,
        "followers_gained": 0,
    }
    type_counts: dict[str, int] = {}
    format_counts: dict[str, int] = {}

    for content in contents[:50]:
        item = _normalize_phyllo_content(content, followers_count=followers_count)
        normalized.append(item)
        type_counts[item["type"]] = type_counts.get(item["type"], 0) + 1
        format_counts[item["format"]] = format_counts.get(item["format"], 0) + 1
        metrics = item["metrics"]
        for key in totals:
            totals[key] += int(metrics.get(key) or 0)

    analyzed_count = len(normalized)
    total_interactions = totals["likes"] + totals["comments"] + totals["shares"] + totals["saves"]
    total_reach = totals["reach"] or totals["views"] or totals["impressions"]
    engagement_by_followers = (
        round((total_interactions / followers_count) * 100, 2) if followers_count else 0.0
    )
    engagement_by_reach = (
        round((total_interactions / total_reach) * 100, 2) if total_reach else 0.0
    )
    top_contents = sorted(normalized, key=lambda item: item["performance_score"], reverse=True)[:5]

    return {
        "content_items_count": analyzed_count,
        "content_type_counts": type_counts,
        "content_format_counts": format_counts,
        "content_metrics": {
            **totals,
            "interactions": total_interactions,
            "engagement_rate_by_followers": engagement_by_followers,
            "engagement_rate_by_reach": engagement_by_reach,
            "best_format": _top_count_key(format_counts),
            "best_type": _top_count_key(type_counts),
        },
        "top_contents": top_contents,
        "data_quality": {
            "profile_source": "phyllo",
            "contents_analyzed": analyzed_count,
            "has_real_profile": True,
            "has_real_engagement": analyzed_count > 0,
        },
    }


def _normalize_phyllo_content(content: dict[str, Any], *, followers_count: int) -> dict[str, Any]:
    engagement = content.get("engagement") if isinstance(content.get("engagement"), dict) else {}
    additional_info = (
        engagement.get("additional_info")
        if isinstance(engagement.get("additional_info"), dict)
        else {}
    )
    metrics = {
        "likes": _int_value(engagement.get("like_count")),
        "comments": _int_value(engagement.get("comment_count")),
        "shares": _int_value(engagement.get("share_count")),
        "saves": _int_value(engagement.get("save_count")),
        "views": _int_value(engagement.get("view_count")),
        "reach": _int_value(engagement.get("reach_organic_count"))
        + _int_value(engagement.get("reach_paid_count")),
        "impressions": _int_value(engagement.get("impression_organic_count"))
        + _int_value(engagement.get("impression_paid_count")),
        "profile_visits": _int_value(additional_info.get("profile_visits")),
        "followers_gained": _int_value(additional_info.get("followers_gained")),
    }
    interactions = metrics["likes"] + metrics["comments"] + metrics["shares"] + metrics["saves"]
    reach_base = metrics["reach"] or metrics["views"] or metrics["impressions"]
    performance_score = (
        metrics["likes"]
        + metrics["comments"] * 4
        + metrics["shares"] * 5
        + metrics["saves"] * 5
        + metrics["views"] * 0.02
        + metrics["reach"] * 0.03
    )
    content_type = str(content.get("type") or "UNKNOWN").upper()
    content_format = str(content.get("format") or "UNKNOWN").upper()
    return {
        "id": str(content.get("id") or ""),
        "external_id": str(content.get("external_id") or ""),
        "type": content_type,
        "format": content_format,
        "url": content.get("url"),
        "published_at": content.get("published_at") or content.get("platform_published_at"),
        "title": content.get("title") or content.get("description") or content.get("caption"),
        "metrics": metrics,
        "engagement_rate_by_followers": round((interactions / followers_count) * 100, 2)
        if followers_count
        else 0.0,
        "engagement_rate_by_reach": round((interactions / reach_base) * 100, 2)
        if reach_base
        else 0.0,
        "performance_score": round(performance_score, 2),
    }


def _int_value(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _top_count_key(values: dict[str, int]) -> str | None:
    if not values:
        return None
    return max(values.items(), key=lambda item: item[1])[0]


def _build_report(session: dict[str, Any], references: list[dict[str, Any]]) -> dict[str, Any]:
    objective = session.get("objective") or "grow_audience"
    snapshot = session.get("profile_snapshot") or {}
    handle = session.get("connected_account_handle") or snapshot.get("handle") or "perfil"
    followers = int(snapshot.get("followers_count") or 0)
    following = int(snapshot.get("following_count") or 0)
    posts = int(snapshot.get("posts_count") or 0)
    engagement = float(snapshot.get("average_engagement_rate") or 0)
    bio = str(snapshot.get("bio") or "").strip()
    website = str(snapshot.get("website") or "").strip()
    content_metrics = snapshot.get("content_metrics") or {}
    top_contents = snapshot.get("top_contents") or []
    contents_analyzed = int(snapshot.get("content_items_count") or 0)
    real_engagement = float(content_metrics.get("engagement_rate_by_reach") or 0) or float(
        content_metrics.get("engagement_rate_by_followers") or 0
    )
    effective_engagement = real_engagement or engagement
    reference_handles = [f"@{ref['handle']}" for ref in references[:5]]
    segment = _infer_segment(
        handle=handle,
        objective=objective,
        references=reference_handles,
        bio=bio,
        display_name=str(snapshot.get("display_name") or ""),
    )
    strength = min(
        100,
        34
        + min(followers // 180, 22)
        + min(posts // 12, 16)
        + (10 if bio else 0)
        + (8 if website else 0)
        + (5 if snapshot.get("is_business") else 0),
    )
    consistency = min(
        100,
        36
        + min(posts // 10, 18)
        + min(contents_analyzed * 4, 22)
        + (8 if content_metrics.get("best_format") else 0)
        + len(reference_handles) * 3,
    )
    benchmark_fit = min(100, 50 + len(reference_handles) * 8)
    engagement_score = min(100, 38 + int(effective_engagement * 7) + min(contents_analyzed * 3, 18))
    top_content_lines = _top_content_lines(top_contents)

    return {
        "headline": f"Diagnostico inicial de @{handle}",
        "objective": {
            "key": objective,
            "label": OBJECTIVE_LABELS.get(objective, "crescer audiencia"),
        },
        "segment": segment,
        "scores": {
            "profile_strength": strength,
            "content_consistency": consistency,
            "engagement_readiness": engagement_score,
            "benchmark_fit": benchmark_fit,
        },
        "profile": {
            "followers_count": followers,
            "following_count": following,
            "posts_count": posts,
            "bio": bio,
            "website": website,
            "is_business": snapshot.get("is_business"),
            "is_verified": snapshot.get("is_verified"),
        },
        "data_quality": {
            "source": snapshot.get("source") or "unknown",
            "identity_sync_status": snapshot.get("identity_sync_status"),
            "engagement_sync_status": snapshot.get("engagement_sync_status"),
            "contents_analyzed": contents_analyzed,
            "has_real_engagement": contents_analyzed > 0,
        },
        "content_metrics": content_metrics,
        "top_contents": top_contents,
        "audience": {
            "summary": (
                _audience_summary(segment_name=segment["name"], bio=bio)
            ),
            "likely_needs": [
                "clareza sobre promessa do perfil",
                "conteudo com motivo claro para salvar, compartilhar ou responder",
                "provas sociais conectadas a uma oferta ou proxima acao",
            ],
        },
        "content_pillars": [
            {"name": "Autoridade", "description": "Teses, bastidores e leitura de mercado."},
            {"name": "Educacao", "description": "Guias curtos, checklists e contexto acionavel."},
            {"name": "Prova social", "description": "Resultados, estudos de caso e antes/depois."},
            {"name": "Comunidade", "description": "Perguntas, enquetes, replies e objecoes reais."},
        ],
        "opportunities": [
            {
                "priority": "alta",
                "title": "Ajustar promessa do perfil",
                "description": _profile_opportunity(bio=bio, website=website),
            },
            {
                "priority": "media",
                "title": "Replicar os sinais dos melhores conteudos",
                "description": (
                    top_content_lines[0]
                    if top_content_lines
                    else "Ainda faltam posts sincronizados para identificar padroes vencedores."
                ),
            },
            {
                "priority": "media",
                "title": "Aumentar engajamento qualificado",
                "description": _engagement_opportunity(
                    content_metrics=content_metrics,
                    effective_engagement=effective_engagement,
                ),
            },
        ],
        "benchmarks": {
            "references": reference_handles,
            "insight": (
                "Referencias suficientes para calibrar tom e formatos."
                if reference_handles
                else "Adicione 3 a 5 referencias para calibrar melhor o diagnostico."
            ),
        },
        "next_actions": [
            "validar a promessa da bio contra o publico-alvo principal",
            "separar os 3 conteudos com maior reach/view para mapear formato e gancho",
            "criar calendario inicial de 7 dias com 2 testes de formato",
        ],
    }


def _infer_segment(
    *,
    handle: str,
    objective: str,
    references: list[str],
    bio: str = "",
    display_name: str = "",
) -> dict[str, Any]:
    text = " ".join([handle, objective, bio, display_name, *references]).lower()
    if any(token in text for token in ("cripto", "crypto", "bitcoin", "web3")):
        name = "Cripto, Web3 e ativos digitais"
    elif any(token in text for token in ("beauty", "moda", "estetica")):
        name = "Beleza, moda e lifestyle"
    elif any(token in text for token in ("imob", "realestate", "corretor")):
        name = "Mercado imobiliario"
    elif any(token in text for token in ("saas", "tech", "software", "ia", "ai")):
        name = "Tecnologia e SaaS"
    else:
        name = "Marca digital e conteudo de autoridade"
    return {
        "name": name,
        "confidence": 0.8 if bio or references else 0.58,
        "signals": ["handle", "bio", "nome publico", "objetivo declarado", "referencias"],
    }


def _audience_summary(*, segment_name: str, bio: str) -> str:
    if "cripto" in segment_name.lower():
        return (
            "Publico interessado em leitura de mercado, sinais de decisao e contexto "
            "sobre risco/oportunidade em ativos digitais."
        )
    if bio:
        return (
            "Publico atraido pela promessa explicita da bio e por conteudos que "
            "transformam autoridade em decisao pratica."
        )
    return (
        "Publico interessado em conteudo pratico, sinais de autoridade e provas "
        "sociais frequentes."
    )


def _profile_opportunity(*, bio: str, website: str) -> str:
    if not bio and not website:
        return "Bio e link principal ainda nao comunicam promessa, publico e proxima acao."
    if not website:
        return "A bio ja existe, mas falta um destino claro para transformar atencao em acao."
    if not bio:
        return "O link existe, mas a bio precisa explicar para quem e por que clicar."
    return "Bio e link existem; proximo passo e deixar a promessa mais especifica e mensuravel."


def _engagement_opportunity(
    *,
    content_metrics: dict[str, Any],
    effective_engagement: float,
) -> str:
    saves = int(content_metrics.get("saves") or 0)
    shares = int(content_metrics.get("shares") or 0)
    comments = int(content_metrics.get("comments") or 0)
    if not content_metrics:
        return "Sincronize conteudos recentes para medir saves, shares, comentarios e reach real."
    if saves + shares == 0:
        return "Criar conteudos mais salvaveis/compartilhaveis; hoje os sinais fortes estao baixos."
    if comments == 0:
        return "Adicionar perguntas, opinioes e CTAs de resposta para gerar conversa real."
    return (
        f"Manter testes em torno dos formatos que ja puxam "
        f"{effective_engagement:.2f}% de engajamento."
    )


def _top_content_lines(top_contents: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in top_contents[:3]:
        metrics = item.get("metrics") or {}
        label = " ".join(filter(None, [item.get("type"), item.get("format")])).strip()
        views = int(metrics.get("views") or 0)
        reach = int(metrics.get("reach") or 0)
        comments = int(metrics.get("comments") or 0)
        shares = int(metrics.get("shares") or 0)
        lines.append(
            f"{label or 'Conteudo'} com {views or reach} visualizacoes/alcance, "
            f"{comments} comentarios e {shares} compartilhamentos."
        )
    return lines
