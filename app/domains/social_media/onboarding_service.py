import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.dependencies import CurrentMembership
from app.core.rate_limit import (
    PublicRateLimiter,
    RateLimitUnavailable,
    RedisFixedWindowRateLimiter,
)
from app.domains.jobs.job_service import JobQueueService, JobRecord
from app.integrations.ai import (
    SOCIAL_SPECIALIST_ANALYSIS_VERSION,
    make_ai_specialist_analysis_client,
)
from app.integrations.apify import (
    ApifyClient,
    ApifyConfigurationError,
    ApifyProviderError,
)
from app.integrations.phyllo import (
    PhylloClient,
    PhylloConfigurationError,
    PhylloProviderError,
)

SOCIAL_ONBOARDING_DIAGNOSE_JOB = "social.onboarding.diagnose"
SOCIAL_ONBOARDING_SPECIALIST_JOB = "social.onboarding.specialist_analysis"
SOCIAL_REFERENCE_SYNC_JOB = "social.references.sync"
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
        apify_client: Any | None = None,
        specialist_ai_client: Any | None = None,
        rate_limiter: PublicRateLimiter | None = None,
    ) -> None:
        self.db = db
        self.job_queue = job_queue
        self.settings = settings or get_settings()
        self.phyllo_client = phyllo_client or PhylloClient(self.settings)
        self.apify_client = apify_client or ApifyClient(self.settings)
        self.specialist_ai_client = specialist_ai_client
        self.rate_limiter = rate_limiter

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
        can_sync_publicly = provider == "instagram"
        active_other_references = self.db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM social_reference_profiles
                WHERE tenant_id = :tenant_id
                  AND onboarding_session_id = :session_id
                  AND status = 'active'
                  AND NOT (provider = :provider AND handle = :handle)
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "session_id": session_id,
                "provider": provider,
                "handle": normalized_handle,
            },
        ).scalar_one()
        if int(active_other_references or 0) >= (
            self.settings.social_onboarding_max_public_references_per_session
        ):
            raise HTTPException(
                status_code=409,
                detail="Limite de referencias publicas atingido para este diagnostico",
            )
        if can_sync_publicly:
            self._enforce_public_reference_add_budget(
                tenant_id=str(current.tenant_id),
                provider=provider,
            )
        public_reference = self.db.execute(
            text(
                """
                INSERT INTO social_public_reference_profiles (
                  provider,
                  handle,
                  display_name,
                  profile_url,
                  source,
                  sync_status,
                  data_truth
                )
                VALUES (
                  :provider,
                  :handle,
                  NULL,
                  NULL,
                  'manual',
                  'manual_pending',
                  CAST(:data_truth AS jsonb)
                )
                ON CONFLICT (provider, handle)
                DO UPDATE SET
                  updated_at = NOW()
                RETURNING
                  id,
                  sync_status,
                  sync_generation,
                  last_synced_at,
                  next_sync_after,
                  data_truth
                """
            ),
            {
                "provider": provider,
                "handle": normalized_handle,
                "data_truth": json.dumps(_manual_reference_truth()),
            },
        ).mappings().one()
        sync_job: JobRecord | None = None
        effective_sync_status = public_reference["sync_status"] or "manual_pending"
        sync_generation = int(public_reference["sync_generation"] or 0)
        if can_sync_publicly and _public_reference_needs_sync(
            dict(public_reference),
            circuit_breaker_failures=self.settings.apify_public_reference_circuit_breaker_failures,
        ):
            self._enforce_public_reference_sync_budget(provider=provider)
            updated_public_reference = self.db.execute(
                text(
                    """
                    UPDATE social_public_reference_profiles
                    SET sync_status = 'pending',
                        sync_generation = sync_generation + 1,
                        updated_at = NOW()
                    WHERE id = :public_reference_profile_id
                      AND sync_status <> 'syncing'
                    RETURNING
                      id,
                      sync_status,
                      sync_generation,
                      last_synced_at,
                      next_sync_after,
                      data_truth
                    """
                ),
                {"public_reference_profile_id": str(public_reference["id"])},
            ).mappings().first()
            if updated_public_reference is not None:
                public_reference = updated_public_reference
                effective_sync_status = public_reference["sync_status"]
                sync_generation = int(public_reference["sync_generation"] or 0)
                sync_job = self._enqueue_public_reference_sync_job(
                    tenant_id=str(current.tenant_id),
                    membership_id=str(current.membership_id),
                    session_id=session_id,
                    public_reference_profile_id=str(public_reference["id"]),
                    provider=provider,
                    handle=normalized_handle,
                    sync_generation=sync_generation,
                    commit=False,
                )
            else:
                effective_sync_status = "syncing"
        row = self.db.execute(
            text(
                """
                INSERT INTO social_reference_profiles (
                  tenant_id,
                  onboarding_session_id,
                  public_reference_profile_id,
                  created_by_membership_id,
                  provider,
                  handle,
                  label,
                  profile_url,
                  sync_status,
                  last_synced_at,
                  metadata_json,
                  comparison_summary
                )
                VALUES (
                  :tenant_id,
                  :session_id,
                  :public_reference_profile_id,
                  :membership_id,
                  :provider,
                  :handle,
                  :label,
                  :profile_url,
                  :sync_status,
                  :last_synced_at,
                  CAST(:metadata_json AS jsonb),
                  CAST(:comparison_summary AS jsonb)
                )
                ON CONFLICT (
                  tenant_id,
                  onboarding_session_id,
                  provider,
                  handle
                )
                DO UPDATE SET
                  public_reference_profile_id = EXCLUDED.public_reference_profile_id,
                  label = EXCLUDED.label,
                  profile_url = EXCLUDED.profile_url,
                  sync_status = EXCLUDED.sync_status,
                  last_synced_at = EXCLUDED.last_synced_at,
                  metadata_json = EXCLUDED.metadata_json,
                  comparison_summary = EXCLUDED.comparison_summary,
                  status = 'active',
                  updated_at = NOW()
                RETURNING *
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "session_id": session_id,
                "public_reference_profile_id": str(public_reference["id"]),
                "membership_id": str(current.membership_id),
                "provider": provider,
                "handle": normalized_handle,
                "label": label,
                "profile_url": profile_url,
                "sync_status": effective_sync_status,
                "last_synced_at": public_reference["last_synced_at"],
                "metadata_json": json.dumps(
                    {
                        "source": "manual_input",
                        "public_reference_profile_id": str(public_reference["id"]),
                        "public_data_synced": bool(public_reference["last_synced_at"]),
                        "public_sync_job_id": str(sync_job.id) if sync_job else None,
                    }
                ),
                "comparison_summary": json.dumps(
                    {
                        "status": "pending_public_sync",
                        "next_step": (
                            "A Labby buscara os dados publicos por infraestrutura interna; "
                            "o cliente nao precisa sair da plataforma."
                        ),
                    }
                ),
            },
        ).mappings().one()
        public_contents_count = self.db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM social_public_reference_contents
                WHERE reference_profile_id = :reference_profile_id
                """
            ),
            {"reference_profile_id": str(public_reference["id"])},
        ).scalar_one()
        self.db.commit()
        reference = dict(row)
        reference["global_sync_status"] = public_reference["sync_status"]
        reference["global_last_synced_at"] = public_reference["last_synced_at"]
        reference["public_contents_count"] = int(public_contents_count or 0)
        reference["data_truth"] = public_reference["data_truth"]
        return reference

    def enqueue_reference_sync(
        self,
        *,
        current: CurrentMembership,
        session_id: str,
        reference_id: str,
    ) -> tuple[dict[str, Any], JobRecord | None]:
        self._get_session(current=current, session_id=session_id)
        reference = self._get_reference(
            tenant_id=str(current.tenant_id),
            session_id=session_id,
            reference_id=reference_id,
        )
        provider = _normalize_provider(str(reference["provider"]))
        handle = _normalize_handle(str(reference["handle"]))
        public_reference_profile_id = reference.get("public_reference_profile_id")

        if not public_reference_profile_id:
            raise HTTPException(
                status_code=409,
                detail="Referencia publica ainda nao possui registro global",
            )
        if provider != "instagram":
            raise HTTPException(
                status_code=409,
                detail="Sincronizacao publica automatica ainda suporta Instagram no MVP",
            )

        if reference.get("global_sync_status") == "syncing":
            self.db.rollback()
            return reference, None

        self._enforce_public_reference_sync_budget(provider=provider)
        public_reference = self.db.execute(
            text(
                """
                UPDATE social_public_reference_profiles
                SET sync_status = 'pending',
                    sync_generation = sync_generation + 1,
                    next_sync_after = NULL,
                    data_truth = data_truth || CAST(:data_truth AS jsonb),
                    updated_at = NOW()
                WHERE id = :public_reference_profile_id
                  AND provider = :provider
                  AND handle = :handle
                  AND sync_status <> 'syncing'
                RETURNING
                  id,
                  sync_status,
                  sync_generation,
                  last_synced_at,
                  data_truth
                """
            ),
            {
                "public_reference_profile_id": str(public_reference_profile_id),
                "provider": provider,
                "handle": handle,
                "data_truth": json.dumps(
                    {
                        "public_data_sync_requested": True,
                        "public_data_synced": False,
                        "last_sync_error_code": None,
                        "last_sync_error_message": None,
                    }
                ),
            },
        ).mappings().first()
        if public_reference is None:
            self.db.rollback()
            return self._get_reference(
                tenant_id=str(current.tenant_id),
                session_id=session_id,
                reference_id=reference_id,
            ), None

        self.db.execute(
            text(
                """
                UPDATE social_reference_profiles
                SET sync_status = 'pending',
                    comparison_summary = CAST(:comparison_summary AS jsonb),
                    updated_at = NOW()
                WHERE public_reference_profile_id = :public_reference_profile_id
                  AND status = 'active'
                """
            ),
            {
                "public_reference_profile_id": str(public_reference_profile_id),
                "comparison_summary": json.dumps(
                    {
                        "status": "pending_public_sync",
                        "next_step": (
                            "A Labby esta sincronizando dados publicos por infraestrutura "
                            "interna; o cliente nao precisa sair da plataforma."
                        ),
                    }
                ),
            },
        )
        sync_generation = int(public_reference["sync_generation"] or 0)
        job = self._enqueue_public_reference_sync_job(
            tenant_id=str(current.tenant_id),
            membership_id=str(current.membership_id),
            session_id=session_id,
            public_reference_profile_id=str(public_reference_profile_id),
            provider=provider,
            handle=handle,
            sync_generation=sync_generation,
            commit=False,
        )
        self.db.commit()
        return self._get_reference(
            tenant_id=str(current.tenant_id),
            session_id=session_id,
            reference_id=reference_id,
        ), job

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

    def enqueue_specialist_analysis(
        self,
        *,
        current: CurrentMembership,
        session_id: str,
    ) -> tuple[dict[str, Any], JobRecord]:
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
            {"tenant_id": str(current.tenant_id), "session_id": session_id},
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Onboarding nao encontrado")
        if row["status"] != "ready":
            raise HTTPException(status_code=409, detail="Diagnostico ainda nao esta pronto")

        row = self._refresh_ready_report_if_benchmark_stale(row=dict(row))
        report = dict(row["analysis_report"] or {})
        brief_value = report.get("specialist_brief")
        brief = brief_value if isinstance(brief_value, dict) else {}
        if not brief.get("ready_for_ai"):
            raise HTTPException(
                status_code=409,
                detail="Dados reais insuficientes para analise especialista",
            )

        analysis_version = int(row["analysis_version"])
        existing = report.get("specialist_analysis")
        existing_request_generation = (
            _int_value(existing.get("request_generation"))
            if isinstance(existing, dict)
            else 0
        )
        if (
            isinstance(existing, dict)
            and existing.get("version") == SOCIAL_SPECIALIST_ANALYSIS_VERSION
            and existing.get("analysis_version") == analysis_version
            and existing.get("status") in {"queued", "running", "ready"}
        ):
            job = self._enqueue_specialist_analysis_job(
                tenant_id=str(current.tenant_id),
                membership_id=str(current.membership_id),
                session_id=session_id,
                analysis_version=analysis_version,
                request_generation=max(existing_request_generation, 1),
                commit=False,
            )
            self.db.commit()
            return self._with_references(dict(row)), job

        try:
            self._enforce_specialist_analysis_budget(tenant_id=str(current.tenant_id))
        except HTTPException:
            self.db.rollback()
            raise

        queued_at = datetime.now(UTC).isoformat()
        request_generation = existing_request_generation + 1
        report["specialist_analysis"] = {
            "status": "queued",
            "version": SOCIAL_SPECIALIST_ANALYSIS_VERSION,
            "analysis_version": analysis_version,
            "request_generation": request_generation,
            "queued_at": queued_at,
            "provider": None,
            "model": None,
        }
        job = self._enqueue_specialist_analysis_job(
            tenant_id=str(current.tenant_id),
            membership_id=str(current.membership_id),
            session_id=session_id,
            analysis_version=analysis_version,
            request_generation=request_generation,
            commit=False,
        )
        row = self.db.execute(
            text(
                """
                UPDATE social_onboarding_sessions
                SET analysis_report = CAST(:analysis_report AS jsonb),
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :session_id
                  AND status = 'ready'
                  AND analysis_version = :analysis_version
                RETURNING *
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "session_id": session_id,
                "analysis_version": analysis_version,
                "analysis_report": json.dumps(report),
            },
        ).mappings().first()
        if row is None:
            self.db.rollback()
            raise HTTPException(status_code=409, detail="Diagnostico mudou durante a solicitacao")
        self.db.commit()
        return self._with_references(dict(row)), job

    def get_action_plan(
        self,
        *,
        current: CurrentMembership,
        session_id: str,
    ) -> dict[str, Any]:
        plan = self._get_active_action_plan(
            tenant_id=str(current.tenant_id),
            session_id=session_id,
        )
        if plan is None:
            raise HTTPException(status_code=404, detail="Plano de acao social nao encontrado")
        return plan

    def generate_action_plan(
        self,
        *,
        current: CurrentMembership,
        session_id: str,
    ) -> dict[str, Any]:
        row = self.db.execute(
            text(
                """
                SELECT *
                FROM social_onboarding_sessions
                WHERE tenant_id = :tenant_id
                  AND id = :session_id
                  AND status = 'ready'
                  AND status <> 'archived'
                FOR UPDATE
                """
            ),
            {"tenant_id": str(current.tenant_id), "session_id": session_id},
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Diagnostico pronto nao encontrado")

        session = self._with_references(dict(row))
        report = dict(session.get("analysis_report") or {})
        specialist_analysis = _ready_specialist_analysis(report, session=session)
        if specialist_analysis is None:
            raise HTTPException(
                status_code=409,
                detail="Gere a analise especialista antes de criar o plano de acao",
            )

        plan_payload = _build_social_action_plan_payload(session=session, report=report)
        items = _normalize_social_action_items(
            specialist_analysis=specialist_analysis,
            report=report,
        )
        calendar_entries = _build_social_calendar_entries(
            items=items,
            report=report,
            session=session,
        )

        self.db.execute(
            text(
                """
                UPDATE social_action_plans
                SET status = 'archived',
                    updated_by_membership_id = :membership_id,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND onboarding_session_id = :session_id
                  AND status = 'active'
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "session_id": session_id,
                "membership_id": str(current.membership_id),
            },
        )
        plan_row = self.db.execute(
            text(
                """
                INSERT INTO social_action_plans (
                  tenant_id,
                  onboarding_session_id,
                  created_by_membership_id,
                  updated_by_membership_id,
                  title,
                  summary,
                  source_analysis_version,
                  source_specialist_version,
                  metadata_json
                )
                VALUES (
                  :tenant_id,
                  :session_id,
                  :membership_id,
                  :membership_id,
                  :title,
                  :summary,
                  :source_analysis_version,
                  :source_specialist_version,
                  CAST(:metadata_json AS jsonb)
                )
                RETURNING *
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "session_id": session_id,
                "membership_id": str(current.membership_id),
                "title": plan_payload["title"],
                "summary": plan_payload["summary"],
                "source_analysis_version": _int_value(session.get("analysis_version")),
                "source_specialist_version": specialist_analysis.get("version"),
                "metadata_json": json.dumps(plan_payload["metadata"]),
            },
        ).mappings().first()
        if plan_row is None:
            self.db.rollback()
            raise HTTPException(status_code=500, detail="Nao foi possivel criar o plano")
        plan_id = str(plan_row["id"])

        self.db.execute(
            text(
                """
                INSERT INTO social_action_plan_items (
                  tenant_id,
                  action_plan_id,
                  onboarding_session_id,
                  position,
                  title,
                  description,
                  why_it_matters,
                  how_to_execute,
                  expected_signal,
                  measurement,
                  evidence,
                  priority,
                  status,
                  source_json
                )
                VALUES (
                  :tenant_id,
                  :action_plan_id,
                  :session_id,
                  :position,
                  :title,
                  :description,
                  :why_it_matters,
                  :how_to_execute,
                  :expected_signal,
                  :measurement,
                  :evidence,
                  :priority,
                  'pending',
                  CAST(:source_json AS jsonb)
                )
                """
            ),
            [
                {
                    "tenant_id": str(current.tenant_id),
                    "action_plan_id": plan_id,
                    "session_id": session_id,
                    "position": index + 1,
                    "title": item["title"],
                    "description": item["description"],
                    "why_it_matters": item["why_it_matters"],
                    "how_to_execute": item["how_to_execute"],
                    "expected_signal": item["expected_signal"],
                    "measurement": item["measurement"],
                    "evidence": item["evidence"],
                    "priority": item["priority"],
                    "source_json": json.dumps(item["source"]),
                }
                for index, item in enumerate(items)
            ],
        )
        inserted_items = self.db.execute(
            text(
                """
                SELECT *
                FROM social_action_plan_items
                WHERE tenant_id = :tenant_id
                  AND action_plan_id = :action_plan_id
                ORDER BY position ASC, id ASC
                """
            ),
            {"tenant_id": str(current.tenant_id), "action_plan_id": plan_id},
        ).mappings().all()
        item_by_position = {int(item["position"]): str(item["id"]) for item in inserted_items}

        self.db.execute(
            text(
                """
                INSERT INTO social_content_calendar_entries (
                  tenant_id,
                  action_plan_id,
                  action_item_id,
                  onboarding_session_id,
                  scheduled_at,
                  day_index,
                  title,
                  format,
                  channel,
                  status,
                  theme,
                  hook,
                  caption_outline,
                  cta,
                  evidence,
                  objective,
                  source_reference_handle,
                  metrics_goal_json,
                  metadata_json
                )
                VALUES (
                  :tenant_id,
                  :action_plan_id,
                  :action_item_id,
                  :session_id,
                  :scheduled_at,
                  :day_index,
                  :title,
                  :format,
                  :channel,
                  'planned',
                  :theme,
                  :hook,
                  :caption_outline,
                  :cta,
                  :evidence,
                  :objective,
                  :source_reference_handle,
                  CAST(:metrics_goal_json AS jsonb),
                  CAST(:metadata_json AS jsonb)
                )
                """
            ),
            [
                {
                    "tenant_id": str(current.tenant_id),
                    "action_plan_id": plan_id,
                    "action_item_id": item_by_position.get(
                        _int_value(entry.get("action_position"))
                    ),
                    "session_id": session_id,
                    "scheduled_at": entry["scheduled_at"],
                    "day_index": entry["day_index"],
                    "title": entry["title"],
                    "format": entry["format"],
                    "channel": entry["channel"],
                    "theme": entry["theme"],
                    "hook": entry["hook"],
                    "caption_outline": entry["caption_outline"],
                    "cta": entry["cta"],
                    "evidence": entry["evidence"],
                    "objective": entry["objective"],
                    "source_reference_handle": entry.get("source_reference_handle"),
                    "metrics_goal_json": json.dumps(entry["metrics_goal"]),
                    "metadata_json": json.dumps(entry["metadata"]),
                }
                for entry in calendar_entries
            ],
        )
        self.db.commit()
        plan = self._get_active_action_plan(
            tenant_id=str(current.tenant_id),
            session_id=session_id,
        )
        if plan is None:
            raise HTTPException(status_code=500, detail="Plano de acao social nao encontrado")
        return plan

    def update_action_plan_item(
        self,
        *,
        current: CurrentMembership,
        item_id: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        allowed = {"pending", "in_progress", "approved", "sent_to_calendar", "done", "archived"}
        updates = {key: value for key, value in patch.items() if value is not None}
        if not updates:
            raise HTTPException(status_code=400, detail="Nenhuma alteracao informada")
        status = updates.get("status")
        if status is not None and status not in allowed:
            raise HTTPException(status_code=422, detail="Status do item invalido")

        row = self.db.execute(
            text(
                """
                UPDATE social_action_plan_items AS item
                SET status = COALESCE(:status, item.status),
                    notes = COALESCE(:notes, item.notes),
                    updated_at = NOW()
                FROM social_action_plans AS plan
                WHERE item.action_plan_id = plan.id
                  AND item.tenant_id = :tenant_id
                  AND item.id = :item_id
                  AND plan.status = 'active'
                RETURNING item.onboarding_session_id
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "item_id": item_id,
                "status": status,
                "notes": updates.get("notes"),
            },
        ).mappings().first()
        if row is None:
            self.db.rollback()
            raise HTTPException(status_code=404, detail="Item do plano nao encontrado")
        self.db.commit()
        plan = self._get_active_action_plan(
            tenant_id=str(current.tenant_id),
            session_id=str(row["onboarding_session_id"]),
        )
        if plan is None:
            raise HTTPException(status_code=404, detail="Plano de acao social nao encontrado")
        return plan

    def update_calendar_entry(
        self,
        *,
        current: CurrentMembership,
        entry_id: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        allowed = {"draft", "planned", "approved", "scheduled", "published", "archived"}
        updates = {key: value for key, value in patch.items() if value is not None}
        if not updates:
            raise HTTPException(status_code=400, detail="Nenhuma alteracao informada")
        status = updates.get("status")
        if status is not None and status not in allowed:
            raise HTTPException(status_code=422, detail="Status do calendario invalido")

        row = self.db.execute(
            text(
                """
                UPDATE social_content_calendar_entries AS entry
                SET status = COALESCE(:status, entry.status),
                    scheduled_at = COALESCE(:scheduled_at, entry.scheduled_at),
                    title = COALESCE(:title, entry.title),
                    caption_outline = COALESCE(:caption_outline, entry.caption_outline),
                    updated_at = NOW()
                FROM social_action_plans AS plan
                WHERE entry.action_plan_id = plan.id
                  AND entry.tenant_id = :tenant_id
                  AND entry.id = :entry_id
                  AND plan.status = 'active'
                RETURNING entry.onboarding_session_id
                """
            ),
            {
                "tenant_id": str(current.tenant_id),
                "entry_id": entry_id,
                "status": status,
                "scheduled_at": updates.get("scheduled_at"),
                "title": updates.get("title"),
                "caption_outline": updates.get("caption_outline"),
            },
        ).mappings().first()
        if row is None:
            self.db.rollback()
            raise HTTPException(status_code=404, detail="Entrada do calendario nao encontrada")
        self.db.commit()
        plan = self._get_active_action_plan(
            tenant_id=str(current.tenant_id),
            session_id=str(row["onboarding_session_id"]),
        )
        if plan is None:
            raise HTTPException(status_code=404, detail="Plano de acao social nao encontrado")
        return plan

    def _refresh_ready_report_if_benchmark_stale(self, *, row: dict[str, Any]) -> dict[str, Any]:
        current_report = dict(row.get("analysis_report") or {})
        references = self._list_references(
            tenant_id=str(row["tenant_id"]),
            session_id=str(row["id"]),
        )
        rebuilt_report = _build_report(row, references)
        if not _analysis_report_needs_benchmark_refresh(
            current_report=current_report,
            rebuilt_report=rebuilt_report,
        ):
            return row

        next_analysis_version = int(row["analysis_version"] or 0) + 1
        updated = self.db.execute(
            text(
                """
                UPDATE social_onboarding_sessions
                SET analysis_version = :analysis_version,
                    analysis_report = CAST(:analysis_report AS jsonb),
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :session_id
                  AND status = 'ready'
                  AND analysis_version = :current_analysis_version
                RETURNING *
                """
            ),
            {
                "tenant_id": str(row["tenant_id"]),
                "session_id": str(row["id"]),
                "analysis_version": next_analysis_version,
                "current_analysis_version": int(row["analysis_version"] or 0),
                "analysis_report": json.dumps(rebuilt_report),
            },
        ).mappings().first()
        if updated is None:
            self.db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Diagnostico mudou durante a solicitacao",
            )
        return dict(updated)

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

    def run_specialist_analysis(
        self,
        *,
        tenant_id: str,
        session_id: str,
        analysis_version: int,
        request_generation: int | None = None,
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
            return {
                "session_id": session_id,
                "skipped": True,
                "reason": "session_not_found_or_archived",
                "analysis_version": analysis_version,
            }
        current_version = int(row["analysis_version"])
        if current_version != analysis_version:
            return {
                "session_id": session_id,
                "skipped": True,
                "reason": "stale_analysis_version",
                "analysis_version": analysis_version,
                "current_analysis_version": current_version,
            }
        if row["status"] != "ready":
            return {
                "session_id": session_id,
                "skipped": True,
                "reason": "session_not_ready",
                "status": row["status"],
                "analysis_version": analysis_version,
            }

        report = dict(row["analysis_report"] or {})
        existing = report.get("specialist_analysis")
        existing_request_generation = (
            _int_value(existing.get("request_generation"))
            if isinstance(existing, dict)
            else 0
        )
        if request_generation is not None and existing_request_generation != request_generation:
            return {
                "session_id": session_id,
                "skipped": True,
                "reason": "stale_specialist_request_generation",
                "analysis_version": analysis_version,
                "request_generation": request_generation,
                "current_request_generation": existing_request_generation,
            }
        if (
            isinstance(existing, dict)
            and existing.get("version") == SOCIAL_SPECIALIST_ANALYSIS_VERSION
            and existing.get("analysis_version") == analysis_version
            and existing.get("status") == "ready"
        ):
            return {
                "session_id": session_id,
                "skipped": True,
                "status": "ready",
                "analysis_version": analysis_version,
            }
        brief_value = report.get("specialist_brief")
        brief = brief_value if isinstance(brief_value, dict) else {}
        if not brief.get("ready_for_ai"):
            raise ValueError("Dados reais insuficientes para analise especialista")

        running = dict(existing) if isinstance(existing, dict) else {}
        running.update(
            {
                "status": "running",
                "version": SOCIAL_SPECIALIST_ANALYSIS_VERSION,
                "analysis_version": analysis_version,
                "request_generation": existing_request_generation or request_generation or 1,
                "started_at": datetime.now(UTC).isoformat(),
                "error_code": None,
                "error_message": None,
            }
        )
        report["specialist_analysis"] = running
        self.db.execute(
            text(
                """
                UPDATE social_onboarding_sessions
                SET analysis_report = CAST(:analysis_report AS jsonb),
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :session_id
                  AND status = 'ready'
                  AND analysis_version = :analysis_version
                """
            ),
            {
                "tenant_id": tenant_id,
                "session_id": session_id,
                "analysis_version": analysis_version,
                "analysis_report": json.dumps(report),
            },
        )
        self.db.commit()

        client = self.specialist_ai_client or make_ai_specialist_analysis_client(self.settings)
        result = client.generate_social_profile_analysis(
            analysis_input=_build_specialist_analysis_input(
                session=dict(row),
                report=report,
                analysis_version=analysis_version,
            )
        )
        completed_analysis = dict(result.analysis)
        completed_analysis.update(
            {
                "status": "ready",
                "version": SOCIAL_SPECIALIST_ANALYSIS_VERSION,
                "analysis_version": analysis_version,
                "request_generation": existing_request_generation or request_generation or 1,
                "provider": result.provider,
                "model": result.model,
                "provider_response_id": result.provider_response_id,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cost_usd": result.cost_usd,
                "completed_at": datetime.now(UTC).isoformat(),
            }
        )

        latest = self.db.execute(
            text(
                """
                SELECT *
                FROM social_onboarding_sessions
                WHERE tenant_id = :tenant_id
                  AND id = :session_id
                  AND status = 'ready'
                  AND analysis_version = :analysis_version
                FOR UPDATE
                """
            ),
            {
                "tenant_id": tenant_id,
                "session_id": session_id,
                "analysis_version": analysis_version,
            },
        ).mappings().first()
        if latest is None:
            self.db.rollback()
            return {
                "session_id": session_id,
                "skipped": True,
                "reason": "session_changed_before_save",
                "analysis_version": analysis_version,
            }
        latest_report = dict(latest["analysis_report"] or {})
        latest_existing = latest_report.get("specialist_analysis")
        latest_generation = (
            _int_value(latest_existing.get("request_generation"))
            if isinstance(latest_existing, dict)
            else 0
        )
        expected_generation = existing_request_generation or request_generation or 1
        if latest_generation != expected_generation:
            self.db.rollback()
            return {
                "session_id": session_id,
                "skipped": True,
                "reason": "specialist_request_changed_before_save",
                "analysis_version": analysis_version,
                "request_generation": expected_generation,
                "current_request_generation": latest_generation,
            }
        latest_report["specialist_analysis"] = completed_analysis
        self.db.execute(
            text(
                """
                UPDATE social_onboarding_sessions
                SET analysis_report = CAST(:analysis_report AS jsonb),
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :session_id
                  AND status = 'ready'
                  AND analysis_version = :analysis_version
                """
            ),
            {
                "tenant_id": tenant_id,
                "session_id": session_id,
                "analysis_version": analysis_version,
                "analysis_report": json.dumps(latest_report),
            },
        )
        self.db.commit()
        return {
            "session_id": session_id,
            "status": "ready",
            "analysis_version": analysis_version,
            "provider": result.provider,
            "model": result.model,
        }

    def run_public_reference_sync(
        self,
        *,
        tenant_id: str,
        public_reference_profile_id: str,
        provider: str,
        handle: str,
        sync_generation: int,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        provider = _normalize_provider(provider)
        normalized_handle = _normalize_handle(handle)

        reference = self.db.execute(
            text(
                """
                SELECT *
                FROM social_public_reference_profiles
                WHERE id = :public_reference_profile_id
                  AND provider = :provider
                  AND handle = :handle
                """
            ),
            {
                "public_reference_profile_id": public_reference_profile_id,
                "provider": provider,
                "handle": normalized_handle,
            },
        ).mappings().first()
        if reference is None:
            self.db.rollback()
            return {
                "public_reference_profile_id": public_reference_profile_id,
                "skipped": True,
                "reason": "reference_not_found",
            }
        if int(reference["sync_generation"] or 0) != sync_generation:
            self.db.rollback()
            return {
                "public_reference_profile_id": public_reference_profile_id,
                "skipped": True,
                "reason": "stale_sync_generation",
                "sync_generation": sync_generation,
                "current_sync_generation": int(reference["sync_generation"] or 0),
            }
        if not _public_reference_job_can_attempt(
            dict(reference),
            circuit_breaker_failures=self.settings.apify_public_reference_circuit_breaker_failures,
        ):
            self.db.rollback()
            return {
                "public_reference_profile_id": public_reference_profile_id,
                "skipped": True,
                "reason": "fresh_or_circuit_open_reference_cache",
                "sync_status": reference["sync_status"],
            }
        if provider != "instagram":
            self._mark_public_reference_sync_result(
                public_reference_profile_id=public_reference_profile_id,
                status="unavailable",
                error_code="unsupported_provider",
                error_message="Sincronizacao publica ainda suporta Instagram no MVP",
                commit=True,
            )
            return {
                "public_reference_profile_id": public_reference_profile_id,
                "status": "unavailable",
                "reason": "unsupported_provider",
            }

        claimed = self.db.execute(
            text(
                """
                UPDATE social_public_reference_profiles
                SET sync_status = 'syncing',
                    updated_at = NOW()
                WHERE id = :public_reference_profile_id
                  AND provider = :provider
                  AND handle = :handle
                  AND sync_generation = :sync_generation
                  AND sync_status <> 'syncing'
                RETURNING *
                """
            ),
            {
                "public_reference_profile_id": public_reference_profile_id,
                "provider": provider,
                "handle": normalized_handle,
                "sync_generation": sync_generation,
            },
        ).mappings().first()
        if claimed is None:
            self.db.rollback()
            return {
                "public_reference_profile_id": public_reference_profile_id,
                "provider": provider,
                "handle": normalized_handle,
                "skipped": True,
                "reason": "sync_already_claimed",
            }
        self.db.execute(
            text(
                """
                UPDATE social_reference_profiles
                SET sync_status = 'syncing',
                    updated_at = NOW()
                WHERE public_reference_profile_id = :public_reference_profile_id
                  AND status = 'active'
                """
            ),
            {"public_reference_profile_id": public_reference_profile_id},
        )
        self.db.commit()

        try:
            profile_items = self.apify_client.fetch_instagram_profile(handle=normalized_handle)
            profile_raw = profile_items[0] if profile_items else {}
            if not profile_raw:
                self._mark_public_reference_sync_result(
                    public_reference_profile_id=public_reference_profile_id,
                    status="unavailable",
                    error_code="profile_not_found",
                    error_message="Perfil publico nao retornou dados na fonte configurada",
                    commit=True,
                )
                return {
                    "public_reference_profile_id": public_reference_profile_id,
                    "status": "unavailable",
                    "reason": "profile_not_found",
                }

            normalized_profile = _normalize_apify_instagram_profile(
                profile_raw,
                fallback_handle=normalized_handle,
            )
            posts_error: str | None = None
            try:
                post_items = self.apify_client.fetch_instagram_posts(
                    handle=normalized_handle,
                    limit=self.settings.apify_instagram_max_posts_per_profile,
                )
            except ApifyProviderError as exc:
                logger.warning(
                    "apify_public_reference_posts_degraded",
                    extra={
                        "public_reference_profile_id": public_reference_profile_id,
                        "provider": provider,
                        "handle": normalized_handle,
                    },
                    exc_info=True,
                )
                post_items = []
                posts_error = str(exc)

            normalized_posts = [
                _normalize_apify_instagram_post(
                    item,
                    followers_count=int(normalized_profile.get("followers_count") or 0),
                )
                for item in post_items[: self.settings.apify_instagram_max_posts_per_profile]
                if isinstance(item, dict)
            ]
            normalized_posts = [item for item in normalized_posts if item.get("external_id")]
            status = "synced" if normalized_posts else "partially_synced"
            next_sync_after = datetime.now(UTC) + timedelta(
                days=max(1, self.settings.apify_public_reference_ttl_days)
            )
            self._persist_public_reference_sync(
                public_reference_profile_id=public_reference_profile_id,
                provider=provider,
                profile=normalized_profile,
                profile_raw=profile_raw,
                posts=normalized_posts,
                sync_status=status,
                next_sync_after=next_sync_after,
                posts_error=posts_error,
            )
            diagnostic_job = None
            if session_id:
                diagnostic_job = self._enqueue_reference_diagnostic_if_possible(
                    tenant_id=tenant_id,
                    session_id=session_id,
                    commit=False,
                )
            self.db.commit()
            return {
                "public_reference_profile_id": public_reference_profile_id,
                "provider": provider,
                "handle": normalized_handle,
                "status": status,
                "posts_synced": len(normalized_posts),
                "diagnostic_job_id": str(diagnostic_job.id) if diagnostic_job else None,
            }
        except ApifyConfigurationError as exc:
            self.db.rollback()
            self._mark_public_reference_sync_result(
                public_reference_profile_id=public_reference_profile_id,
                status="failed",
                error_code="apify_not_configured",
                error_message="LABBY_APIFY_API_TOKEN nao configurado",
                commit=True,
            )
            raise ValueError("Apify nao configurado para sincronizacao publica") from exc
        except ApifyProviderError as exc:
            self.db.rollback()
            self._mark_public_reference_sync_result(
                public_reference_profile_id=public_reference_profile_id,
                status="failed",
                error_code="apify_provider_error",
                error_message=str(exc),
                commit=True,
            )
            raise ValueError("Falha na fonte publica configurada") from exc

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
        content_sync_status = "synced"
        content_sync_error = None
        try:
            contents = self._call_phyllo(
                lambda: self.phyllo_client.list_contents(account_id=account_id)
            )
        except HTTPException as exc:
            logger.warning(
                "phyllo_content_sync_degraded",
                extra={"session_id": str(session["id"]), "phyllo_account_id": account_id},
                exc_info=True,
            )
            contents = []
            content_sync_status = "unavailable"
            content_sync_error = str(exc.detail)

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
        normalized_contents = list(content_summary.pop("_normalized_contents", []))
        self._persist_connected_contents(
            session=session,
            provider=provider,
            account_id=account_id,
            normalized_contents=normalized_contents,
        )
        content_summary["data_quality"]["content_sync_status"] = content_sync_status
        if content_sync_error:
            content_summary["data_quality"]["content_sync_error"] = content_sync_error
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

    def reconcile_stale_public_reference_syncs(
        self,
        *,
        stale_after_minutes: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        candidates = self.db.execute(
            text(
                """
                SELECT id
                FROM social_public_reference_profiles
                WHERE sync_status = 'syncing'
                  AND updated_at < NOW() - make_interval(mins => :stale_after_minutes)
                ORDER BY updated_at ASC, id ASC
                FOR UPDATE SKIP LOCKED
                LIMIT :limit
                """
            ),
            {
                "stale_after_minutes": max(1, stale_after_minutes),
                "limit": max(1, limit),
            },
        ).mappings().all()
        ids = [str(row["id"]) for row in candidates]
        if not ids:
            self.db.commit()
            return []

        next_sync_after = datetime.now(UTC) + timedelta(
            hours=max(1, self.settings.apify_public_reference_failure_backoff_hours)
        )
        data_truth = {
            "public_data_synced": False,
            "last_sync_error_code": "sync_abandoned",
            "last_sync_error_message": "Public reference sync claimed but did not finish",
            "next_sync_after": next_sync_after.isoformat(),
        }
        rows = self.db.execute(
            text(
                """
                UPDATE social_public_reference_profiles
                SET sync_status = 'failed',
                    failure_count = failure_count + 1,
                    next_sync_after = :next_sync_after,
                    data_truth = data_truth || CAST(:data_truth AS jsonb),
                    updated_at = NOW()
                WHERE id IN :ids
                RETURNING *
                """
            ).bindparams(bindparam("ids", expanding=True)),
            {
                "ids": ids,
                "next_sync_after": next_sync_after,
                "data_truth": json.dumps(data_truth),
            },
        ).mappings().all()
        self.db.execute(
            text(
                """
                UPDATE social_reference_profiles
                SET sync_status = 'failed',
                    comparison_summary = CAST(:comparison_summary AS jsonb),
                    updated_at = NOW()
                WHERE public_reference_profile_id IN :ids
                  AND status = 'active'
                """
            ).bindparams(bindparam("ids", expanding=True)),
            {
                "ids": ids,
                "comparison_summary": json.dumps(
                    {
                        "status": "failed",
                        "error_code": "sync_abandoned",
                        "error_message": "Public reference sync did not finish",
                        "next_sync_after": next_sync_after.isoformat(),
                        "next_step": "Tentar novamente mais tarde",
                    }
                ),
            },
        )
        self.db.commit()
        return [dict(row) for row in rows]

    def cleanup_orphaned_public_references(
        self,
        *,
        retention_days: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = self.db.execute(
            text(
                """
                WITH candidates AS (
                  SELECT p.id
                  FROM social_public_reference_profiles p
                  WHERE p.updated_at < NOW() - make_interval(days => :retention_days)
                    AND NOT EXISTS (
                      SELECT 1
                      FROM social_reference_profiles r
                      WHERE r.public_reference_profile_id = p.id
                        AND r.status = 'active'
                    )
                  ORDER BY p.updated_at ASC, p.id ASC
                  FOR UPDATE SKIP LOCKED
                  LIMIT :limit
                )
                DELETE FROM social_public_reference_profiles p
                USING candidates
                WHERE p.id = candidates.id
                RETURNING p.*
                """
            ),
            {
                "retention_days": max(1, retention_days),
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

    def mark_specialist_analysis_failed(
        self,
        *,
        tenant_id: str,
        session_id: str,
        analysis_version: int,
        request_generation: int | None = None,
        error_code: str,
        error_message: str,
    ) -> None:
        row = self.db.execute(
            text(
                """
                SELECT analysis_report
                FROM social_onboarding_sessions
                WHERE tenant_id = :tenant_id
                  AND id = :session_id
                  AND status = 'ready'
                  AND analysis_version = :analysis_version
                FOR UPDATE
                """
            ),
            {
                "tenant_id": tenant_id,
                "session_id": session_id,
                "analysis_version": analysis_version,
            },
        ).mappings().first()
        if row is None:
            self.db.rollback()
            return
        report = dict(row["analysis_report"] or {})
        existing = report.get("specialist_analysis")
        existing_generation = (
            _int_value(existing.get("request_generation"))
            if isinstance(existing, dict)
            else 0
        )
        if request_generation is not None and existing_generation != request_generation:
            self.db.rollback()
            return
        report["specialist_analysis"] = {
            "status": "failed",
            "version": SOCIAL_SPECIALIST_ANALYSIS_VERSION,
            "analysis_version": analysis_version,
            "request_generation": existing_generation or request_generation or 1,
            "error_code": error_code[:120],
            "error_message": error_message[:2000],
            "failed_at": datetime.now(UTC).isoformat(),
        }
        self.db.execute(
            text(
                """
                UPDATE social_onboarding_sessions
                SET analysis_report = CAST(:analysis_report AS jsonb),
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :session_id
                  AND status = 'ready'
                  AND analysis_version = :analysis_version
                """
            ),
            {
                "tenant_id": tenant_id,
                "session_id": session_id,
                "analysis_version": analysis_version,
                "analysis_report": json.dumps(report),
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

    def _enqueue_specialist_analysis_job(
        self,
        *,
        tenant_id: str,
        membership_id: str | None,
        session_id: str,
        analysis_version: int,
        request_generation: int,
        commit: bool,
    ) -> JobRecord:
        return self.job_queue.enqueue_job(
            tenant_id=tenant_id,
            membership_id=membership_id,
            job_type=SOCIAL_ONBOARDING_SPECIALIST_JOB,
            queue_name=SOCIAL_ONBOARDING_QUEUE,
            idempotency_key=(
                f"social.onboarding.specialist:{session_id}:v{analysis_version}:"
                f"{SOCIAL_SPECIALIST_ANALYSIS_VERSION}:r{request_generation}"
            ),
            payload={
                "session_id": session_id,
                "analysis_version": analysis_version,
                "request_generation": request_generation,
            },
            max_attempts=1,
            commit=commit,
        )

    def _enqueue_public_reference_sync_job(
        self,
        *,
        tenant_id: str,
        membership_id: str | None,
        session_id: str | None,
        public_reference_profile_id: str,
        provider: str,
        handle: str,
        sync_generation: int,
        commit: bool,
    ) -> JobRecord:
        return self.job_queue.enqueue_job(
            tenant_id=tenant_id,
            membership_id=membership_id,
            job_type=SOCIAL_REFERENCE_SYNC_JOB,
            queue_name=SOCIAL_ONBOARDING_QUEUE,
            idempotency_key=(
                f"social.references.sync:{provider}:{handle}:v{sync_generation}"
            ),
            payload={
                "public_reference_profile_id": public_reference_profile_id,
                "session_id": session_id,
                "provider": provider,
                "handle": handle,
                "sync_generation": sync_generation,
            },
            max_attempts=1,
            commit=commit,
        )

    def _enforce_public_reference_add_budget(self, *, tenant_id: str, provider: str) -> None:
        self._enforce_public_reference_limit(
            key=f"social-reference:add:{tenant_id}:{provider}",
            limit=self.settings.apify_public_reference_add_limit_per_hour,
            window_seconds=60 * 60,
        )

    def _enforce_public_reference_sync_budget(self, *, provider: str) -> None:
        day = datetime.now(UTC).strftime("%Y%m%d")
        self._enforce_public_reference_limit(
            key=f"social-reference:sync:{provider}:{day}",
            limit=self.settings.apify_public_reference_sync_limit_per_day,
            window_seconds=60 * 60 * 24,
        )

    def _enforce_specialist_analysis_budget(self, *, tenant_id: str) -> None:
        day = datetime.now(UTC).strftime("%Y%m%d")
        limiter = self._public_reference_rate_limiter()
        if limiter is None:
            return
        key = f"social-specialist-analysis:{tenant_id}:{day}"
        try:
            decision = limiter.check(
                key=key,
                limit=self.settings.social_specialist_analysis_limit_per_day,
                window_seconds=60 * 60 * 24,
            )
        except RateLimitUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail="Limitador de custo indisponivel",
            ) from exc
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail="Limite diario de analises especialistas atingido",
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )

    def _enforce_public_reference_limit(
        self,
        *,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> None:
        limiter = self._public_reference_rate_limiter()
        if limiter is None:
            return
        try:
            decision = limiter.check(
                key=key,
                limit=limit,
                window_seconds=window_seconds,
            )
        except RateLimitUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail="Limitador de custo indisponivel",
            ) from exc
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail="Limite de sincronizacao publica atingido",
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )

    def _public_reference_rate_limiter(self) -> PublicRateLimiter | None:
        if self.rate_limiter is not None:
            return self.rate_limiter
        if self.settings.public_rate_limit_backend == "redis":
            self.rate_limiter = RedisFixedWindowRateLimiter()
            return self.rate_limiter
        logger.warning(
            "public_reference_rate_limiter_disabled",
            extra={"backend": self.settings.public_rate_limit_backend},
        )
        return None

    def _enqueue_reference_diagnostic_if_possible(
        self,
        *,
        tenant_id: str,
        session_id: str,
        commit: bool,
    ) -> JobRecord | None:
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
                  AND status NOT IN ('archived', 'connecting', 'analyzing')
                  AND connected_account_id IS NOT NULL
                  AND connected_account_handle IS NOT NULL
                  AND (
                    :debounce_seconds = 0
                    OR analysis_completed_at IS NULL
                    OR analysis_completed_at < NOW() - make_interval(secs => :debounce_seconds)
                    OR COALESCE(
                      (
                        (analysis_report -> 'reference_context')
                        ->> 'references_with_public_data'
                      )::integer,
                      0
                    ) = 0
                  )
                RETURNING *
                """
            ),
            {
                "tenant_id": tenant_id,
                "session_id": session_id,
                "progress_steps": json.dumps(_analysis_progress()),
                "debounce_seconds": (
                    self.settings.social_onboarding_reference_diagnostic_debounce_seconds
                ),
            },
        ).mappings().first()
        if row is None:
            return None
        return self._enqueue_diagnostic_job_for_ids(
            tenant_id=tenant_id,
            membership_id=(
                str(row["updated_by_membership_id"])
                if row.get("updated_by_membership_id")
                else None
            ),
            session_id=session_id,
            analysis_version=int(row["analysis_version"]),
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

    def _mark_public_reference_sync_result(
        self,
        *,
        public_reference_profile_id: str,
        status: str,
        error_code: str | None,
        error_message: str | None,
        commit: bool,
    ) -> None:
        increment_failure = status in {"failed", "unavailable", "partially_synced"}
        next_sync_after = datetime.now(UTC) + timedelta(
            hours=max(1, self.settings.apify_public_reference_failure_backoff_hours)
        )
        summary = {
            "status": status,
            "error_code": error_code,
            "error_message": error_message,
            "next_sync_after": next_sync_after.isoformat(),
            "next_step": (
                "Tentar novamente mais tarde"
                if status == "failed"
                else "Adicionar outra referencia ou revisar o handle informado"
            ),
        }
        self.db.execute(
            text(
                """
                UPDATE social_public_reference_profiles
                SET sync_status = :status,
                    failure_count = CASE
                      WHEN :increment_failure THEN failure_count + 1
                      ELSE failure_count
                    END,
                    next_sync_after = :next_sync_after,
                    data_truth = data_truth || CAST(:data_truth AS jsonb),
                    updated_at = NOW()
                WHERE id = :public_reference_profile_id
                """
            ),
            {
                "public_reference_profile_id": public_reference_profile_id,
                "status": status,
                "increment_failure": increment_failure,
                "next_sync_after": next_sync_after,
                "data_truth": json.dumps(
                    {
                        "public_data_synced": False,
                        "last_sync_error_code": error_code,
                        "last_sync_error_message": error_message,
                        "next_sync_after": next_sync_after.isoformat(),
                    }
                ),
            },
        )
        self.db.execute(
            text(
                """
                UPDATE social_reference_profiles
                SET sync_status = :status,
                    comparison_summary = CAST(:comparison_summary AS jsonb),
                    updated_at = NOW()
                WHERE public_reference_profile_id = :public_reference_profile_id
                  AND status = 'active'
                """
            ),
            {
                "public_reference_profile_id": public_reference_profile_id,
                "status": status,
                "comparison_summary": json.dumps(summary),
            },
        )
        if commit:
            self.db.commit()

    def _persist_public_reference_sync(
        self,
        *,
        public_reference_profile_id: str,
        provider: str,
        profile: dict[str, Any],
        profile_raw: dict[str, Any],
        posts: list[dict[str, Any]],
        sync_status: str,
        next_sync_after: datetime,
        posts_error: str | None,
    ) -> None:
        self.db.execute(
            text(
                """
                UPDATE social_public_reference_profiles
                SET display_name = :display_name,
                    profile_url = :profile_url,
                    source = 'apify',
                    sync_status = CAST(:sync_status AS varchar),
                    failure_count = CASE
                      WHEN CAST(:sync_status AS varchar) = 'synced' THEN 0
                      ELSE failure_count + 1
                    END,
                    profile_snapshot = CAST(:profile_snapshot AS jsonb),
                    raw_payload = CAST(:raw_payload AS jsonb),
                    data_truth = CAST(:data_truth AS jsonb),
                    last_synced_at = NOW(),
                    next_sync_after = :next_sync_after,
                    observed_at = NOW(),
                    updated_at = NOW()
                WHERE id = :public_reference_profile_id
                """
            ),
            {
                "public_reference_profile_id": public_reference_profile_id,
                "display_name": profile.get("display_name"),
                "profile_url": profile.get("profile_url"),
                "sync_status": sync_status,
                "profile_snapshot": json.dumps(profile),
                "raw_payload": json.dumps(_minimize_apify_profile_raw(profile_raw)),
                "data_truth": json.dumps(
                    {
                        "source": "apify",
                        "source_detail": "apify.instagram-profile-scraper",
                        "confidence": "high",
                        "is_inferred": False,
                        "public_data_synced": True,
                        "public_data_only": True,
                        "raw_payload_persisted": True,
                        "posts_sync_error": posts_error,
                    }
                ),
                "next_sync_after": next_sync_after,
            },
        )
        rows = []
        for post in posts:
            raw_post = post.pop("_raw", {})
            minimized_raw_post = _minimize_apify_post_raw(raw_post)
            rows.append(
                {
                    "reference_profile_id": public_reference_profile_id,
                    "provider": provider,
                    "external_id": post["external_id"],
                    "content_type": post.get("type") or "UNKNOWN",
                    "content_format": post.get("format") or "UNKNOWN",
                    "title": post.get("title"),
                    "content_url": post.get("url"),
                    "published_at": _parse_datetime(post.get("published_at")),
                    "metrics_json": json.dumps(post.get("metrics") or {}),
                    "raw_payload": json.dumps(minimized_raw_post),
                    "data_truth": json.dumps(
                        {
                            "source": "apify",
                            "source_detail": "apify.instagram-post-scraper",
                            "confidence": (
                                "medium"
                                if post.get("unavailable_metrics")
                                else "high"
                            ),
                            "is_inferred": False,
                            "public_data_only": True,
                            "raw_payload_persisted": True,
                            "unavailable_metrics": post.get("unavailable_metrics") or [],
                        }
                    ),
                    "engagement_rate_by_followers": post.get("engagement_rate_by_followers"),
                    "engagement_rate_by_reach": post.get("engagement_rate_by_reach"),
                    "performance_score": post.get("performance_score"),
                }
            )
        if rows:
            self.db.execute(
                text(
                    """
                    INSERT INTO social_public_reference_contents (
                      reference_profile_id,
                      provider,
                      external_id,
                      content_type,
                      content_format,
                      title,
                      content_url,
                      published_at,
                      metrics_json,
                      raw_payload,
                      data_truth,
                      engagement_rate_by_followers,
                      engagement_rate_by_reach,
                      performance_score,
                      observed_at,
                      updated_at
                    )
                    VALUES (
                      :reference_profile_id,
                      :provider,
                      :external_id,
                      :content_type,
                      :content_format,
                      :title,
                      :content_url,
                      :published_at,
                      CAST(:metrics_json AS jsonb),
                      CAST(:raw_payload AS jsonb),
                      CAST(:data_truth AS jsonb),
                      :engagement_rate_by_followers,
                      :engagement_rate_by_reach,
                      :performance_score,
                      NOW(),
                      NOW()
                    )
                    ON CONFLICT (reference_profile_id, external_id)
                    DO UPDATE SET
                      provider = EXCLUDED.provider,
                      content_type = EXCLUDED.content_type,
                      content_format = EXCLUDED.content_format,
                      title = EXCLUDED.title,
                      content_url = EXCLUDED.content_url,
                      published_at = EXCLUDED.published_at,
                      metrics_json = EXCLUDED.metrics_json,
                      raw_payload = EXCLUDED.raw_payload,
                      data_truth = EXCLUDED.data_truth,
                      engagement_rate_by_followers = EXCLUDED.engagement_rate_by_followers,
                      engagement_rate_by_reach = EXCLUDED.engagement_rate_by_reach,
                      performance_score = EXCLUDED.performance_score,
                      observed_at = NOW(),
                      updated_at = NOW()
                    """
                ),
                rows,
            )
        comparison_summary = {
            "status": sync_status,
            "source": "apify",
            "public_contents_count": len(rows),
            "public_followers_count": int(profile.get("followers_count") or 0),
            "public_posts_count": int(profile.get("posts_count") or 0),
            "next_sync_after": next_sync_after.isoformat(),
            "next_step": (
                "Comparativo publico pronto para o proximo diagnostico"
                if rows
                else "Perfil lido; faltam posts publicos para comparar performance"
            ),
        }
        self.db.execute(
            text(
                """
                UPDATE social_reference_profiles
                SET sync_status = :sync_status,
                    last_synced_at = NOW(),
                    metadata_json = (
                      COALESCE(metadata_json, '{}'::jsonb)
                      || CAST(:metadata_json AS jsonb)
                    ),
                    comparison_summary = CAST(:comparison_summary AS jsonb),
                    updated_at = NOW()
                WHERE public_reference_profile_id = :public_reference_profile_id
                  AND status = 'active'
                """
            ),
            {
                "public_reference_profile_id": public_reference_profile_id,
                "sync_status": sync_status,
                "metadata_json": json.dumps(
                    {
                        "public_data_synced": bool(rows),
                        "public_reference_source": "apify",
                    }
                ),
                "comparison_summary": json.dumps(comparison_summary),
            },
        )

    def _persist_connected_contents(
        self,
        *,
        session: dict[str, Any],
        provider: str,
        account_id: str,
        normalized_contents: list[dict[str, Any]],
    ) -> None:
        rows: list[dict[str, Any]] = []
        for item in normalized_contents:
            raw_content = item.pop("_raw", {})
            external_id = str(item.get("external_id") or item.get("id") or "").strip()
            if not external_id:
                continue
            rows.append(
                {
                    "tenant_id": str(session["tenant_id"]),
                    "session_id": str(session["id"]),
                    "environment": self.settings.phyllo_environment,
                    "provider": provider,
                    "phyllo_account_id": account_id,
                    "external_id": external_id,
                    "phyllo_content_id": str(item.get("id") or "") or None,
                    "content_type": item.get("type") or "UNKNOWN",
                    "content_format": item.get("format") or "UNKNOWN",
                    "title": item.get("title"),
                    "content_url": item.get("url"),
                    "published_at": _parse_datetime(item.get("published_at")),
                    "metrics_json": json.dumps(item.get("metrics") or {}),
                    "raw_payload": json.dumps(raw_content),
                    "data_truth": json.dumps(
                        {
                            "source": "phyllo",
                            "source_detail": "phyllo.social.contents",
                            "confidence": "high",
                            "is_inferred": False,
                            "raw_payload_persisted": True,
                        }
                    ),
                    "engagement_rate_by_followers": item.get("engagement_rate_by_followers"),
                    "engagement_rate_by_reach": item.get("engagement_rate_by_reach"),
                    "performance_score": item.get("performance_score"),
                }
            )
        if not rows:
            return
        self.db.execute(
            text(
                """
                INSERT INTO social_connected_contents (
                  tenant_id,
                  onboarding_session_id,
                  environment,
                  provider,
                  phyllo_account_id,
                  external_id,
                  phyllo_content_id,
                  content_type,
                  content_format,
                  title,
                  content_url,
                  published_at,
                  metrics_json,
                  raw_payload,
                  data_truth,
                  engagement_rate_by_followers,
                  engagement_rate_by_reach,
                  performance_score,
                  observed_at,
                  updated_at
                )
                VALUES (
                  :tenant_id,
                  :session_id,
                  :environment,
                  :provider,
                  :phyllo_account_id,
                  :external_id,
                  :phyllo_content_id,
                  :content_type,
                  :content_format,
                  :title,
                  :content_url,
                  :published_at,
                  CAST(:metrics_json AS jsonb),
                  CAST(:raw_payload AS jsonb),
                  CAST(:data_truth AS jsonb),
                  :engagement_rate_by_followers,
                  :engagement_rate_by_reach,
                  :performance_score,
                  NOW(),
                  NOW()
                )
                ON CONFLICT (tenant_id, environment, provider, external_id)
                DO UPDATE SET
                  onboarding_session_id = EXCLUDED.onboarding_session_id,
                  phyllo_account_id = EXCLUDED.phyllo_account_id,
                  phyllo_content_id = EXCLUDED.phyllo_content_id,
                  content_type = EXCLUDED.content_type,
                  content_format = EXCLUDED.content_format,
                  title = EXCLUDED.title,
                  content_url = EXCLUDED.content_url,
                  published_at = EXCLUDED.published_at,
                  metrics_json = EXCLUDED.metrics_json,
                  raw_payload = EXCLUDED.raw_payload,
                  data_truth = EXCLUDED.data_truth,
                  engagement_rate_by_followers = EXCLUDED.engagement_rate_by_followers,
                  engagement_rate_by_reach = EXCLUDED.engagement_rate_by_reach,
                  performance_score = EXCLUDED.performance_score,
                  observed_at = NOW(),
                  updated_at = NOW()
                """
            ),
            rows,
        )

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
        row["analysis_report"] = _without_stale_specialist_analysis(row.get("analysis_report"))
        row["references"] = self._list_references(
            tenant_id=str(row["tenant_id"]),
            session_id=str(row["id"]),
        )
        return row

    def _get_active_action_plan(
        self,
        *,
        tenant_id: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        plan = self.db.execute(
            text(
                """
                SELECT *
                FROM social_action_plans
                WHERE tenant_id = :tenant_id
                  AND onboarding_session_id = :session_id
                  AND status = 'active'
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "session_id": session_id},
        ).mappings().first()
        if plan is None:
            return None
        items = self.db.execute(
            text(
                """
                SELECT *
                FROM social_action_plan_items
                WHERE tenant_id = :tenant_id
                  AND action_plan_id = :action_plan_id
                  AND status <> 'archived'
                ORDER BY position ASC, id ASC
                """
            ),
            {"tenant_id": tenant_id, "action_plan_id": str(plan["id"])},
        ).mappings().all()
        calendar_entries = self.db.execute(
            text(
                """
                SELECT *
                FROM social_content_calendar_entries
                WHERE tenant_id = :tenant_id
                  AND action_plan_id = :action_plan_id
                  AND status <> 'archived'
                ORDER BY day_index ASC, scheduled_at ASC, id ASC
                """
            ),
            {"tenant_id": tenant_id, "action_plan_id": str(plan["id"])},
        ).mappings().all()
        hydrated = dict(plan)
        hydrated["items"] = [dict(item) for item in items]
        hydrated["calendar_entries"] = [dict(entry) for entry in calendar_entries]
        return hydrated

    def _get_reference(
        self,
        *,
        tenant_id: str,
        session_id: str,
        reference_id: str,
    ) -> dict[str, Any]:
        row = self.db.execute(
            text(
                """
                WITH content_counts AS (
                  SELECT reference_profile_id, COUNT(*) AS public_contents_count
                  FROM social_public_reference_contents
                  WHERE reference_profile_id = (
                    SELECT public_reference_profile_id
                    FROM social_reference_profiles
                    WHERE tenant_id = :tenant_id
                      AND onboarding_session_id = :session_id
                      AND id = :reference_id
                      AND status = 'active'
                  )
                  GROUP BY reference_profile_id
                )
                SELECT
                  refs.*,
                  public_refs.sync_status AS global_sync_status,
                  public_refs.last_synced_at AS global_last_synced_at,
                  public_refs.data_truth AS data_truth,
                  COALESCE(content_counts.public_contents_count, 0) AS public_contents_count
                FROM social_reference_profiles AS refs
                LEFT JOIN social_public_reference_profiles AS public_refs
                  ON public_refs.id = refs.public_reference_profile_id
                LEFT JOIN content_counts
                  ON content_counts.reference_profile_id = refs.public_reference_profile_id
                WHERE refs.tenant_id = :tenant_id
                  AND refs.onboarding_session_id = :session_id
                  AND refs.id = :reference_id
                  AND refs.status = 'active'
                """
            ),
            {
                "tenant_id": tenant_id,
                "session_id": session_id,
                "reference_id": reference_id,
            },
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Referencia publica nao encontrada")
        return dict(row)

    def _list_references(self, *, tenant_id: str, session_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            text(
                """
                WITH refs AS (
                  SELECT *
                  FROM social_reference_profiles
                  WHERE tenant_id = :tenant_id
                    AND onboarding_session_id = :session_id
                    AND status = 'active'
                ),
                content_base AS (
                  SELECT c.*
                  FROM social_public_reference_contents c
                  WHERE c.reference_profile_id IN (
                    SELECT public_reference_profile_id
                    FROM refs
                    WHERE public_reference_profile_id IS NOT NULL
                  )
                ),
                content_counts AS (
                  SELECT reference_profile_id, COUNT(*) AS public_contents_count
                  FROM content_base
                  GROUP BY reference_profile_id
                ),
                content_stats AS (
                  SELECT
                    reference_profile_id,
                    jsonb_build_object(
                      'avg_likes', ROUND(AVG(COALESCE((metrics_json->>'likes')::numeric, 0)), 2),
                      'avg_comments',
                      ROUND(AVG(COALESCE((metrics_json->>'comments')::numeric, 0)), 2),
                      'avg_interactions', ROUND(
                        AVG(
                          COALESCE((metrics_json->>'likes')::numeric, 0)
                          + COALESCE((metrics_json->>'comments')::numeric, 0)
                          + COALESCE((metrics_json->>'shares')::numeric, 0)
                          + COALESCE((metrics_json->>'saves')::numeric, 0)
                        ),
                        2
                      ),
                      'avg_er_by_followers',
                      ROUND(AVG(COALESCE(engagement_rate_by_followers, 0)), 2),
                      'max_performance_score', ROUND(MAX(performance_score), 2)
                    ) AS content_stats
                  FROM content_base
                  GROUP BY reference_profile_id
                ),
                format_counts AS (
                  SELECT reference_profile_id, content_format, COUNT(*) AS format_count
                  FROM content_base
                  GROUP BY reference_profile_id, content_format
                ),
                format_rollups AS (
                  SELECT
                    reference_profile_id,
                    jsonb_object_agg(content_format, format_count ORDER BY format_count DESC)
                      AS format_distribution
                  FROM format_counts
                  GROUP BY reference_profile_id
                ),
                ranked_contents AS (
                  SELECT
                    c.*,
                    ROW_NUMBER() OVER (
                      PARTITION BY c.reference_profile_id
                      ORDER BY c.performance_score DESC NULLS LAST,
                               c.published_at DESC NULLS LAST,
                               c.id ASC
                    ) AS rank
                  FROM content_base c
                ),
                top_public_contents AS (
                  SELECT
                    reference_profile_id,
                    jsonb_agg(
                      jsonb_build_object(
                        'external_id', external_id,
                        'format', content_format,
                        'type', content_type,
                        'title', title,
                        'url', content_url,
                        'published_at', published_at,
                        'metrics', metrics_json,
                        'engagement_rate_by_followers', engagement_rate_by_followers,
                        'performance_score', performance_score
                      )
                      ORDER BY performance_score DESC NULLS LAST,
                               published_at DESC NULLS LAST
                    ) AS top_public_contents
                  FROM ranked_contents
                  WHERE rank <= 5
                  GROUP BY reference_profile_id
                )
                SELECT
                  refs.*,
                  public_refs.sync_status AS global_sync_status,
                  public_refs.source AS global_source,
                  public_refs.display_name AS global_display_name,
                  public_refs.profile_url AS global_profile_url,
                  public_refs.profile_snapshot AS public_profile_snapshot,
                  public_refs.last_synced_at AS global_last_synced_at,
                  public_refs.data_truth AS data_truth,
                  COALESCE(content_counts.public_contents_count, 0) AS public_contents_count,
                  COALESCE(content_stats.content_stats, '{}'::jsonb) AS public_content_stats,
                  COALESCE(format_rollups.format_distribution, '{}'::jsonb)
                    AS public_format_distribution,
                  COALESCE(top_public_contents.top_public_contents, '[]'::jsonb)
                    AS top_public_contents
                FROM refs
                LEFT JOIN social_public_reference_profiles AS public_refs
                  ON public_refs.id = refs.public_reference_profile_id
                LEFT JOIN content_counts
                  ON content_counts.reference_profile_id = refs.public_reference_profile_id
                LEFT JOIN content_stats
                  ON content_stats.reference_profile_id = refs.public_reference_profile_id
                LEFT JOIN format_rollups
                  ON format_rollups.reference_profile_id = refs.public_reference_profile_id
                LEFT JOIN top_public_contents
                  ON top_public_contents.reference_profile_id = refs.public_reference_profile_id
                ORDER BY refs.created_at ASC, refs.id ASC
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


def _without_stale_specialist_analysis(report: Any) -> Any:
    if not isinstance(report, dict):
        return report

    specialist = report.get("specialist_analysis")
    if not isinstance(specialist, dict):
        return report

    if specialist.get("version") == SOCIAL_SPECIALIST_ANALYSIS_VERSION:
        return report

    clean_report = dict(report)
    clean_report.pop("specialist_analysis", None)
    clean_report["specialist_analysis_stale"] = {
        "previous_version": specialist.get("version"),
        "status": specialist.get("status"),
        "reason": "contract_version_changed",
    }
    return clean_report


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
    if isinstance(data, dict) and not any(
        key in payload
        for key in (
            "id",
            "user",
            "account",
            "work_platform_id",
            "platform_id",
            "platform_username",
            "username",
            "handle",
        )
    ):
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


def _pick_number_top_level(payload: dict[str, Any], *, keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = payload.get(key)
        if value in (None, ""):
            continue
        try:
            return int(float(str(value).replace("%", "").strip()))
        except (TypeError, ValueError):
            continue
    return None


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
        item["_raw"] = content
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
        round(((total_interactions / analyzed_count) / followers_count) * 100, 2)
        if followers_count and analyzed_count
        else 0.0
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
        "_normalized_contents": normalized,
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


def _float_value(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _text_value(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    normalized = str(value).strip()
    return normalized or fallback


def _clamped_text(value: Any, fallback: str, *, limit: int = 500) -> str:
    normalized = _text_value(value, fallback)
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3].rstrip()}..."


def _ready_specialist_analysis(
    report: dict[str, Any],
    *,
    session: dict[str, Any],
) -> dict[str, Any] | None:
    analysis = report.get("specialist_analysis")
    if not isinstance(analysis, dict):
        return None
    if analysis.get("status") != "ready":
        return None
    if analysis.get("version") != SOCIAL_SPECIALIST_ANALYSIS_VERSION:
        return None
    if _int_value(analysis.get("analysis_version")) != _int_value(session.get("analysis_version")):
        return None
    return analysis


def _build_social_action_plan_payload(
    *,
    session: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    handle = _text_value(session.get("connected_account_handle"), "perfil")
    headline = _text_value(report.get("headline"), "Diagnostico social")
    analysis = _dict_value(report.get("specialist_analysis"))
    summary = _text_value(
        analysis.get("executive_summary"),
        f"Plano inicial derivado do diagnostico: {headline}.",
    )
    reference_context = _dict_value(report.get("reference_context"))
    content_metrics = _dict_value(report.get("content_metrics"))
    return {
        "title": f"Plano de acao social - @{handle}",
        "summary": _clamped_text(summary, f"Plano social para @{handle}.", limit=700),
        "metadata": {
            "source": "specialist_analysis",
            "truth_contract_version": _dict_value(report.get("truth_contract")).get("version"),
            "reference_status": reference_context.get("status"),
            "best_format": content_metrics.get("best_format"),
            "generated_from": {
                "session_id": str(session.get("id")),
                "analysis_version": _int_value(session.get("analysis_version")),
                "specialist_version": analysis.get("version"),
            },
        },
    }


def _normalize_social_action_items(
    *,
    specialist_analysis: dict[str, Any],
    report: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_items = _list_value(specialist_analysis.get("action_plan"))
    opportunities = _list_value(specialist_analysis.get("opportunities"))
    reference_context = _dict_value(report.get("reference_context"))
    content_metrics = _dict_value(report.get("content_metrics"))
    best_format = _text_value(content_metrics.get("best_format"), "REEL")

    items: list[dict[str, Any]] = []
    for raw in raw_items:
        item = _dict_value(raw)
        if not item:
            continue
        title = _clamped_text(item.get("title"), "Acao social prioritaria", limit=180)
        action = _clamped_text(item.get("action"), title, limit=900)
        why = _clamped_text(
            item.get("why_it_matters"),
            (
                "Esta acao deriva de sinais reais do perfil, dos posts analisados "
                "e das referencias sincronizadas."
            ),
            limit=900,
        )
        how = _clamped_text(
            item.get("how_to_execute"),
            (
                "Transforme a recomendacao em uma pauta curta, com gancho claro, "
                "prova e chamada para resposta."
            ),
            limit=900,
        )
        expected_signal = _clamped_text(
            item.get("expected_signal"),
            "Acompanhar comentarios, compartilhamentos, salvamentos e taxa de resposta.",
            limit=500,
        )
        measurement = _clamped_text(
            item.get("measurement"),
            "Comparar desempenho contra a media dos posts reais analisados.",
            limit=500,
        )
        evidence = _clamped_text(
            item.get("evidence"),
            "Evidencia derivada do diagnostico especialista e do truth contract.",
            limit=700,
        )
        priority = _text_value(item.get("priority"), "high").lower()
        if priority not in {"low", "medium", "high"}:
            priority = "high" if len(items) < 2 else "medium"
        items.append(
            {
                "title": title,
                "description": action,
                "why_it_matters": why,
                "how_to_execute": how,
                "expected_signal": expected_signal,
                "measurement": measurement,
                "evidence": evidence,
                "priority": priority,
                "source": {"provider": "specialist_analysis", "raw": item},
            }
        )

    fallback_sources = [
        {
            "title": "Refinar promessa da bio",
            "description": (
                "Reescrever a bio para deixar explicito para quem o perfil fala, "
                "qual dor resolve e qual proximo passo o publico deve tomar."
            ),
            "why_it_matters": (
                "A bio e o primeiro filtro de conversao. Promessa vaga reduz "
                "follow, clique e resposta."
            ),
            "how_to_execute": (
                "Criar 3 versoes de bio com publico, transformacao, prova e CTA; "
                "publicar a mais objetiva e medir efeitos por 7 dias."
            ),
            "expected_signal": "Aumento de cliques, follows novos e respostas qualificadas.",
            "measurement": (
                "Comparar follows e cliques dos 7 dias seguintes contra os 7 dias anteriores."
            ),
            "evidence": _clamped_text(
                _dict_value(report.get("profile")).get("bio"),
                (
                    "Bio lida no perfil conectado; tratar como oportunidade quando "
                    "a promessa nao estiver mensuravel."
                ),
                limit=700,
            ),
            "priority": "high",
        },
        {
            "title": f"Criar uma peca de prova social em formato {best_format}",
            "description": (
                "Publicar um conteudo com resultado, bastidor ou estudo de caso real "
                "em vez de uma dica generica."
            ),
            "why_it_matters": (
                "Os posts com prova concreta reduzem friccao e ajudam a audiencia "
                "a entender por que confiar no perfil."
            ),
            "how_to_execute": (
                "Abrir com uma situacao real, mostrar contexto, decisao tomada, "
                "resultado e uma pergunta final para conversa."
            ),
            "expected_signal": (
                "Mais comentarios salvos como duvidas, respostas e compartilhamentos."
            ),
            "measurement": "Medir interacoes por post e ER por seguidores contra a media atual.",
            "evidence": (
                "Top contents e referencias publicas indicam sinais de tracao em "
                "conteudos com narrativa pratica."
            ),
            "priority": "high",
        },
        {
            "title": "Extrair matriz dos melhores conteudos reais",
            "description": (
                "Separar os posts com maior sinal e quebrar cada um em gancho, "
                "promessa, prova, formato e CTA."
            ),
            "why_it_matters": (
                "A matriz evita criar do zero e transforma o que ja funcionou em "
                "sistema repetivel."
            ),
            "how_to_execute": (
                "Escolher 3 posts do perfil conectado e 3 posts das referencias; "
                "classificar padroes e gerar variacoes."
            ),
            "expected_signal": "Mais consistencia entre pauta, formato e resposta do publico.",
            "measurement": "Acompanhar variacao de interacoes por post durante o proximo ciclo.",
            "evidence": "Conteudos reais persistidos no diagnostico e referencias sincronizadas.",
            "priority": "medium",
        },
        {
            "title": "Fechar briefing semanal com limites de verdade",
            "description": (
                "Transformar o diagnostico em um briefing que separa fatos, calculos, "
                "inferencias e dados ausentes."
            ),
            "why_it_matters": (
                "Isso impede recomendacoes inventadas e deixa a operacao social auditavel."
            ),
            "how_to_execute": (
                "Usar somente dados presentes no truth contract; qualquer lacuna deve "
                "virar pergunta ou teste, nao afirmacao."
            ),
            "expected_signal": "Recomendacoes mais confiaveis e menos retrabalho editorial.",
            "measurement": (
                "Revisar semanalmente se cada recomendacao tem evidencia real associada."
            ),
            "evidence": _text_value(
                reference_context.get("truth_rule"),
                "Truth contract do diagnostico.",
            ),
            "priority": "medium",
        },
    ]
    for fallback in fallback_sources:
        if len(items) >= 6:
            break
        titles = {item["title"].lower() for item in items}
        if fallback["title"].lower() in titles:
            continue
        items.append({**fallback, "source": {"provider": "deterministic_fallback"}})

    for opportunity in opportunities[:2]:
        if len(items) >= 6:
            break
        raw = _dict_value(opportunity)
        title = _clamped_text(raw.get("title"), "Oportunidade prioritaria", limit=180)
        if title.lower() in {item["title"].lower() for item in items}:
            continue
        items.append(
            {
                "title": title,
                "description": _clamped_text(raw.get("action"), title, limit=900),
                "why_it_matters": _clamped_text(
                    raw.get("evidence"),
                    "Oportunidade apontada pela analise especialista.",
                    limit=900,
                ),
                "how_to_execute": (
                    "Transformar a oportunidade em uma pauta com gancho, evidencia "
                    "e CTA mensuravel."
                ),
                "expected_signal": "Mais resposta qualificada do publico.",
                "measurement": "Comparar interacoes por post contra a media do ciclo anterior.",
                "evidence": _clamped_text(
                    raw.get("evidence"),
                    "Oportunidade da analise especialista.",
                    limit=700,
                ),
                "priority": _text_value(raw.get("priority"), "medium").lower()
                if _text_value(raw.get("priority"), "medium").lower() in {"low", "medium", "high"}
                else "medium",
                "source": {"provider": "specialist_opportunity", "raw": raw},
            }
        )

    # Keep the first six actions compact enough for the operational view.
    return items[:6]


def _build_social_calendar_entries(
    *,
    items: list[dict[str, Any]],
    report: dict[str, Any],
    session: dict[str, Any],
) -> list[dict[str, Any]]:
    content_metrics = _dict_value(report.get("content_metrics"))
    benchmark = _dict_value(report.get("competitive_benchmark"))
    reference_profiles = _list_value(benchmark.get("reference_profiles"))
    source_reference_handle = None
    for raw_reference in reference_profiles:
        reference = _dict_value(raw_reference)
        if _int_value(reference.get("public_contents_count")):
            source_reference_handle = reference.get("handle")
            break

    best_format = _text_value(content_metrics.get("best_format"), "REEL").upper()
    format_cycle = [best_format, "CAROUSEL", "STORY", best_format, "IMAGE", "REEL", "CAROUSEL"]
    start_at = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    handle = _text_value(session.get("connected_account_handle"), "perfil")

    entries: list[dict[str, Any]] = []
    for index in range(7):
        item = items[index % len(items)] if items else {}
        day_index = index + 1
        content_format = format_cycle[index % len(format_cycle)]
        title = _clamped_text(
            item.get("title"),
            f"Pauta {day_index} para @{handle}",
            limit=180,
        )
        how_to_execute = _text_value(item.get("how_to_execute"), title)
        description = _text_value(item.get("description"), title)
        expected_signal = _text_value(item.get("expected_signal"), "Interacoes qualificadas")
        measurement = _text_value(item.get("measurement"), "Medir interacoes por post")
        evidence = _text_value(item.get("evidence"), "Dados reais do diagnostico")
        entries.append(
            {
                "action_position": (index % len(items)) + 1 if items else None,
                "scheduled_at": start_at + timedelta(days=index),
                "day_index": day_index,
                "title": f"Dia {day_index}: {title}",
                "format": content_format,
                "channel": "instagram",
                "theme": title,
                "hook": _clamped_text(how_to_execute, title, limit=700),
                "caption_outline": _clamped_text(
                    f"{description} Sinal esperado: {expected_signal}.",
                    description,
                    limit=1000,
                ),
                "cta": (
                    "Convide o publico a comentar, salvar ou responder com uma duvida especifica."
                ),
                "evidence": _clamped_text(evidence, "Dados reais do diagnostico.", limit=700),
                "objective": _clamped_text(measurement, "Medir interacoes por post.", limit=500),
                "source_reference_handle": source_reference_handle,
                "metrics_goal": {
                    "primary": "interactions_per_content",
                    "secondary": "engagement_rate_by_followers",
                    "baseline_interactions": _float_value(content_metrics.get("interactions")),
                    "baseline_er_followers": _float_value(
                        content_metrics.get("engagement_rate_by_followers")
                    ),
                },
                "metadata": {
                    "generated_by": "labby_social_calendar_v1",
                    "truth_contract_version": _dict_value(
                        report.get("truth_contract")
                    ).get("version"),
                    "source_handle": handle,
                    "format_basis": content_format,
                },
            }
        )
    return entries


def _top_count_key(values: dict[str, int]) -> str | None:
    if not values:
        return None
    return max(values.items(), key=lambda item: item[1])[0]


def _top_numeric_key(values: dict[str, Any]) -> str | None:
    normalized = {str(key): _float_value(value) for key, value in values.items()}
    normalized = {key: value for key, value in normalized.items() if value > 0}
    if not normalized:
        return None
    return max(normalized.items(), key=lambda item: item[1])[0]


def _content_metric(metrics: dict[str, Any], key: str) -> float:
    return _float_value(metrics.get(key))


def _compact_connected_contents(
    contents: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for item in contents[:limit]:
        metrics = _dict_value(item.get("metrics"))
        compacted.append(
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "type": item.get("type"),
                "format": item.get("format"),
                "published_at": item.get("published_at"),
                "metrics": {
                    "likes": _content_metric(metrics, "likes"),
                    "comments": _content_metric(metrics, "comments"),
                    "shares": _content_metric(metrics, "shares"),
                    "saves": _content_metric(metrics, "saves"),
                    "views": _content_metric(metrics, "views"),
                    "reach": _content_metric(metrics, "reach"),
                },
                "engagement_rate_by_followers": _float_value(
                    item.get("engagement_rate_by_followers")
                ),
                "engagement_rate_by_reach": _float_value(item.get("engagement_rate_by_reach")),
                "performance_score": _float_value(item.get("performance_score")),
            }
        )
    return compacted


def _compact_public_contents(
    contents: list[Any],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for raw_item in contents[:limit]:
        item = _dict_value(raw_item)
        metrics = _dict_value(item.get("metrics"))
        compacted.append(
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "type": item.get("type"),
                "format": item.get("format"),
                "published_at": str(item.get("published_at")) if item.get("published_at") else None,
                "metrics": {
                    "likes": _content_metric(metrics, "likes"),
                    "comments": _content_metric(metrics, "comments"),
                    "shares": _content_metric(metrics, "shares"),
                    "saves": _content_metric(metrics, "saves"),
                    "views": _content_metric(metrics, "views"),
                    "reach": _content_metric(metrics, "reach"),
                },
                "engagement_rate_by_followers": _float_value(
                    item.get("engagement_rate_by_followers")
                ),
                "performance_score": _float_value(item.get("performance_score")),
            }
        )
    return compacted


def _manual_reference_truth() -> dict[str, Any]:
    return {
        "source": "manual_input",
        "confidence": "medium",
        "is_inferred": False,
        "public_data_synced": False,
        "rule": (
            "Handle informado pelo usuario. Nao usar metricas, audiencia ou conteudos "
            "da referencia ate a sincronizacao publica por fonte configurada."
        ),
    }


def _public_reference_needs_sync(
    reference: dict[str, Any],
    *,
    circuit_breaker_failures: int,
) -> bool:
    status = str(reference.get("sync_status") or "manual_pending")
    if status == "manual_pending":
        return True
    if status in {"pending", "syncing"}:
        return False
    failure_count = int(reference.get("failure_count") or 0)
    if status in {"failed", "unavailable", "partially_synced"}:
        if failure_count >= max(1, circuit_breaker_failures):
            return False
    next_sync_after = reference.get("next_sync_after")
    if next_sync_after is None:
        return True
    if isinstance(next_sync_after, datetime):
        now = datetime.now(tz=next_sync_after.tzinfo)
        return next_sync_after <= now
    return False


def _public_reference_job_can_attempt(
    reference: dict[str, Any],
    *,
    circuit_breaker_failures: int,
) -> bool:
    if str(reference.get("sync_status") or "") == "pending":
        return True
    return _public_reference_needs_sync(
        reference,
        circuit_breaker_failures=circuit_breaker_failures,
    )


def _normalize_apify_instagram_profile(
    payload: dict[str, Any],
    *,
    fallback_handle: str,
) -> dict[str, Any]:
    handle = (
        _pick_text(payload, keys=("username", "userName", "handle", "ownerUsername"))
        or fallback_handle
    )
    handle = _normalize_handle(handle)
    profile_url = (
        _pick_text(payload, keys=("url", "profileUrl", "profile_url"))
        or f"https://www.instagram.com/{handle}/"
    )
    return {
        "provider": "instagram",
        "handle": handle,
        "display_name": _pick_text(payload, keys=("fullName", "displayName", "name"))
        or handle,
        "profile_url": profile_url,
        "profile_image_url": _pick_text(
            payload,
            keys=("profilePicUrl", "profile_pic_url", "profileImageUrl", "profile_image_url"),
        ),
        "bio": _pick_text(payload, keys=("biography", "bio", "description")),
        "website": _pick_text(payload, keys=("externalUrl", "website", "websiteUrl")),
        "followers_count": _pick_number(
            payload,
            keys=("followersCount", "followers_count", "followerCount", "followers"),
        ),
        "following_count": _pick_number(
            payload,
            keys=("followsCount", "followingCount", "following_count", "follows"),
        ),
        "posts_count": _pick_number(payload, keys=("postsCount", "mediaCount", "posts_count")),
        "is_business": _pick_bool(
            payload,
            keys=("isBusinessAccount", "businessAccount", "is_business"),
        ),
        "is_verified": _pick_bool(payload, keys=("verified", "isVerified", "is_verified")),
        "is_private": _pick_bool(payload, keys=("private", "isPrivate", "is_private")),
        "source": "apify",
        "connection_mode": "public_reference",
        "public_data_only": True,
    }


def _minimize_apify_profile_raw(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: payload.get(key)
        for key in (
            "username",
            "fullName",
            "url",
            "profilePicUrl",
            "followersCount",
            "followsCount",
            "postsCount",
            "biography",
            "externalUrl",
            "private",
            "verified",
            "isBusinessAccount",
        )
        if key in payload
    }


def _minimize_apify_post_raw(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: payload.get(key)
        for key in (
            "id",
            "shortCode",
            "url",
            "caption",
            "timestamp",
            "productType",
            "likesCount",
            "commentsCount",
            "videoViewCount",
            "videoPlayCount",
            "viewsCount",
            "isPinned",
            "isCommentsDisabled",
        )
        if key in payload
    }


def _normalize_apify_instagram_post(
    payload: dict[str, Any],
    *,
    followers_count: int,
) -> dict[str, Any]:
    shortcode = _pick_text(payload, keys=("shortCode", "shortcode", "code"))
    url = _pick_text(payload, keys=("url", "postUrl", "displayUrl"))
    external_id = (
        _pick_text(payload, keys=("id", "external_id", "externalId"))
        or shortcode
        or url
        or ""
    )
    product_type = (
        _pick_text(payload, keys=("productType", "type", "mediaType")) or "UNKNOWN"
    ).upper()
    if product_type in {"CLIPS", "REELS"}:
        content_type = "REELS"
        content_format = "VIDEO"
    elif "VIDEO" in product_type:
        content_type = "VIDEO"
        content_format = "VIDEO"
    elif "CAROUSEL" in product_type or "SIDE" in product_type:
        content_type = "CAROUSEL"
        content_format = "CAROUSEL"
    else:
        content_type = "POST"
        content_format = "IMAGE"

    likes = _pick_number_top_level(payload, keys=("likesCount", "likeCount", "likes"))
    comments = _pick_number_top_level(payload, keys=("commentsCount", "commentCount", "comments"))
    views = _pick_number_top_level(
        payload,
        keys=("videoViewCount", "videoPlayCount", "viewsCount", "views", "playsCount"),
    )
    metrics = {
        "likes": likes,
        "comments": comments,
        "views": views,
        "shares": None,
        "saves": None,
        "reach": None,
        "impressions": None,
    }
    unavailable_metrics = [
        key
        for key, value in metrics.items()
        if value is None
    ]
    interaction_count = (likes or 0) + (comments or 0)
    performance_score = (likes or 0) + (comments or 0) * 4 + (views or 0) * 0.02
    if not url and shortcode:
        url = f"https://www.instagram.com/p/{shortcode}/"
    return {
        "id": str(payload.get("id") or ""),
        "external_id": str(external_id),
        "type": content_type,
        "format": content_format,
        "url": url,
        "published_at": _pick_text(payload, keys=("timestamp", "publishedAt", "takenAt")),
        "title": _pick_text(payload, keys=("caption", "text", "title")),
        "metrics": metrics,
        "engagement_rate_by_followers": round((interaction_count / followers_count) * 100, 2)
        if followers_count
        else 0.0,
        "engagement_rate_by_reach": None,
        "performance_score": round(performance_score, 2),
        "unavailable_metrics": unavailable_metrics,
        "_raw": payload,
    }


def _build_reference_context(references: list[dict[str, Any]]) -> dict[str, Any]:
    declared = []
    references_with_public_data = 0
    public_contents_total = 0
    for reference in references:
        public_contents_count = int(reference.get("public_contents_count") or 0)
        sync_status = (
            reference.get("global_sync_status")
            or reference.get("sync_status")
            or "manual_pending"
        )
        if public_contents_count:
            references_with_public_data += 1
            public_contents_total += public_contents_count
        profile_snapshot = _dict_value(reference.get("public_profile_snapshot"))
        content_stats = _dict_value(reference.get("public_content_stats"))
        format_distribution = _dict_value(reference.get("public_format_distribution"))
        declared.append(
            {
                "id": str(reference.get("id")),
                "public_reference_profile_id": (
                    str(reference["public_reference_profile_id"])
                    if reference.get("public_reference_profile_id")
                    else None
                ),
                "provider": reference.get("provider"),
                "handle": reference.get("handle"),
                "label": reference.get("label"),
                "sync_status": sync_status,
                "public_contents_count": public_contents_count,
                "source": reference.get("global_source") or profile_snapshot.get("source"),
                "display_name": (
                    reference.get("global_display_name")
                    or profile_snapshot.get("display_name")
                    or reference.get("label")
                ),
                "followers_count": _int_value(profile_snapshot.get("followers_count")),
                "posts_count": _int_value(profile_snapshot.get("posts_count")),
                "format_distribution": format_distribution,
                "content_stats": {
                    "avg_likes": _float_value(content_stats.get("avg_likes")),
                    "avg_comments": _float_value(content_stats.get("avg_comments")),
                    "avg_interactions": _float_value(content_stats.get("avg_interactions")),
                    "avg_er_by_followers": _float_value(
                        content_stats.get("avg_er_by_followers")
                    ),
                    "max_performance_score": _float_value(
                        content_stats.get("max_performance_score")
                    ),
                },
                "top_contents": _compact_public_contents(
                    _list_value(reference.get("top_public_contents")),
                    limit=3,
                ),
            }
        )

    declared_count = len(declared)
    if declared_count == 0:
        status = "missing"
        insight = "Adicione 3 a 5 referencias para calibrar melhor o diagnostico."
        next_step = "adicionar 3 a 5 referencias publicas do mesmo segmento"
    elif references_with_public_data == 0:
        status = "manual_only"
        insight = (
            "Referencias informadas; comparativo real aguarda sincronizacao publica "
            "pela infraestrutura da Labby."
        )
        next_step = "aguardar a sincronizacao dos dados publicos antes de comparar performance"
    elif references_with_public_data < min(3, declared_count):
        status = "partially_synced"
        insight = "Benchmark parcialmente pronto; faltam dados publicos de algumas referencias."
        next_step = "completar sincronizacao publica das referencias restantes"
    else:
        status = "synced"
        insight = "Benchmark pronto para comparar conteudos reais do mesmo segmento."
        next_step = "gerar comparativo por formato, alcance e sinais de distribuicao"

    return {
        "status": status,
        "minimum_references": 3,
        "declared_count": declared_count,
        "references_with_public_data": references_with_public_data,
        "public_contents_total": public_contents_total,
        "references": declared,
        "insight": insight,
        "next_step": next_step,
        "truth_rule": (
            "Referencias manuais calibram contexto. Comparativos de performance so podem "
            "usar dados publicos sincronizados por fonte configurada e auditavel."
        ),
    }


def _build_competitive_benchmark(
    *,
    snapshot: dict[str, Any],
    content_metrics: dict[str, Any],
    top_contents: list[dict[str, Any]],
    references: list[dict[str, Any]],
    reference_context: dict[str, Any],
) -> dict[str, Any]:
    connected_followers = _int_value(snapshot.get("followers_count"))
    connected_contents = _int_value(snapshot.get("content_items_count"))
    connected_interactions = _float_value(content_metrics.get("interactions"))
    connected_avg_interactions = (
        round(connected_interactions / connected_contents, 2) if connected_contents else 0.0
    )
    connected_best_format = str(content_metrics.get("best_format") or "")
    connected = {
        "handle": snapshot.get("handle"),
        "display_name": snapshot.get("display_name"),
        "followers_count": connected_followers,
        "posts_count": _int_value(snapshot.get("posts_count")),
        "contents_analyzed": connected_contents,
        "best_format": connected_best_format or None,
        "avg_interactions_per_content": connected_avg_interactions,
        "engagement_rate_by_followers": _float_value(
            content_metrics.get("engagement_rate_by_followers")
        ),
        "engagement_rate_by_reach": _float_value(
            content_metrics.get("engagement_rate_by_reach")
        ),
        "top_contents": _compact_connected_contents(top_contents, limit=5),
    }

    reference_profiles: list[dict[str, Any]] = []
    for reference in references:
        profile_snapshot = _dict_value(reference.get("public_profile_snapshot"))
        content_stats = _dict_value(reference.get("public_content_stats"))
        format_distribution = _dict_value(reference.get("public_format_distribution"))
        top_public_contents = _compact_public_contents(
            _list_value(reference.get("top_public_contents")),
            limit=5,
        )
        public_contents_count = _int_value(reference.get("public_contents_count"))
        if not public_contents_count:
            continue
        followers_count = _int_value(profile_snapshot.get("followers_count"))
        avg_interactions = _float_value(content_stats.get("avg_interactions"))
        avg_er_followers = _float_value(content_stats.get("avg_er_by_followers"))
        top_format = _top_numeric_key(format_distribution)
        reference_profiles.append(
            {
                "handle": reference.get("handle"),
                "display_name": (
                    reference.get("global_display_name")
                    or profile_snapshot.get("display_name")
                    or reference.get("label")
                ),
                "source": reference.get("global_source") or profile_snapshot.get("source"),
                "sync_status": (
                    reference.get("global_sync_status")
                    or reference.get("sync_status")
                    or "manual_pending"
                ),
                "followers_count": followers_count,
                "posts_count": _int_value(profile_snapshot.get("posts_count")),
                "public_contents_count": public_contents_count,
                "format_distribution": format_distribution,
                "top_format": top_format,
                "avg_likes": _float_value(content_stats.get("avg_likes")),
                "avg_comments": _float_value(content_stats.get("avg_comments")),
                "avg_interactions_per_content": avg_interactions,
                "avg_er_by_followers": avg_er_followers,
                "scale_vs_connected_followers": (
                    round(followers_count / connected_followers, 1)
                    if followers_count and connected_followers
                    else None
                ),
                "interactions_gap_vs_connected": (
                    round(avg_interactions - connected_avg_interactions, 2)
                    if avg_interactions or connected_avg_interactions
                    else None
                ),
                "top_contents": top_public_contents,
            }
        )

    reference_avg_interactions = (
        round(
            sum(_float_value(ref.get("avg_interactions_per_content")) for ref in reference_profiles)
            / len(reference_profiles),
            2,
        )
        if reference_profiles
        else 0.0
    )
    reference_avg_er_followers = (
        round(
            sum(_float_value(ref.get("avg_er_by_followers")) for ref in reference_profiles)
            / len(reference_profiles),
            2,
        )
        if reference_profiles
        else 0.0
    )
    dominant_reference_formats: dict[str, int] = {}
    for ref in reference_profiles:
        top_format = str(ref.get("top_format") or "").strip()
        if top_format:
            dominant_reference_formats[top_format] = (
                dominant_reference_formats.get(top_format, 0) + 1
            )
    dominant_reference_format = _top_count_key(dominant_reference_formats)

    findings: list[dict[str, Any]] = []
    if reference_profiles:
        findings.append(
            {
                "title": "Base real de benchmark",
                "finding": (
                    f"{len(reference_profiles)} referencias sincronizadas com "
                    f"{reference_context.get('public_contents_total', 0)} posts publicos."
                ),
                "evidence": ", ".join(
                    f"@{ref['handle']} ({ref['public_contents_count']} posts)"
                    for ref in reference_profiles[:5]
                ),
                "confidence": "high",
            }
        )
        if connected_avg_interactions or reference_avg_interactions:
            delta = round(reference_avg_interactions - connected_avg_interactions, 2)
            findings.append(
                {
                    "title": "Diferenca de interacoes medias por post",
                    "finding": (
                        f"Perfil conectado: {connected_avg_interactions:.2f}; "
                        f"referencias: {reference_avg_interactions:.2f}; delta: {delta:.2f}."
                    ),
                    "evidence": (
                        "Calculo normalizado por post para evitar comparar apenas volume bruto."
                    ),
                    "confidence": "medium",
                }
            )
        if dominant_reference_format:
            findings.append(
                {
                    "title": "Formato dominante nas referencias",
                    "finding": (
                        f"Formato mais frequente entre referencias: {dominant_reference_format}; "
                        f"perfil conectado: {connected_best_format or 'nao definido'}."
                    ),
                    "evidence": "Distribuicao de formatos dos posts publicos sincronizados.",
                    "confidence": "medium",
                }
            )

    return {
        "version": "competitive_benchmark_v1",
        "method": (
            "Compara apenas dados publicos sincronizados e dados conectados autorizados. "
            "Volume bruto e normalizado por seguidores/post para reduzir vies de escala."
        ),
        "connected_profile": connected,
        "reference_profiles": reference_profiles,
        "aggregate": {
            "references_with_data": len(reference_profiles),
            "public_contents_total": int(reference_context.get("public_contents_total") or 0),
            "reference_avg_interactions_per_content": reference_avg_interactions,
            "reference_avg_er_by_followers": reference_avg_er_followers,
            "dominant_reference_format": dominant_reference_format,
        },
        "findings": findings,
        "truth_limits": [
            "Referencias publicas nao retornam demografia privada.",
            (
                "Apify retorna likes e comentarios publicos; saves, shares e reach podem "
                "estar ausentes."
            ),
            "Comparacoes de performance usam taxas e medias, nao apenas tamanho do perfil.",
        ],
    }


def _build_specialist_brief(
    *,
    snapshot: dict[str, Any],
    content_metrics: dict[str, Any],
    top_contents: list[dict[str, Any]],
    segment: dict[str, Any],
    reference_context: dict[str, Any],
    competitive_benchmark: dict[str, Any],
) -> dict[str, Any]:
    contents_analyzed = int(snapshot.get("content_items_count") or 0)
    has_profile_facts = bool(snapshot.get("followers_count") or snapshot.get("bio"))
    has_content_facts = contents_analyzed > 0 and bool(top_contents)
    has_reference_facts = reference_context["references_with_public_data"] > 0
    mode = "profile_only"
    if has_reference_facts:
        mode = "profile_plus_references"
    elif reference_context["declared_count"]:
        mode = "profile_plus_manual_reference_context"

    blocked_inputs = []
    if not has_content_facts:
        blocked_inputs.append("post_level_engagement")
    if not has_reference_facts:
        blocked_inputs.append("public_reference_performance")
    blocked_inputs.append("audience_demographics")

    return {
        "version": "social_specialist_brief_v1",
        "analysis_mode": mode,
        "ready_for_ai": bool(has_profile_facts and has_content_facts),
        "segment_hypothesis": {
            "name": segment.get("name"),
            "confidence": segment.get("confidence"),
            "is_inferred": True,
            "evidence": segment.get("signals", []),
        },
        "inputs": {
            "profile_snapshot": {
                "source": snapshot.get("source") or "unknown",
                "followers_count": int(snapshot.get("followers_count") or 0),
                "posts_count": int(snapshot.get("posts_count") or 0),
                "bio_present": bool(snapshot.get("bio")),
            },
            "connected_contents": {
                "count": contents_analyzed,
                "best_format": content_metrics.get("best_format"),
                "engagement_rate_by_reach": content_metrics.get("engagement_rate_by_reach"),
                "engagement_rate_by_followers": content_metrics.get(
                    "engagement_rate_by_followers"
                ),
            },
            "references": {
                "declared_count": reference_context["declared_count"],
                "synced_count": reference_context["references_with_public_data"],
                "public_contents_total": reference_context["public_contents_total"],
            },
            "competitive_benchmark": {
                "references_with_data": competitive_benchmark["aggregate"][
                    "references_with_data"
                ],
                "reference_avg_interactions_per_content": competitive_benchmark[
                    "aggregate"
                ]["reference_avg_interactions_per_content"],
                "dominant_reference_format": competitive_benchmark["aggregate"][
                    "dominant_reference_format"
                ],
            },
        },
        "guardrails": [
            "Nao afirmar demografia sem dado retornado por fonte conectada.",
            "Nao comparar referencias sem conteudos publicos sincronizados.",
            "Usar top_contents reais como evidencia para toda recomendacao de formato.",
            "Separar fato, calculo e inferencia em qualquer resposta gerada por IA.",
        ],
        "blocked_inputs": blocked_inputs,
        "next_analysis_step": reference_context["next_step"],
    }


def _build_specialist_analysis_input(
    *,
    session: dict[str, Any],
    report: dict[str, Any],
    analysis_version: int,
) -> dict[str, Any]:
    clean_report = dict(report)
    clean_report.pop("specialist_analysis", None)
    top_contents = clean_report.get("top_contents")
    if isinstance(top_contents, list):
        clean_report["top_contents"] = top_contents[:12]
    observed = clean_report.get("observed_facts")
    if isinstance(observed, list):
        clean_report["observed_facts"] = observed[:10]
    computed = clean_report.get("computed_insights")
    if isinstance(computed, list):
        clean_report["computed_insights"] = computed[:10]
    inferred = clean_report.get("inferred_insights")
    if isinstance(inferred, list):
        clean_report["inferred_insights"] = inferred[:8]
    missing = clean_report.get("missing_data")
    if isinstance(missing, list):
        clean_report["missing_data"] = missing[:8]
    return {
        "version": "social_specialist_analysis_input_v1",
        "analysis_version": analysis_version,
        "session": {
            "id": str(session.get("id")),
            "objective": session.get("objective"),
            "primary_provider": session.get("primary_provider"),
            "connection_mode": session.get("connection_mode"),
            "connected_account_handle": session.get("connected_account_handle"),
            "connected_account_name": session.get("connected_account_name"),
        },
        "report": clean_report,
        "non_negotiable_rules": [
            "Nao inventar dado ausente.",
            "Nao afirmar demografia sem fonte conectada.",
            "Nao usar dados privados de referencias publicas.",
            "Toda recomendacao precisa citar evidencia real ou declarar baixa confianca.",
            "Separar fatos, calculos e inferencias.",
        ],
    }


def _analysis_report_needs_benchmark_refresh(
    *,
    current_report: dict[str, Any],
    rebuilt_report: dict[str, Any],
) -> bool:
    if not current_report:
        return bool(rebuilt_report)

    current_context = _dict_value(current_report.get("reference_context"))
    rebuilt_context = _dict_value(rebuilt_report.get("reference_context"))
    if _int_value(rebuilt_context.get("references_with_public_data")) > _int_value(
        current_context.get("references_with_public_data")
    ):
        return True
    if _int_value(rebuilt_context.get("public_contents_total")) > _int_value(
        current_context.get("public_contents_total")
    ):
        return True

    current_benchmark = _dict_value(current_report.get("competitive_benchmark"))
    rebuilt_benchmark = _dict_value(rebuilt_report.get("competitive_benchmark"))
    current_references = _list_value(current_benchmark.get("reference_profiles"))
    rebuilt_references = _list_value(rebuilt_benchmark.get("reference_profiles"))
    if len(rebuilt_references) > len(current_references):
        return True

    current_handles = {
        str(item.get("handle") or "").strip().lower()
        for item in current_references
        if isinstance(item, dict)
    }
    rebuilt_handles = {
        str(item.get("handle") or "").strip().lower()
        for item in rebuilt_references
        if isinstance(item, dict)
    }
    if rebuilt_handles and rebuilt_handles != current_handles:
        return True

    current_connected = _dict_value(current_benchmark.get("connected_profile"))
    rebuilt_connected = _dict_value(rebuilt_benchmark.get("connected_profile"))
    if _int_value(rebuilt_connected.get("followers_count")) > _int_value(
        current_connected.get("followers_count")
    ):
        return True
    if _int_value(rebuilt_connected.get("contents_analyzed")) > _int_value(
        current_connected.get("contents_analyzed")
    ):
        return True
    return False


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
    snapshot_quality = (
        snapshot.get("data_quality") if isinstance(snapshot.get("data_quality"), dict) else {}
    )
    real_engagement = float(content_metrics.get("engagement_rate_by_reach") or 0) or float(
        content_metrics.get("engagement_rate_by_followers") or 0
    )
    effective_engagement = real_engagement or engagement
    reference_handles = [f"@{ref['handle']}" for ref in references[:5]]
    reference_context = _build_reference_context(references)
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
    benchmark_fit = min(
        100,
        42
        + min(reference_context["declared_count"] * 5, 20)
        + min(reference_context["references_with_public_data"] * 11, 38),
    )
    engagement_score = min(100, 38 + int(effective_engagement * 7) + min(contents_analyzed * 3, 18))
    top_content_lines = _top_content_lines(top_contents)
    competitive_benchmark = _build_competitive_benchmark(
        snapshot=snapshot,
        content_metrics=content_metrics,
        top_contents=top_contents,
        references=references,
        reference_context=reference_context,
    )
    truth = _build_truth_sections(
        snapshot=snapshot,
        content_metrics=content_metrics,
        top_contents=top_contents,
        segment=segment,
        scores={
            "profile_strength": strength,
            "content_consistency": consistency,
            "engagement_readiness": engagement_score,
            "benchmark_fit": benchmark_fit,
        },
        references=reference_handles,
        reference_context=reference_context,
    )
    specialist_brief = _build_specialist_brief(
        snapshot=snapshot,
        content_metrics=content_metrics,
        top_contents=top_contents,
        segment=segment,
        reference_context=reference_context,
        competitive_benchmark=competitive_benchmark,
    )

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
            "has_real_engagement": bool(
                snapshot_quality.get("has_real_engagement", contents_analyzed > 0)
            ),
            "content_sync_status": snapshot_quality.get("content_sync_status"),
            "content_sync_error": snapshot_quality.get("content_sync_error"),
        },
        "observed_facts": truth["observed_facts"],
        "computed_insights": truth["computed_insights"],
        "inferred_insights": truth["inferred_insights"],
        "missing_data": truth["missing_data"],
        "truth_contract": truth["truth_contract"],
        "content_metrics": content_metrics,
        "top_contents": top_contents,
        "reference_context": reference_context,
        "competitive_benchmark": competitive_benchmark,
        "specialist_brief": specialist_brief,
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
            "insight": reference_context["insight"],
        },
        "next_actions": [
            "validar a promessa da bio contra o publico-alvo principal",
            "separar os 3 conteudos com maior reach/view para mapear formato e gancho",
            reference_context["next_step"],
        ],
    }


def _build_truth_sections(
    *,
    snapshot: dict[str, Any],
    content_metrics: dict[str, Any],
    top_contents: list[dict[str, Any]],
    segment: dict[str, Any],
    scores: dict[str, int],
    references: list[str],
    reference_context: dict[str, Any],
) -> dict[str, Any]:
    contents_analyzed = int(snapshot.get("content_items_count") or 0)
    content_sync_status = None
    snapshot_quality = snapshot.get("data_quality")
    if isinstance(snapshot_quality, dict):
        content_sync_status = snapshot_quality.get("content_sync_status")

    observed_facts = [
        _truth_item(
            key="followers_count",
            label="Seguidores lidos",
            value=int(snapshot.get("followers_count") or 0),
            source="phyllo.profile",
            confidence="high",
            evidence="Campo follower_count/followers_count retornado pela Phyllo.",
        ),
        _truth_item(
            key="posts_count",
            label="Posts no perfil",
            value=int(snapshot.get("posts_count") or 0),
            source="phyllo.profile",
            confidence="high",
            evidence="Campo content_count/media_count retornado pela Phyllo.",
        ),
        _truth_item(
            key="contents_analyzed",
            label="Conteudos reais analisados",
            value=contents_analyzed,
            source="phyllo.social.contents",
            confidence="high" if contents_analyzed else "low",
            evidence="Posts persistidos em social_connected_contents com payload bruto.",
        ),
    ]
    if snapshot.get("bio"):
        observed_facts.append(
            _truth_item(
                key="bio",
                label="Bio do perfil",
                value=snapshot.get("bio"),
                source="phyllo.profile",
                confidence="high",
                evidence="Texto de bio retornado pela fonte conectada.",
            )
        )
    if snapshot.get("website"):
        observed_facts.append(
            _truth_item(
                key="website",
                label="Link do perfil",
                value=snapshot.get("website"),
                source="phyllo.profile",
                confidence="high",
                evidence="URL retornada pela fonte conectada.",
            )
        )

    computed_insights = [
        _truth_item(
            key="engagement_rate_by_followers",
            label="ER medio por seguidores",
            value=content_metrics.get("engagement_rate_by_followers"),
            source="labby.calculation.v1",
            confidence="high" if contents_analyzed else "low",
            evidence="Media por conteudo: interacoes do post divididas por seguidores.",
            method="avg((likes + comments + shares + saves) / followers) * 100",
        ),
        _truth_item(
            key="engagement_rate_by_reach",
            label="ER por alcance/views",
            value=content_metrics.get("engagement_rate_by_reach"),
            source="labby.calculation.v1",
            confidence="high" if contents_analyzed else "low",
            evidence="Interacoes totais divididas por reach/views disponivel.",
            method="sum(interactions) / sum(reach_or_views) * 100",
        ),
        _truth_item(
            key="best_format",
            label="Formato mais recorrente",
            value=content_metrics.get("best_format"),
            source="labby.calculation.v1",
            confidence="medium" if contents_analyzed else "low",
            evidence="Contagem simples dos formatos retornados na amostra.",
        ),
    ]
    for score_key, score in scores.items():
        computed_insights.append(
            _truth_item(
                key=f"score_{score_key}",
                label=f"Score {score_key}",
                value=score,
                source="labby.scoring.v1",
                confidence="medium",
                evidence=(
                    "Score calculado por regras deterministicas a partir do perfil "
                    "e posts reais."
                ),
            )
        )

    inferred_insights = [
        _truth_item(
            key="segment",
            label="Segmento sugerido",
            value=segment.get("name"),
            source="labby.inference.v1",
            confidence="medium",
            is_inferred=True,
            evidence="Inferencia baseada em handle, bio, nome do perfil e referencias informadas.",
        ),
        _truth_item(
            key="audience_hypothesis",
            label="Hipotese de publico",
            value="Derivada do posicionamento do perfil, nao de dados demograficos.",
            source="labby.inference.v1",
            confidence="low",
            is_inferred=True,
            evidence="A API atual nao retornou idade, genero ou localizacao da audiencia.",
        ),
    ]

    missing_data = []
    if not contents_analyzed:
        missing_data.append(
            _missing_item(
                key="content_engagement",
                label="Posts com metricas de engajamento",
                reason="A fonte ainda nao retornou conteudos ou a sincronizacao falhou.",
                next_step="Reprocessar quando a Phyllo concluir a sincronizacao de engagement.",
            )
        )
    if not references:
        missing_data.append(
            _missing_item(
                key="reference_profiles",
                label="Perfis publicos de referencia",
                reason=(
                    "O cliente ainda nao informou referencias publicas para calibrar "
                    "comparativo externo."
                ),
                next_step="Adicionar 3 a 5 referencias do mesmo segmento.",
            )
        )
    elif not reference_context["references_with_public_data"]:
        missing_data.append(
            _missing_item(
                key="reference_public_metrics",
                label="Metricas publicas das referencias",
                reason=(
                    "As referencias foram informadas, mas nenhum conteudo publico "
                    "delas foi sincronizado ainda."
                ),
                next_step=reference_context["next_step"],
            )
        )
    missing_data.append(
        _missing_item(
            key="audience_demographics",
            label="Demografia da audiencia",
            reason="A fonte conectada nao retornou idade, genero ou localizacao neste escopo.",
            next_step="Tratar como dado ausente; nao usar como fato no diagnostico.",
        )
    )

    return {
        "truth_contract": {
            "version": "social_profile_truth_v1",
            "rule": (
                "Facts come from provider payloads; calculations are deterministic; "
                "inferences are labeled."
            ),
            "content_sync_status": content_sync_status or "unknown",
        },
        "observed_facts": observed_facts,
        "computed_insights": computed_insights,
        "inferred_insights": inferred_insights,
        "missing_data": missing_data,
    }


def _truth_item(
    *,
    key: str,
    label: str,
    value: Any,
    source: str,
    confidence: str,
    evidence: str,
    is_inferred: bool = False,
    method: str | None = None,
) -> dict[str, Any]:
    item = {
        "key": key,
        "label": label,
        "value": value,
        "source": source,
        "confidence": confidence,
        "is_inferred": is_inferred,
        "evidence": evidence,
    }
    if method:
        item["method"] = method
    return item


def _missing_item(
    *,
    key: str,
    label: str,
    reason: str,
    next_step: str,
) -> dict[str, str]:
    return {
        "key": key,
        "label": label,
        "reason": reason,
        "next_step": next_step,
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
