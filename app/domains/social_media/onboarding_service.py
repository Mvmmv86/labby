import hashlib
import json
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
                    connection_mode = 'oauth',
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

        account_payload = self._call_phyllo(lambda: self.phyllo_client.get_account(account_id))
        account = _unwrap_data(account_payload or {})
        profiles = self._call_phyllo(
            lambda: self.phyllo_client.list_profiles(account_id=account_id)
        )
        profile = _unwrap_data(profiles[0]) if profiles else {}

        payload_user_id = _pick_text(account, profile, keys=("user_id", "phyllo_user_id"))
        if payload_user_id and payload_user_id != phyllo_user_id:
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
        snapshot = {
            "provider": provider,
            "handle": handle,
            "display_name": display_name,
            "profile_url": profile_url,
            "followers_count": _pick_number(
                account,
                profile,
                keys=("followers_count", "follower_count", "followers", "subscribers_count"),
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
            "source": "phyllo",
            "connection_mode": "oauth",
            "phyllo_user_id": phyllo_user_id,
            "phyllo_account_id": phyllo_account_id,
            "phyllo_profile_id": phyllo_profile_id,
            "work_platform_id": effective_work_platform_id,
            "account_status": account_status,
        }

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
                "tenant_id": str(current.tenant_id),
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
                  AND status <> 'archived'
                RETURNING *
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "session_id": session_id,
                "membership_id": str(current.membership_id),
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
            raise HTTPException(status_code=404, detail="Onboarding nao encontrado")

        job = self._enqueue_diagnostic_job(
            current=current,
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

        references = self._list_references(tenant_id=tenant_id, session_id=session_id)
        report = _build_report(dict(row), references)
        progress = _ready_progress()
        updated = self.db.execute(
            text(
                """
                UPDATE social_onboarding_sessions
                SET status = 'ready',
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
        return self.job_queue.enqueue_job(
            tenant_id=str(current.tenant_id),
            membership_id=str(current.membership_id),
            job_type=SOCIAL_ONBOARDING_DIAGNOSE_JOB,
            queue_name=SOCIAL_ONBOARDING_QUEUE,
            idempotency_key=f"social.onboarding.diagnose:{session_id}:v{analysis_version}",
            payload={"session_id": session_id, "analysis_version": analysis_version},
            max_attempts=3,
            commit=commit,
        )

    def _get_or_create_phyllo_user(self, *, current: CurrentMembership) -> dict[str, Any]:
        environment = self.settings.phyllo_environment
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
            return dict(existing)

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
        return dict(row)

    def _call_phyllo(self, operation):
        try:
            return operation()
        except PhylloConfigurationError as exc:
            self.db.rollback()
            raise HTTPException(status_code=503, detail="Phyllo nao configurado") from exc
        except PhylloProviderError as exc:
            self.db.rollback()
            raise HTTPException(status_code=502, detail=str(exc)) from exc

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


def _unwrap_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


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


def _build_report(session: dict[str, Any], references: list[dict[str, Any]]) -> dict[str, Any]:
    objective = session.get("objective") or "grow_audience"
    snapshot = session.get("profile_snapshot") or {}
    handle = session.get("connected_account_handle") or snapshot.get("handle") or "perfil"
    followers = int(snapshot.get("followers_count") or 0)
    posts = int(snapshot.get("posts_count") or 0)
    engagement = float(snapshot.get("average_engagement_rate") or 0)
    reference_handles = [f"@{ref['handle']}" for ref in references[:5]]
    segment = _infer_segment(handle=handle, objective=objective, references=reference_handles)
    strength = min(100, 44 + min(followers // 250, 22) + min(posts // 20, 18) + int(engagement * 4))
    consistency = min(100, 42 + min(posts // 12, 26) + len(reference_handles) * 4)
    benchmark_fit = min(100, 50 + len(reference_handles) * 8)

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
            "engagement_readiness": min(100, 48 + int(engagement * 10)),
            "benchmark_fit": benchmark_fit,
        },
        "audience": {
            "summary": (
                "Publico interessado em conteudo pratico, sinais de autoridade e "
                "provas sociais frequentes."
            ),
            "likely_needs": [
                "clareza sobre promessa do perfil",
                "conteudo comparavel e recorrente",
                "motivos para salvar, comentar e voltar",
            ],
        },
        "content_pillars": [
            {"name": "Autoridade", "description": "Provas, bastidores e opinioes fortes."},
            {"name": "Educacao", "description": "Guias curtos, checklists e contexto."},
            {"name": "Prova social", "description": "Resultados, casos e antes/depois."},
            {"name": "Comunidade", "description": "Perguntas, enquetes e respostas."},
        ],
        "opportunities": [
            {
                "priority": "alta",
                "title": "Ajustar promessa do perfil",
                "description": (
                    "Bio, destaques e posts fixados precisam comunicar o ganho principal."
                ),
            },
            {
                "priority": "media",
                "title": "Criar series recorrentes",
                "description": "Series reduzem custo de producao e aumentam reconhecimento.",
            },
            {
                "priority": "media",
                "title": "Comparar com referencias",
                "description": "Usar benchmarks para descobrir formatos com maior tracao.",
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
            "confirmar segmento e publico-alvo",
            "conectar mais uma rede para comparar consistencia",
            "gerar calendario inicial de 7 dias",
        ],
    }


def _infer_segment(*, handle: str, objective: str, references: list[str]) -> dict[str, Any]:
    text = " ".join([handle, objective, *references]).lower()
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
        "confidence": 0.72 if references else 0.58,
        "signals": ["handle", "objetivo declarado", "referencias informadas"],
    }
