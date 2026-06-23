from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.rate_limit import RateLimitDecision
from app.domains.jobs.job_service import JobQueueService
from app.domains.jobs.registry import JobExecutionContext
from app.domains.social_media import onboarding_jobs, onboarding_service
from app.domains.social_media.onboarding_service import SocialOnboardingService
from app.integrations.phyllo import PhylloProviderError
from tests.test_sales_contacts_integration import TENANT_1, current_one, current_two

pytestmark = pytest.mark.integration
pytest_plugins = ("tests.test_sales_contacts_integration",)


@pytest.fixture(autouse=True)
def clean_social_global_tables(db_session: Session) -> None:
    db_session.execute(
        text("TRUNCATE social_public_reference_profiles RESTART IDENTITY CASCADE")
    )
    db_session.commit()


def make_service(db_session: Session) -> SocialOnboardingService:
    return SocialOnboardingService(db_session, job_queue=JobQueueService(db_session))


def seed_social_calendar_entry(
    db_session: Session,
    service: SocialOnboardingService,
) -> dict[str, Any]:
    session = service.create_session(current=current_one(), objective="content_ops")
    plan_id = db_session.execute(
        text(
            """
            INSERT INTO social_action_plans (
                tenant_id,
                onboarding_session_id,
                created_by_membership_id,
                updated_by_membership_id,
                title,
                summary,
                status,
                source_analysis_version,
                source_specialist_version,
                plan_version
            )
            VALUES (
                :tenant_id,
                :session_id,
                :membership_id,
                :membership_id,
                'Plano de teste',
                'Plano gerado para testes de calendario',
                'active',
                1,
                'test',
                1
            )
            RETURNING id
            """
        ),
        {
            "tenant_id": TENANT_1,
            "session_id": session["id"],
            "membership_id": current_one().membership_id,
        },
    ).scalar_one()
    entry_id = db_session.execute(
        text(
            """
            INSERT INTO social_content_calendar_entries (
                tenant_id,
                action_plan_id,
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
                source_reference_handle
            )
            VALUES (
                :tenant_id,
                :plan_id,
                :session_id,
                NOW() + INTERVAL '1 day',
                1,
                'Dia 1: roteiro de teste',
                'REEL',
                'instagram',
                'planned',
                'Prova social',
                'Abrir com resultado concreto',
                'Legenda com historia curta',
                'Comente a palavra plano',
                'Top contents reais do diagnostico',
                'Medir salvamentos e comentarios',
                '@referencia'
            )
            RETURNING id
            """
        ),
        {
            "tenant_id": TENANT_1,
            "plan_id": plan_id,
            "session_id": session["id"],
        },
    ).scalar_one()
    db_session.commit()
    return {"session_id": session["id"], "plan_id": plan_id, "entry_id": entry_id}


class FakePhylloClient:
    def __init__(self) -> None:
        self.users_by_external_id: dict[str, dict[str, Any]] = {}
        self.created_users = 0
        self.created_tokens: list[dict[str, Any]] = []
        self.accounts_by_user_id: dict[str, list[dict[str, Any]]] = {}
        self.accounts_by_id: dict[str, dict[str, Any]] = {}
        self.contents_by_account_id: dict[str, list[dict[str, Any]]] = {}
        self.list_accounts_errors: set[str] = set()
        self.list_contents_errors: set[str] = set()

    def get_user_by_external_id(self, external_id: str):
        return self.users_by_external_id.get(external_id)

    def create_user(self, *, name: str, external_id: str):
        self.created_users += 1
        user = {
            "id": f"phyllo-user-{self.created_users}",
            "name": name,
            "external_id": external_id,
        }
        self.users_by_external_id[external_id] = user
        return user

    def create_sdk_token(self, *, user_id: str, products: list[str]):
        self.created_tokens.append({"user_id": user_id, "products": products})
        return {"sdk_token": f"sdk-{user_id}"}

    def get_account(self, account_id: str):
        return self.accounts_by_id.get(account_id) or {
            "id": account_id,
            "user": {"id": "phyllo-user-1"},
            "work_platform_id": "9bb8913b-ddd9-430b-a66a-d74d846e6c66",
            "platform_username": "MinhaMarca",
            "display_name": "Minha Marca",
            "profile_url": "https://instagram.com/minhamarca",
            "status": "connected",
            "data": {
                "identity": {"status": "SYNCED"},
                "engagement": {"status": "SYNCED", "last_sync_at": "2026-06-11T10:00:00"},
            },
        }

    def list_accounts(self, *, user_id: str):
        if user_id in self.list_accounts_errors:
            raise PhylloProviderError("Phyllo temporariamente indisponivel")
        return self.accounts_by_user_id.get(user_id, [])

    def list_profiles(self, *, account_id: str):
        return [
            {
                "id": "profile-1",
                "account_id": account_id,
                "follower_count": 4200,
                "following_count": 900,
                "content_count": 96,
                "engagement_rate": 3.4,
                "introduction": "Marca de conteudo sobre IA e vendas",
                "website": "https://labby.com.br",
                "is_business": True,
                "is_verified": False,
            }
        ]

    def list_contents(self, *, account_id: str, limit: int = 30):
        if account_id in self.list_contents_errors:
            raise PhylloProviderError("Phyllo contents temporariamente indisponivel")
        return self.contents_by_account_id.get(
            account_id,
            [
                {
                    "id": "content-1",
                    "external_id": "ig-1",
                    "type": "REEL",
                    "format": "VIDEO",
                    "url": "https://instagram.com/reel/1",
                    "engagement": {
                        "like_count": 120,
                        "comment_count": 12,
                        "share_count": 8,
                        "save_count": 20,
                        "view_count": 5100,
                        "reach_organic_count": 3400,
                    },
                },
                {
                    "id": "content-2",
                    "external_id": "ig-2",
                    "type": "POST",
                    "format": "IMAGE",
                    "url": "https://instagram.com/p/2",
                    "engagement": {
                        "like_count": 80,
                        "comment_count": 4,
                        "share_count": 1,
                        "save_count": 3,
                        "reach_organic_count": 900,
                    },
                },
            ],
        )[:limit]


class FakeApifyClient:
    def __init__(self) -> None:
        self.profile_calls: list[str] = []
        self.post_calls: list[dict[str, Any]] = []
        self.profile_items_by_handle: dict[str, list[dict[str, Any]]] = {}
        self.post_items_by_handle: dict[str, list[dict[str, Any]]] = {}
        self.profile_errors: set[str] = set()
        self.post_errors: set[str] = set()

    def fetch_instagram_profile(self, *, handle: str) -> list[dict[str, Any]]:
        self.profile_calls.append(handle)
        if handle in self.profile_errors:
            from app.integrations.apify import ApifyProviderError

            raise ApifyProviderError("Apify profile temporary failure")
        return self.profile_items_by_handle.get(
            handle,
            [
                {
                    "username": handle,
                    "fullName": "Gabriel Vieira | Cripto",
                    "followersCount": 1368,
                    "followsCount": 1375,
                    "postsCount": 31,
                    "biography": "Eu sou Trader e nao sou Holder",
                    "profilePicUrl": "https://cdn.example/avatar.jpg",
                    "url": f"https://www.instagram.com/{handle}/",
                    "private": False,
                    "verified": False,
                    "isBusinessAccount": False,
                }
            ],
        )

    def fetch_instagram_posts(self, *, handle: str, limit: int) -> list[dict[str, Any]]:
        self.post_calls.append({"handle": handle, "limit": limit})
        if handle in self.post_errors:
            from app.integrations.apify import ApifyProviderError

            raise ApifyProviderError("Apify posts temporary failure")
        return self.post_items_by_handle.get(
            handle,
            [
                {
                    "id": "3727959046017062220",
                    "shortCode": "DO8XwA",
                    "url": "https://www.instagram.com/p/DO8XwA/",
                    "caption": "O Atacama foi so o inicio de um mundo inteiro.",
                    "commentsCount": 5,
                    "likesCount": 58,
                    "timestamp": "2026-04-29T19:58:06.000Z",
                    "productType": "clips",
                },
                {
                    "id": "3886212427159640420",
                    "shortCode": "DXumZz",
                    "url": "https://www.instagram.com/p/DXumZz/",
                    "caption": "Nem nos meus sonhos mais impossiveis.",
                    "commentsCount": 12,
                    "likesCount": 35,
                    "timestamp": "2026-02-02T12:46:40.000Z",
                    "productType": "clips",
                },
            ],
        )[:limit]


class FakeSpecialistAIClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_social_profile_analysis(self, *, analysis_input: dict[str, Any]):
        from app.integrations.ai import (
            SOCIAL_SPECIALIST_ANALYSIS_VERSION,
            AISpecialistAnalysisResult,
        )

        self.calls.append(analysis_input)
        return AISpecialistAnalysisResult(
            analysis={
                "status": "ready",
                "version": SOCIAL_SPECIALIST_ANALYSIS_VERSION,
                "executive_summary": "Analise especialista baseada em dados reais.",
                "diagnosis": [
                    {
                        "title": "Padrao principal",
                        "evidence": "Posts reais e referencias sincronizadas.",
                        "recommendation": "Dobrar testes no formato de maior sinal.",
                        "confidence": "high",
                    }
                ],
                "content_patterns": [],
                "benchmark_insights": [],
                "opportunities": [],
                "action_plan": [],
                "truth_blocks": [{"key": "audience_demographics"}],
                "source_contract": {"uses_real_posts": True},
            },
            model="fake-specialist",
            provider="fake",
            provider_response_id="fake-response",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
        )


class FakeRateLimiter:
    def __init__(self, *, allowed: bool = True) -> None:
        self.allowed = allowed
        self.calls: list[dict[str, Any]] = []

    def check(
        self,
        *,
        key: str,
        limit: int,
        window_seconds: int = 60,
    ) -> RateLimitDecision:
        self.calls.append(
            {
                "key": key,
                "limit": limit,
                "window_seconds": window_seconds,
            }
        )
        return RateLimitDecision(
            allowed=self.allowed,
            current=1 if self.allowed else limit + 1,
            retry_after_seconds=3600,
        )


def make_phyllo_service(
    db_session: Session,
    phyllo_client: FakePhylloClient,
) -> SocialOnboardingService:
    return SocialOnboardingService(
        db_session,
        job_queue=JobQueueService(db_session),
        phyllo_client=phyllo_client,
    )


def make_apify_service(
    db_session: Session,
    apify_client: FakeApifyClient,
) -> SocialOnboardingService:
    return SocialOnboardingService(
        db_session,
        job_queue=JobQueueService(db_session),
        apify_client=apify_client,
    )


def make_specialist_service(
    db_session: Session,
    specialist_ai_client: FakeSpecialistAIClient,
) -> SocialOnboardingService:
    return SocialOnboardingService(
        db_session,
        job_queue=JobQueueService(db_session),
        specialist_ai_client=specialist_ai_client,
    )


def test_social_onboarding_rediagnose_uses_new_job_version_real_postgres(
    db_session: Session,
) -> None:
    service = make_service(db_session)
    session = service.create_session(current=current_one(), objective="grow_audience")

    first, first_job = service.connect_fake_account(
        current=current_one(),
        session_id=str(session["id"]),
        provider="instagram",
        handle="@marca",
        display_name="Marca",
        profile_url=None,
        followers_count=1200,
        posts_count=80,
        average_engagement_rate=2.4,
    )
    assert first["analysis_version"] == 1
    assert first["connection_mode"] == "simulated"
    assert first_job.idempotency_key.endswith(":v1")

    service.run_diagnostic(
        tenant_id=str(TENANT_1),
        session_id=str(session["id"]),
        analysis_version=1,
    )
    ready = service.get_session(current=current_one(), session_id=str(session["id"]))
    assert ready["status"] == "ready"

    second, second_job = service.connect_fake_account(
        current=current_one(),
        session_id=str(session["id"]),
        provider="youtube",
        handle="@marca_tv",
        display_name="Marca TV",
        profile_url=None,
        followers_count=2500,
        posts_count=140,
        average_engagement_rate=3.1,
    )
    assert second["status"] == "analyzing"
    assert second["analysis_version"] == 2
    assert second_job.idempotency_key.endswith(":v2")
    assert second_job.id != first_job.id

    stale = service.run_diagnostic(
        tenant_id=str(TENANT_1),
        session_id=str(session["id"]),
        analysis_version=1,
    )
    assert stale["skipped"] is True
    assert stale["reason"] == "stale_analysis_version"
    still_analyzing = service.get_session(current=current_one(), session_id=str(session["id"]))
    assert still_analyzing["status"] == "analyzing"

    service.run_diagnostic(
        tenant_id=str(TENANT_1),
        session_id=str(session["id"]),
        analysis_version=2,
    )
    rerun_ready = service.get_session(current=current_one(), session_id=str(session["id"]))
    assert rerun_ready["status"] == "ready"
    assert rerun_ready["connected_account_handle"] == "marca_tv"

    job_count = db_session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM jobs
            WHERE tenant_id = :tenant_id
              AND job_type = 'social.onboarding.diagnose'
            """
        ),
        {"tenant_id": TENANT_1},
    ).scalar_one()
    assert job_count == 2


def test_social_onboarding_worker_skips_archived_session_real_postgres(
    db_session: Session,
) -> None:
    service = make_service(db_session)
    first = service.create_session(current=current_one(), objective="grow_audience")
    connected, _ = service.connect_fake_account(
        current=current_one(),
        session_id=str(first["id"]),
        provider="instagram",
        handle="@marca",
        display_name="Marca",
        profile_url=None,
        followers_count=1200,
        posts_count=80,
        average_engagement_rate=2.4,
    )
    service.create_session(current=current_one(), objective="sell_more")

    result = service.run_diagnostic(
        tenant_id=str(TENANT_1),
        session_id=str(first["id"]),
        analysis_version=connected["analysis_version"],
    )

    assert result["skipped"] is True
    assert result["reason"] == "session_archived"
    archived_status = db_session.execute(
        text("SELECT status FROM social_onboarding_sessions WHERE id = :session_id"),
        {"session_id": first["id"]},
    ).scalar_one()
    assert archived_status == "archived"


def test_social_onboarding_cross_tenant_lookup_returns_404_for_real_row(
    db_session: Session,
) -> None:
    service = make_service(db_session)
    other = service.create_session(current=current_two(), objective="benchmarking")

    with pytest.raises(HTTPException) as exc:
        service.get_session(current=current_one(), session_id=str(other["id"]))

    assert exc.value.status_code == 404


def test_social_onboarding_phyllo_connect_token_creates_tenant_user_once(
    db_session: Session,
) -> None:
    phyllo = FakePhylloClient()
    service = make_phyllo_service(db_session, phyllo)
    session = service.create_session(current=current_one(), objective="grow_audience")

    first = service.create_phyllo_connect_token(
        current=current_one(),
        session_id=str(session["id"]),
    )
    second = service.create_phyllo_connect_token(
        current=current_one(),
        session_id=str(session["id"]),
    )

    assert first["user_id"] == "phyllo-user-1"
    assert first["sdk_token"] == "sdk-phyllo-user-1"
    assert second["user_id"] == "phyllo-user-1"
    assert phyllo.created_users == 1
    assert phyllo.created_tokens == [
        {"user_id": "phyllo-user-1", "products": ["IDENTITY", "ENGAGEMENT"]},
        {"user_id": "phyllo-user-1", "products": ["IDENTITY", "ENGAGEMENT"]},
    ]
    status = db_session.execute(
        text("SELECT status FROM social_onboarding_sessions WHERE id = :session_id"),
        {"session_id": session["id"]},
    ).scalar_one()
    assert status == "connecting"


def test_social_onboarding_phyllo_connect_token_clears_simulated_report(
    db_session: Session,
) -> None:
    phyllo = FakePhylloClient()
    service = make_phyllo_service(db_session, phyllo)
    session = service.create_session(current=current_one(), objective="grow_audience")
    connected, _ = service.connect_fake_account(
        current=current_one(),
        session_id=str(session["id"]),
        provider="instagram",
        handle="@marca",
        display_name="Marca",
        profile_url="https://instagram.com/marca",
        followers_count=1200,
        posts_count=80,
        average_engagement_rate=2.4,
    )
    service.run_diagnostic(
        tenant_id=str(TENANT_1),
        session_id=str(session["id"]),
        analysis_version=connected["analysis_version"],
    )

    ready = service.get_session(current=current_one(), session_id=str(session["id"]))
    assert ready["status"] == "ready"
    assert ready["connection_mode"] == "simulated"
    assert ready["connected_account_handle"] == "marca"
    assert ready["analysis_report"]

    service.create_phyllo_connect_token(
        current=current_one(),
        session_id=str(session["id"]),
    )

    oauth = service.get_session(current=current_one(), session_id=str(session["id"]))
    assert oauth["status"] == "connecting"
    assert oauth["connection_mode"] == "oauth"
    assert oauth["primary_provider"] == "instagram"
    assert oauth["connected_account_id"] is None
    assert oauth["connected_account_handle"] is None
    assert oauth["connected_account_name"] is None
    assert oauth["profile_url"] is None
    assert oauth["profile_snapshot"] == {}
    assert oauth["analysis_report"] is None
    assert oauth["analysis_started_at"] is None
    assert oauth["analysis_completed_at"] is None


def test_social_onboarding_phyllo_complete_updates_oauth_snapshot_and_job(
    db_session: Session,
) -> None:
    phyllo = FakePhylloClient()
    service = make_phyllo_service(db_session, phyllo)
    session = service.create_session(current=current_one(), objective="grow_audience")
    service.create_phyllo_connect_token(current=current_one(), session_id=str(session["id"]))

    connected, job = service.complete_phyllo_connection(
        current=current_one(),
        session_id=str(session["id"]),
        phyllo_user_id="phyllo-user-1",
        account_id="phyllo-account-1",
        work_platform_id="9bb8913b-ddd9-430b-a66a-d74d846e6c66",
    )

    assert connected["status"] == "analyzing"
    assert connected["connection_mode"] == "oauth"
    assert connected["primary_provider"] == "instagram"
    assert connected["connected_account_handle"] == "minhamarca"
    assert connected["profile_snapshot"]["source"] == "phyllo"
    assert connected["profile_snapshot"]["followers_count"] == 4200
    assert connected["profile_snapshot"]["following_count"] == 900
    assert connected["profile_snapshot"]["bio"] == "Marca de conteudo sobre IA e vendas"
    assert connected["profile_snapshot"]["website"] == "https://labby.com.br"
    assert connected["profile_snapshot"]["is_business"] is True
    assert connected["profile_snapshot"]["engagement_sync_status"] == "SYNCED"
    assert connected["analysis_version"] == 1
    assert job.idempotency_key.endswith(":v1")

    account_row = db_session.execute(
        text(
            """
            SELECT provider, handle, phyllo_account_id
            FROM social_phyllo_accounts
            WHERE tenant_id = :tenant_id
              AND phyllo_account_id = 'phyllo-account-1'
            """
        ),
        {"tenant_id": TENANT_1},
    ).mappings().one()
    assert account_row["provider"] == "instagram"
    assert account_row["handle"] == "minhamarca"


def test_social_onboarding_diagnostic_uses_real_phyllo_content_metrics(
    db_session: Session,
) -> None:
    phyllo = FakePhylloClient()
    service = make_phyllo_service(db_session, phyllo)
    session = service.create_session(current=current_one(), objective="authority")
    service.create_phyllo_connect_token(current=current_one(), session_id=str(session["id"]))

    connected, _ = service.complete_phyllo_connection(
        current=current_one(),
        session_id=str(session["id"]),
        phyllo_user_id="phyllo-user-1",
        account_id="phyllo-account-1",
        work_platform_id="9bb8913b-ddd9-430b-a66a-d74d846e6c66",
    )

    result = service.run_diagnostic(
        tenant_id=str(TENANT_1),
        session_id=str(session["id"]),
        analysis_version=connected["analysis_version"],
    )

    assert result["status"] == "ready"
    ready = service.get_session(current=current_one(), session_id=str(session["id"]))
    snapshot = ready["profile_snapshot"]
    report = ready["analysis_report"]
    assert snapshot["content_items_count"] == 2
    assert snapshot["content_metrics"]["views"] == 5100
    assert snapshot["content_metrics"]["reach"] == 4300
    assert snapshot["content_metrics"]["interactions"] == 248
    assert snapshot["content_metrics"]["engagement_rate_by_followers"] == 2.95
    assert snapshot["top_contents"][0]["external_id"] == "ig-1"
    assert report["data_quality"]["contents_analyzed"] == 2
    assert report["data_quality"]["has_real_engagement"] is True
    assert report["data_quality"]["content_sync_status"] == "synced"
    assert report["truth_contract"]["version"] == "social_profile_truth_v1"
    assert any(item["key"] == "followers_count" for item in report["observed_facts"])
    assert any(
        item["key"] == "engagement_rate_by_followers"
        for item in report["computed_insights"]
    )
    assert any(
        item["key"] == "segment" and item["is_inferred"]
        for item in report["inferred_insights"]
    )
    assert any(item["key"] == "audience_demographics" for item in report["missing_data"])
    assert report["top_contents"][0]["metrics"]["comments"] == 12
    assert "_raw" not in report["top_contents"][0]
    assert "Cripto" not in report["segment"]["name"]

    content_rows = db_session.execute(
        text(
            """
            SELECT
              environment,
              external_id,
              content_type,
              content_format,
              metrics_json,
              raw_payload,
              data_truth,
              engagement_rate_by_followers
            FROM social_connected_contents
            WHERE tenant_id = :tenant_id
              AND phyllo_account_id = 'phyllo-account-1'
            ORDER BY external_id ASC
            """
        ),
        {"tenant_id": TENANT_1},
    ).mappings().all()
    assert len(content_rows) == 2
    assert content_rows[0]["environment"] == "staging"
    assert content_rows[0]["external_id"] == "ig-1"
    assert content_rows[0]["content_type"] == "REEL"
    assert content_rows[0]["content_format"] == "VIDEO"
    assert content_rows[0]["metrics_json"]["likes"] == 120
    assert content_rows[0]["raw_payload"]["external_id"] == "ig-1"
    assert content_rows[0]["raw_payload"]["engagement"]["comment_count"] == 12
    assert content_rows[0]["data_truth"]["source"] == "phyllo"
    assert float(content_rows[0]["engagement_rate_by_followers"]) == 3.81


def test_social_onboarding_specialist_analysis_persists_versioned_result(
    db_session: Session,
) -> None:
    phyllo = FakePhylloClient()
    specialist_ai = FakeSpecialistAIClient()
    service = SocialOnboardingService(
        db_session,
        job_queue=JobQueueService(db_session),
        phyllo_client=phyllo,
        specialist_ai_client=specialist_ai,
    )
    session = service.create_session(current=current_one(), objective="authority")
    service.create_phyllo_connect_token(current=current_one(), session_id=str(session["id"]))
    connected, _ = service.complete_phyllo_connection(
        current=current_one(),
        session_id=str(session["id"]),
        phyllo_user_id="phyllo-user-1",
        account_id="phyllo-account-1",
        work_platform_id="9bb8913b-ddd9-430b-a66a-d74d846e6c66",
    )
    service.run_diagnostic(
        tenant_id=str(TENANT_1),
        session_id=str(session["id"]),
        analysis_version=connected["analysis_version"],
    )

    queued, job = service.enqueue_specialist_analysis(
        current=current_one(),
        session_id=str(session["id"]),
    )
    assert job.job_type == "social.onboarding.specialist_analysis"
    assert queued["analysis_report"]["specialist_analysis"]["status"] == "queued"

    result = service.run_specialist_analysis(
        tenant_id=str(TENANT_1),
        session_id=str(session["id"]),
        analysis_version=queued["analysis_version"],
    )

    assert result["status"] == "ready"
    assert len(specialist_ai.calls) == 1
    ready = service.get_session(current=current_one(), session_id=str(session["id"]))
    analysis = ready["analysis_report"]["specialist_analysis"]
    assert analysis["status"] == "ready"
    assert analysis["analysis_version"] == ready["analysis_version"]
    assert analysis["provider"] == "fake"
    assert analysis["model"] == "fake-specialist"
    assert analysis["executive_summary"] == "Analise especialista baseada em dados reais."
    assert analysis["truth_blocks"][0]["key"] == "audience_demographics"

    skipped = service.run_specialist_analysis(
        tenant_id=str(TENANT_1),
        session_id=str(session["id"]),
        analysis_version=ready["analysis_version"],
    )
    assert skipped["skipped"] is True
    assert len(specialist_ai.calls) == 1


def test_social_onboarding_specialist_analysis_requeues_after_failed_attempt(
    db_session: Session,
) -> None:
    phyllo = FakePhylloClient()
    service = SocialOnboardingService(
        db_session,
        job_queue=JobQueueService(db_session),
        phyllo_client=phyllo,
        specialist_ai_client=FakeSpecialistAIClient(),
    )
    session = service.create_session(current=current_one(), objective="authority")
    service.create_phyllo_connect_token(current=current_one(), session_id=str(session["id"]))
    connected, _ = service.complete_phyllo_connection(
        current=current_one(),
        session_id=str(session["id"]),
        phyllo_user_id="phyllo-user-1",
        account_id="phyllo-account-1",
        work_platform_id="9bb8913b-ddd9-430b-a66a-d74d846e6c66",
    )
    service.run_diagnostic(
        tenant_id=str(TENANT_1),
        session_id=str(session["id"]),
        analysis_version=connected["analysis_version"],
    )

    queued, first_job = service.enqueue_specialist_analysis(
        current=current_one(),
        session_id=str(session["id"]),
    )
    first_analysis = queued["analysis_report"]["specialist_analysis"]
    assert first_analysis["request_generation"] == 1
    assert first_job.idempotency_key.endswith(":r1")

    service.mark_specialist_analysis_failed(
        tenant_id=str(TENANT_1),
        session_id=str(session["id"]),
        analysis_version=queued["analysis_version"],
        request_generation=1,
        error_code="AITimeoutError",
        error_message="Timeout na IA",
    )

    retried, second_job = service.enqueue_specialist_analysis(
        current=current_one(),
        session_id=str(session["id"]),
    )
    retry_analysis = retried["analysis_report"]["specialist_analysis"]

    assert retry_analysis["status"] == "queued"
    assert retry_analysis["request_generation"] == 2
    assert second_job.id != first_job.id
    assert second_job.idempotency_key.endswith(":r2")

    jobs = db_session.execute(
        text(
            """
            SELECT idempotency_key, status
            FROM jobs
            WHERE tenant_id = :tenant_id
              AND job_type = 'social.onboarding.specialist_analysis'
            ORDER BY created_at ASC
            """
        ),
        {"tenant_id": str(TENANT_1)},
    ).mappings().all()
    assert [row["idempotency_key"].rsplit(":", 1)[-1] for row in jobs] == ["r1", "r2"]


def test_social_onboarding_specialist_analysis_budget_blocks_new_paid_job(
    db_session: Session,
) -> None:
    phyllo = FakePhylloClient()
    limiter = FakeRateLimiter(allowed=False)
    service = SocialOnboardingService(
        db_session,
        job_queue=JobQueueService(db_session),
        phyllo_client=phyllo,
        specialist_ai_client=FakeSpecialistAIClient(),
        rate_limiter=limiter,
    )
    session = service.create_session(current=current_one(), objective="authority")
    service.create_phyllo_connect_token(current=current_one(), session_id=str(session["id"]))
    connected, _ = service.complete_phyllo_connection(
        current=current_one(),
        session_id=str(session["id"]),
        phyllo_user_id="phyllo-user-1",
        account_id="phyllo-account-1",
        work_platform_id="9bb8913b-ddd9-430b-a66a-d74d846e6c66",
    )
    service.run_diagnostic(
        tenant_id=str(TENANT_1),
        session_id=str(session["id"]),
        analysis_version=connected["analysis_version"],
    )

    with pytest.raises(HTTPException) as exc:
        service.enqueue_specialist_analysis(
            current=current_one(),
            session_id=str(session["id"]),
        )

    assert exc.value.status_code == 429
    assert len(limiter.calls) == 1
    assert limiter.calls[0]["key"].startswith(f"social-specialist-analysis:{TENANT_1}:")
    assert limiter.calls[0]["limit"] == 20
    assert limiter.calls[0]["window_seconds"] == 60 * 60 * 24
    row = db_session.execute(
        text(
            """
            SELECT analysis_report
            FROM social_onboarding_sessions
            WHERE id = :session_id
            """
        ),
        {"session_id": str(session["id"])},
    ).mappings().one()
    assert "specialist_analysis" not in row["analysis_report"]


def test_social_onboarding_reference_profiles_are_globally_deduped(
    db_session: Session,
) -> None:
    service = make_service(db_session)
    session_one = service.create_session(current=current_one(), objective="benchmarking")
    session_two = service.create_session(current=current_two(), objective="benchmarking")

    reference_one = service.add_reference(
        current=current_one(),
        session_id=str(session_one["id"]),
        provider="instagram",
        handle="@ReferenciaCrypto",
        label="Referencia crypto",
        profile_url="https://instagram.com/referenciacrypto",
    )
    reference_two = service.add_reference(
        current=current_two(),
        session_id=str(session_two["id"]),
        provider="instagram",
        handle="referenciacrypto",
        label="Referencia para outro tenant",
        profile_url=None,
    )

    assert (
        reference_one["public_reference_profile_id"]
        == reference_two["public_reference_profile_id"]
    )
    assert reference_one["sync_status"] == "pending"
    assert reference_one["public_contents_count"] == 0
    assert reference_one["label"] == "Referencia crypto"
    assert reference_one["profile_url"] == "https://instagram.com/referenciacrypto"

    global_row = db_session.execute(
        text(
            """
            SELECT
              COUNT(*) AS total,
              MAX(display_name) AS display_name,
              MAX(profile_url) AS profile_url
            FROM social_public_reference_profiles
            WHERE provider = 'instagram'
              AND handle = 'referenciacrypto'
            """
        )
    ).mappings().one()
    link_count = db_session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM social_reference_profiles
            WHERE public_reference_profile_id = :public_reference_profile_id
            """
        ),
        {"public_reference_profile_id": reference_one["public_reference_profile_id"]},
    ).scalar_one()

    assert global_row["total"] == 1
    assert global_row["display_name"] is None
    assert global_row["profile_url"] is None
    assert link_count == 2
    sync_job_count = db_session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM jobs
            WHERE job_type = 'social.references.sync'
              AND payload ->> 'handle' = 'referenciacrypto'
            """
        )
    ).scalar_one()
    assert sync_job_count == 1


def test_social_onboarding_reference_sync_retry_requeues_new_generation(
    db_session: Session,
) -> None:
    service = make_service(db_session)
    session = service.create_session(current=current_one(), objective="benchmarking")
    reference = service.add_reference(
        current=current_one(),
        session_id=str(session["id"]),
        provider="instagram",
        handle="@evandro_pit",
        label="Evandro",
        profile_url=None,
    )
    public_reference_id = str(reference["public_reference_profile_id"])

    db_session.execute(
        text(
            """
            UPDATE social_public_reference_profiles
            SET sync_status = 'failed',
                failure_count = 99,
                next_sync_after = NOW() + INTERVAL '1 day',
                data_truth = data_truth || '{"last_sync_error_code":"apify_not_configured"}'::jsonb
            WHERE id = :public_reference_id
            """
        ),
        {"public_reference_id": public_reference_id},
    )
    db_session.execute(
        text(
            """
            UPDATE social_reference_profiles
            SET sync_status = 'failed',
                comparison_summary = '{"status":"failed"}'::jsonb
            WHERE id = :reference_id
            """
        ),
        {"reference_id": str(reference["id"])},
    )
    db_session.commit()

    retried_reference, job = service.enqueue_reference_sync(
        current=current_one(),
        session_id=str(session["id"]),
        reference_id=str(reference["id"]),
    )

    assert job is not None
    assert job.job_type == "social.references.sync"
    assert job.idempotency_key.endswith(":v2")
    assert retried_reference["sync_status"] == "pending"
    assert retried_reference["global_sync_status"] == "pending"
    assert retried_reference["data_truth"]["public_data_sync_requested"] is True
    assert retried_reference["comparison_summary"]["status"] == "pending_public_sync"

    global_row = db_session.execute(
        text(
            """
            SELECT sync_status, sync_generation, next_sync_after
            FROM social_public_reference_profiles
            WHERE id = :public_reference_id
            """
        ),
        {"public_reference_id": public_reference_id},
    ).mappings().one()
    assert global_row["sync_status"] == "pending"
    assert global_row["sync_generation"] == 2
    assert global_row["next_sync_after"] is None


def test_social_onboarding_public_reference_sync_persists_apify_profile_and_posts(
    db_session: Session,
) -> None:
    apify_client = FakeApifyClient()
    service = make_apify_service(db_session, apify_client)
    session = service.create_session(current=current_one(), objective="benchmarking")
    reference = service.add_reference(
        current=current_one(),
        session_id=str(session["id"]),
        provider="instagram",
        handle="@gvcripto",
        label="Referencia real",
        profile_url=None,
    )
    public_reference_id = str(reference["public_reference_profile_id"])
    generation = db_session.execute(
        text(
            """
            SELECT sync_generation
            FROM social_public_reference_profiles
            WHERE id = :public_reference_id
            """
        ),
        {"public_reference_id": public_reference_id},
    ).scalar_one()

    result = service.run_public_reference_sync(
        tenant_id=str(TENANT_1),
        public_reference_profile_id=public_reference_id,
        provider="instagram",
        handle="gvcripto",
        sync_generation=int(generation),
        session_id=str(session["id"]),
    )

    assert result["status"] == "synced"
    assert result["posts_synced"] == 2
    assert result["diagnostic_job_id"] is None
    assert apify_client.profile_calls == ["gvcripto"]
    assert apify_client.post_calls == [{"handle": "gvcripto", "limit": 30}]

    global_row = db_session.execute(
        text(
            """
            SELECT
              source,
              sync_status,
              display_name,
              profile_url,
              profile_snapshot,
              raw_payload,
              data_truth
            FROM social_public_reference_profiles
            WHERE id = :public_reference_id
            """
        ),
        {"public_reference_id": public_reference_id},
    ).mappings().one()
    assert global_row["source"] == "apify"
    assert global_row["sync_status"] == "synced"
    assert global_row["display_name"] == "Gabriel Vieira | Cripto"
    assert global_row["profile_url"] == "https://www.instagram.com/gvcripto/"
    assert global_row["profile_snapshot"]["followers_count"] == 1368
    assert global_row["raw_payload"]["username"] == "gvcripto"
    assert global_row["data_truth"]["source"] == "apify"
    assert global_row["data_truth"]["public_data_only"] is True

    content_rows = db_session.execute(
        text(
            """
            SELECT
              external_id,
              content_type,
              content_format,
              title,
              metrics_json,
              raw_payload,
              data_truth,
              engagement_rate_by_followers,
              engagement_rate_by_reach
            FROM social_public_reference_contents
            WHERE reference_profile_id = :public_reference_id
            ORDER BY performance_score DESC
            """
        ),
        {"public_reference_id": public_reference_id},
    ).mappings().all()
    assert len(content_rows) == 2
    assert content_rows[0]["external_id"] == "3886212427159640420"
    assert content_rows[0]["content_type"] == "REELS"
    assert content_rows[0]["content_format"] == "VIDEO"
    assert content_rows[0]["metrics_json"]["likes"] == 35
    assert content_rows[0]["metrics_json"]["comments"] == 12
    assert content_rows[0]["metrics_json"]["reach"] is None
    assert content_rows[0]["metrics_json"]["shares"] is None
    assert content_rows[0]["raw_payload"]["shortCode"] == "DXumZz"
    assert content_rows[0]["data_truth"]["source"] == "apify"
    assert "reach" in content_rows[0]["data_truth"]["unavailable_metrics"]
    assert float(content_rows[0]["engagement_rate_by_followers"]) == 3.44
    assert content_rows[0]["engagement_rate_by_reach"] is None

    linked_reference = service.get_session(current=current_one(), session_id=str(session["id"]))
    synced_reference = linked_reference["references"][0]
    assert synced_reference["sync_status"] == "synced"
    assert synced_reference["global_sync_status"] == "synced"
    assert synced_reference["public_contents_count"] == 2
    assert synced_reference["comparison_summary"]["public_followers_count"] == 1368


def test_social_onboarding_public_reference_partial_sync_honors_cooldown(
    db_session: Session,
) -> None:
    apify_client = FakeApifyClient()
    apify_client.post_items_by_handle["emptyref"] = []
    service = make_apify_service(db_session, apify_client)
    first_session = service.create_session(current=current_one(), objective="benchmarking")
    second_session = service.create_session(current=current_two(), objective="benchmarking")

    first_reference = service.add_reference(
        current=current_one(),
        session_id=str(first_session["id"]),
        provider="instagram",
        handle="@emptyref",
        label=None,
        profile_url=None,
    )
    public_reference_id = str(first_reference["public_reference_profile_id"])
    generation = db_session.execute(
        text(
            """
            SELECT sync_generation
            FROM social_public_reference_profiles
            WHERE id = :public_reference_id
            """
        ),
        {"public_reference_id": public_reference_id},
    ).scalar_one()

    result = service.run_public_reference_sync(
        tenant_id=str(TENANT_1),
        public_reference_profile_id=public_reference_id,
        provider="instagram",
        handle="emptyref",
        sync_generation=int(generation),
        session_id=str(first_session["id"]),
    )

    assert result["status"] == "partially_synced"
    assert result["posts_synced"] == 0
    assert apify_client.profile_calls == ["emptyref"]
    assert apify_client.post_calls == [{"handle": "emptyref", "limit": 30}]

    second_reference = service.add_reference(
        current=current_two(),
        session_id=str(second_session["id"]),
        provider="instagram",
        handle="emptyref",
        label=None,
        profile_url=None,
    )

    assert second_reference["sync_status"] == "partially_synced"
    sync_job_count = db_session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM jobs
            WHERE job_type = 'social.references.sync'
              AND payload ->> 'handle' = 'emptyref'
            """
        )
    ).scalar_one()
    global_state = db_session.execute(
        text(
            """
            SELECT sync_status, failure_count, next_sync_after
            FROM social_public_reference_profiles
            WHERE id = :public_reference_id
            """
        ),
        {"public_reference_id": public_reference_id},
    ).mappings().one()
    assert sync_job_count == 1
    assert global_state["sync_status"] == "partially_synced"
    assert global_state["failure_count"] == 1
    assert global_state["next_sync_after"] is not None
    assert apify_client.profile_calls == ["emptyref"]
    assert apify_client.post_calls == [{"handle": "emptyref", "limit": 30}]


def test_social_onboarding_public_reference_reaper_fails_stale_syncing(
    db_session: Session,
) -> None:
    apify_client = FakeApifyClient()
    service = make_apify_service(db_session, apify_client)
    session = service.create_session(current=current_one(), objective="benchmarking")
    reference = service.add_reference(
        current=current_one(),
        session_id=str(session["id"]),
        provider="instagram",
        handle="@stuckref",
        label=None,
        profile_url=None,
    )
    public_reference_id = str(reference["public_reference_profile_id"])
    db_session.execute(
        text(
            """
            UPDATE social_public_reference_profiles
            SET sync_status = 'syncing',
                updated_at = NOW() - INTERVAL '2 hours'
            WHERE id = :public_reference_id
            """
        ),
        {"public_reference_id": public_reference_id},
    )
    db_session.execute(
        text(
            """
            UPDATE social_reference_profiles
            SET sync_status = 'syncing'
            WHERE public_reference_profile_id = :public_reference_id
            """
        ),
        {"public_reference_id": public_reference_id},
    )
    db_session.commit()

    reaped = service.reconcile_stale_public_reference_syncs(
        stale_after_minutes=60,
        limit=10,
    )

    assert len(reaped) == 1
    global_state = db_session.execute(
        text(
            """
            SELECT sync_status, failure_count, next_sync_after
            FROM social_public_reference_profiles
            WHERE id = :public_reference_id
            """
        ),
        {"public_reference_id": public_reference_id},
    ).mappings().one()
    linked_state = db_session.execute(
        text(
            """
            SELECT sync_status, comparison_summary
            FROM social_reference_profiles
            WHERE public_reference_profile_id = :public_reference_id
            """
        ),
        {"public_reference_id": public_reference_id},
    ).mappings().one()
    assert global_state["sync_status"] == "failed"
    assert global_state["failure_count"] == 1
    assert global_state["next_sync_after"] is not None
    assert linked_state["sync_status"] == "failed"
    assert linked_state["comparison_summary"]["error_code"] == "sync_abandoned"


def test_social_onboarding_cleanup_deletes_orphaned_public_references(
    db_session: Session,
) -> None:
    apify_client = FakeApifyClient()
    service = make_apify_service(db_session, apify_client)
    session = service.create_session(current=current_one(), objective="benchmarking")
    reference = service.add_reference(
        current=current_one(),
        session_id=str(session["id"]),
        provider="instagram",
        handle="@oldref",
        label=None,
        profile_url=None,
    )
    public_reference_id = str(reference["public_reference_profile_id"])
    generation = db_session.execute(
        text(
            """
            SELECT sync_generation
            FROM social_public_reference_profiles
            WHERE id = :public_reference_id
            """
        ),
        {"public_reference_id": public_reference_id},
    ).scalar_one()
    service.run_public_reference_sync(
        tenant_id=str(TENANT_1),
        public_reference_profile_id=public_reference_id,
        provider="instagram",
        handle="oldref",
        sync_generation=int(generation),
        session_id=str(session["id"]),
    )
    db_session.execute(
        text(
            """
            UPDATE social_reference_profiles
            SET status = 'archived',
                updated_at = NOW()
            WHERE public_reference_profile_id = :public_reference_id
            """
        ),
        {"public_reference_id": public_reference_id},
    )
    db_session.execute(
        text(
            """
            UPDATE social_public_reference_profiles
            SET updated_at = NOW() - INTERVAL '120 days'
            WHERE id = :public_reference_id
            """
        ),
        {"public_reference_id": public_reference_id},
    )
    db_session.commit()

    deleted = service.cleanup_orphaned_public_references(retention_days=90, limit=10)

    assert len(deleted) == 1
    assert str(deleted[0]["id"]) == public_reference_id
    global_count = db_session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM social_public_reference_profiles
            WHERE id = :public_reference_id
            """
        ),
        {"public_reference_id": public_reference_id},
    ).scalar_one()
    content_count = db_session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM social_public_reference_contents
            WHERE reference_profile_id = :public_reference_id
            """
        ),
        {"public_reference_id": public_reference_id},
    ).scalar_one()
    link_reference_id = db_session.execute(
        text(
            """
            SELECT public_reference_profile_id
            FROM social_reference_profiles
            WHERE tenant_id = :tenant_id
              AND handle = 'oldref'
            """
        ),
        {"tenant_id": TENANT_1},
    ).scalar_one()
    assert global_count == 0
    assert content_count == 0
    assert link_reference_id is None


def test_social_onboarding_public_reference_sync_reprocesses_ready_session(
    db_session: Session,
) -> None:
    apify_client = FakeApifyClient()
    service = make_apify_service(db_session, apify_client)
    session = service.create_session(current=current_one(), objective="benchmarking")
    analyzing, _ = service.connect_fake_account(
        current=current_one(),
        session_id=str(session["id"]),
        provider="instagram",
        handle="@marca",
        display_name="Marca",
        profile_url=None,
        followers_count=1200,
        posts_count=80,
        average_engagement_rate=2.4,
    )
    service.run_diagnostic(
        tenant_id=str(TENANT_1),
        session_id=str(session["id"]),
        analysis_version=analyzing["analysis_version"],
    )
    ready = service.get_session(current=current_one(), session_id=str(session["id"]))
    assert ready["status"] == "ready"
    assert ready["analysis_version"] == 1

    reference = service.add_reference(
        current=current_one(),
        session_id=str(session["id"]),
        provider="instagram",
        handle="@gvcripto",
        label=None,
        profile_url=None,
    )
    generation = db_session.execute(
        text(
            """
            SELECT sync_generation
            FROM social_public_reference_profiles
            WHERE id = :public_reference_id
            """
        ),
        {"public_reference_id": str(reference["public_reference_profile_id"])},
    ).scalar_one()

    sync_result = service.run_public_reference_sync(
        tenant_id=str(TENANT_1),
        public_reference_profile_id=str(reference["public_reference_profile_id"]),
        provider="instagram",
        handle="gvcripto",
        sync_generation=int(generation),
        session_id=str(session["id"]),
    )

    assert sync_result["status"] == "synced"
    assert sync_result["diagnostic_job_id"]
    reprocessing = service.get_session(current=current_one(), session_id=str(session["id"]))
    assert reprocessing["status"] == "analyzing"
    assert reprocessing["analysis_version"] == 2

    service.run_diagnostic(
        tenant_id=str(TENANT_1),
        session_id=str(session["id"]),
        analysis_version=2,
    )
    refreshed = service.get_session(current=current_one(), session_id=str(session["id"]))
    assert refreshed["status"] == "ready"
    assert refreshed["analysis_report"]["reference_context"]["status"] == "synced"
    assert refreshed["analysis_report"]["reference_context"]["references_with_public_data"] == 1
    assert refreshed["analysis_report"]["specialist_brief"]["analysis_mode"] == (
        "profile_plus_references"
    )
    assert (
        "public_reference_performance"
        not in refreshed["analysis_report"]["specialist_brief"]["blocked_inputs"]
    )


def test_social_onboarding_public_reference_diagnostic_debounce(
    db_session: Session,
) -> None:
    apify_client = FakeApifyClient()
    service = make_apify_service(db_session, apify_client)
    session = service.create_session(current=current_one(), objective="benchmarking")
    analyzing, _ = service.connect_fake_account(
        current=current_one(),
        session_id=str(session["id"]),
        provider="instagram",
        handle="@marca",
        display_name="Marca",
        profile_url=None,
        followers_count=1200,
        posts_count=80,
        average_engagement_rate=2.4,
    )
    service.run_diagnostic(
        tenant_id=str(TENANT_1),
        session_id=str(session["id"]),
        analysis_version=analyzing["analysis_version"],
    )

    first_reference = service.add_reference(
        current=current_one(),
        session_id=str(session["id"]),
        provider="instagram",
        handle="@gvcripto",
        label=None,
        profile_url=None,
    )
    first_generation = db_session.execute(
        text(
            """
            SELECT sync_generation
            FROM social_public_reference_profiles
            WHERE id = :public_reference_id
            """
        ),
        {"public_reference_id": str(first_reference["public_reference_profile_id"])},
    ).scalar_one()
    first_sync = service.run_public_reference_sync(
        tenant_id=str(TENANT_1),
        public_reference_profile_id=str(first_reference["public_reference_profile_id"]),
        provider="instagram",
        handle="gvcripto",
        sync_generation=int(first_generation),
        session_id=str(session["id"]),
    )
    assert first_sync["diagnostic_job_id"]
    service.run_diagnostic(
        tenant_id=str(TENANT_1),
        session_id=str(session["id"]),
        analysis_version=2,
    )
    ready_with_reference = service.get_session(
        current=current_one(),
        session_id=str(session["id"]),
    )
    assert ready_with_reference["status"] == "ready"
    assert ready_with_reference["analysis_version"] == 2
    assert ready_with_reference["analysis_report"]["reference_context"][
        "references_with_public_data"
    ] == 1

    second_reference = service.add_reference(
        current=current_one(),
        session_id=str(session["id"]),
        provider="instagram",
        handle="@evandro_pit",
        label=None,
        profile_url=None,
    )
    second_generation = db_session.execute(
        text(
            """
            SELECT sync_generation
            FROM social_public_reference_profiles
            WHERE id = :public_reference_id
            """
        ),
        {"public_reference_id": str(second_reference["public_reference_profile_id"])},
    ).scalar_one()
    second_sync = service.run_public_reference_sync(
        tenant_id=str(TENANT_1),
        public_reference_profile_id=str(second_reference["public_reference_profile_id"]),
        provider="instagram",
        handle="evandro_pit",
        sync_generation=int(second_generation),
        session_id=str(session["id"]),
    )

    assert second_sync["status"] == "synced"
    assert second_sync["diagnostic_job_id"] is None
    still_ready = service.get_session(current=current_one(), session_id=str(session["id"]))
    assert still_ready["status"] == "ready"
    assert still_ready["analysis_version"] == 2
    assert still_ready["analysis_report"]["reference_context"][
        "references_with_public_data"
    ] == 1
    assert len(still_ready["analysis_report"]["competitive_benchmark"]["reference_profiles"]) == 1
    diagnosis_jobs = db_session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM jobs
            WHERE job_type = 'social.onboarding.diagnose'
              AND payload ->> 'session_id' = :session_id
            """
        ),
        {"session_id": str(session["id"])},
    ).scalar_one()
    assert diagnosis_jobs == 2

    queued, diagnostic_job = service.enqueue_diagnostic(
        current=current_one(),
        session_id=str(session["id"]),
    )

    assert diagnostic_job.job_type == "social.onboarding.diagnose"
    assert queued["analysis_version"] == 3
    service.run_diagnostic(
        tenant_id=str(TENANT_1),
        session_id=str(session["id"]),
        analysis_version=3,
    )
    refreshed = service.get_session(current=current_one(), session_id=str(session["id"]))
    assert refreshed["analysis_report"]["reference_context"]["references_with_public_data"] == 2
    assert refreshed["analysis_report"]["reference_context"]["public_contents_total"] == 4
    assert len(refreshed["analysis_report"]["competitive_benchmark"]["reference_profiles"]) == 2


def test_social_onboarding_report_marks_manual_references_as_unsynced(
    db_session: Session,
) -> None:
    service = make_service(db_session)
    session = service.create_session(current=current_one(), objective="benchmarking")
    analyzing, _ = service.connect_fake_account(
        current=current_one(),
        session_id=str(session["id"]),
        provider="instagram",
        handle="@marca",
        display_name="Marca",
        profile_url=None,
        followers_count=1200,
        posts_count=80,
        average_engagement_rate=2.4,
    )
    service.add_reference(
        current=current_one(),
        session_id=str(session["id"]),
        provider="instagram",
        handle="@referencia_crypto",
        label="Referencia crypto",
        profile_url=None,
    )

    service.run_diagnostic(
        tenant_id=str(TENANT_1),
        session_id=str(session["id"]),
        analysis_version=analyzing["analysis_version"],
    )

    ready = service.get_session(current=current_one(), session_id=str(session["id"]))
    report = ready["analysis_report"]
    assert report["reference_context"]["status"] == "manual_only"
    assert report["reference_context"]["declared_count"] == 1
    assert report["reference_context"]["references_with_public_data"] == 0
    assert report["specialist_brief"]["analysis_mode"] == "profile_plus_manual_reference_context"
    assert report["specialist_brief"]["ready_for_ai"] is False
    assert "public_reference_performance" in report["specialist_brief"]["blocked_inputs"]
    assert any(item["key"] == "reference_public_metrics" for item in report["missing_data"])


def test_social_onboarding_diagnostic_degrades_when_phyllo_contents_fail(
    db_session: Session,
) -> None:
    phyllo = FakePhylloClient()
    phyllo.list_contents_errors.add("phyllo-account-1")
    service = make_phyllo_service(db_session, phyllo)
    session = service.create_session(current=current_one(), objective="authority")
    service.create_phyllo_connect_token(current=current_one(), session_id=str(session["id"]))

    connected, _ = service.complete_phyllo_connection(
        current=current_one(),
        session_id=str(session["id"]),
        phyllo_user_id="phyllo-user-1",
        account_id="phyllo-account-1",
        work_platform_id="9bb8913b-ddd9-430b-a66a-d74d846e6c66",
    )

    result = service.run_diagnostic(
        tenant_id=str(TENANT_1),
        session_id=str(session["id"]),
        analysis_version=connected["analysis_version"],
    )

    assert result["status"] == "ready"
    ready = service.get_session(current=current_one(), session_id=str(session["id"]))
    snapshot = ready["profile_snapshot"]
    report = ready["analysis_report"]
    assert snapshot["followers_count"] == 4200
    assert snapshot["content_items_count"] == 0
    assert snapshot["content_metrics"]["interactions"] == 0
    assert snapshot["data_quality"]["content_sync_status"] == "unavailable"
    assert report["data_quality"]["contents_analyzed"] == 0
    assert report["data_quality"]["has_real_engagement"] is False
    assert report["data_quality"]["content_sync_status"] == "unavailable"

    content_count = db_session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM social_connected_contents
            WHERE tenant_id = :tenant_id
            """
        ),
        {"tenant_id": TENANT_1},
    ).scalar_one()
    assert content_count == 0


def test_social_onboarding_phyllo_complete_rejects_cross_tenant_user(
    db_session: Session,
) -> None:
    phyllo = FakePhylloClient()
    service = make_phyllo_service(db_session, phyllo)
    session_one = service.create_session(current=current_one(), objective="grow_audience")
    session_two = service.create_session(current=current_two(), objective="grow_audience")
    service.create_phyllo_connect_token(current=current_one(), session_id=str(session_one["id"]))
    service.create_phyllo_connect_token(current=current_two(), session_id=str(session_two["id"]))

    with pytest.raises(HTTPException) as exc:
        service.complete_phyllo_connection(
            current=current_two(),
            session_id=str(session_two["id"]),
            phyllo_user_id="phyllo-user-1",
            account_id="phyllo-account-1",
            work_platform_id="9bb8913b-ddd9-430b-a66a-d74d846e6c66",
        )

    assert exc.value.status_code == 404


def test_social_onboarding_phyllo_complete_rejects_missing_owner(
    db_session: Session,
) -> None:
    phyllo = FakePhylloClient()
    phyllo.accounts_by_id["phyllo-account-ownerless"] = {
        "id": "phyllo-account-ownerless",
        "work_platform_id": "9bb8913b-ddd9-430b-a66a-d74d846e6c66",
        "platform_username": "SemDono",
    }
    service = make_phyllo_service(db_session, phyllo)
    session = service.create_session(current=current_one(), objective="grow_audience")
    service.create_phyllo_connect_token(current=current_one(), session_id=str(session["id"]))

    with pytest.raises(HTTPException) as exc:
        service.complete_phyllo_connection(
            current=current_one(),
            session_id=str(session["id"]),
            phyllo_user_id="phyllo-user-1",
            account_id="phyllo-account-ownerless",
            work_platform_id="9bb8913b-ddd9-430b-a66a-d74d846e6c66",
        )

    assert exc.value.status_code == 409
    account_count = db_session.execute(
        text("SELECT COUNT(*) FROM social_phyllo_accounts WHERE tenant_id = :tenant_id"),
        {"tenant_id": TENANT_1},
    ).scalar_one()
    assert account_count == 0


def test_social_onboarding_phyllo_complete_rejects_wrong_owner(
    db_session: Session,
) -> None:
    phyllo = FakePhylloClient()
    phyllo.accounts_by_id["phyllo-account-other"] = {
        "id": "phyllo-account-other",
        "user": {"id": "phyllo-user-other"},
        "work_platform_id": "9bb8913b-ddd9-430b-a66a-d74d846e6c66",
        "platform_username": "OutraConta",
    }
    service = make_phyllo_service(db_session, phyllo)
    session = service.create_session(current=current_one(), objective="grow_audience")
    service.create_phyllo_connect_token(current=current_one(), session_id=str(session["id"]))

    with pytest.raises(HTTPException) as exc:
        service.complete_phyllo_connection(
            current=current_one(),
            session_id=str(session["id"]),
            phyllo_user_id="phyllo-user-1",
            account_id="phyllo-account-other",
            work_platform_id="9bb8913b-ddd9-430b-a66a-d74d846e6c66",
        )

    assert exc.value.status_code == 409


def test_social_onboarding_fake_connect_rejects_oauth_in_progress(
    db_session: Session,
) -> None:
    phyllo = FakePhylloClient()
    service = make_phyllo_service(db_session, phyllo)
    session = service.create_session(current=current_one(), objective="grow_audience")
    service.create_phyllo_connect_token(current=current_one(), session_id=str(session["id"]))

    with pytest.raises(HTTPException) as exc:
        service.connect_fake_account(
            current=current_one(),
            session_id=str(session["id"]),
            provider="instagram",
            handle="@simulado",
            display_name="Simulado",
            profile_url=None,
            followers_count=1,
            posts_count=1,
            average_engagement_rate=1.0,
        )

    assert exc.value.status_code == 409


def test_social_onboarding_reconciles_phyllo_connecting_session(
    db_session: Session,
) -> None:
    phyllo = FakePhylloClient()
    phyllo.accounts_by_user_id["phyllo-user-1"] = [
        {
            "id": "phyllo-account-recovered",
            "status": "connected",
            "work_platform_id": "9bb8913b-ddd9-430b-a66a-d74d846e6c66",
        }
    ]
    phyllo.accounts_by_id["phyllo-account-recovered"] = {
        "id": "phyllo-account-recovered",
        "user": {"id": "phyllo-user-1"},
        "work_platform_id": "9bb8913b-ddd9-430b-a66a-d74d846e6c66",
        "platform_username": "Recuperado",
        "display_name": "Perfil Recuperado",
        "status": "connected",
    }
    service = make_phyllo_service(db_session, phyllo)
    session = service.create_session(current=current_one(), objective="grow_audience")
    service.create_phyllo_connect_token(current=current_one(), session_id=str(session["id"]))

    reconciled = service.reconcile_phyllo_connecting_sessions(limit=10)

    assert len(reconciled) == 1
    assert reconciled[0]["session_id"] == str(session["id"])
    assert reconciled[0]["status"] == "analyzing"
    assert reconciled[0]["job_id"]
    row = db_session.execute(
        text(
            """
            SELECT status, connection_mode, connected_account_handle
            FROM social_onboarding_sessions
            WHERE id = :session_id
            """
        ),
        {"session_id": session["id"]},
    ).mappings().one()
    assert row["status"] == "analyzing"
    assert row["connection_mode"] == "oauth"
    assert row["connected_account_handle"] == "recuperado"


def test_social_onboarding_reconciler_isolates_candidate_phyllo_failures(
    db_session: Session,
) -> None:
    phyllo = FakePhylloClient()
    service = make_phyllo_service(db_session, phyllo)
    first = service.create_session(current=current_one(), objective="grow_audience")
    second = service.create_session(current=current_two(), objective="grow_audience")
    service.create_phyllo_connect_token(current=current_one(), session_id=str(first["id"]))
    service.create_phyllo_connect_token(current=current_two(), session_id=str(second["id"]))
    phyllo.list_accounts_errors.add("phyllo-user-1")
    phyllo.accounts_by_user_id["phyllo-user-2"] = [
        {
            "id": "phyllo-account-second",
            "status": "connected",
            "work_platform_id": "9bb8913b-ddd9-430b-a66a-d74d846e6c66",
        }
    ]
    phyllo.accounts_by_id["phyllo-account-second"] = {
        "id": "phyllo-account-second",
        "user": {"id": "phyllo-user-2"},
        "work_platform_id": "9bb8913b-ddd9-430b-a66a-d74d846e6c66",
        "platform_username": "SegundoPerfil",
        "display_name": "Segundo Perfil",
        "status": "connected",
    }

    reconciled = service.reconcile_phyllo_connecting_sessions(limit=10)

    assert len(reconciled) == 1
    assert reconciled[0]["session_id"] == str(second["id"])
    first_status = db_session.execute(
        text("SELECT status FROM social_onboarding_sessions WHERE id = :session_id"),
        {"session_id": first["id"]},
    ).scalar_one()
    second_row = db_session.execute(
        text(
            """
            SELECT status, connected_account_handle
            FROM social_onboarding_sessions
            WHERE id = :session_id
            """
        ),
        {"session_id": second["id"]},
    ).mappings().one()
    assert first_status == "connecting"
    assert second_row["status"] == "analyzing"
    assert second_row["connected_account_handle"] == "segundoperfil"


def test_social_onboarding_reconciler_prefers_connected_instagram_account(
    db_session: Session,
) -> None:
    phyllo = FakePhylloClient()
    service = make_phyllo_service(db_session, phyllo)
    session = service.create_session(current=current_one(), objective="grow_audience")
    service.create_phyllo_connect_token(current=current_one(), session_id=str(session["id"]))
    phyllo.accounts_by_user_id["phyllo-user-1"] = [
        {
            "id": "phyllo-expired-instagram",
            "status": "SESSION_EXPIRED",
            "work_platform_id": "9bb8913b-ddd9-430b-a66a-d74d846e6c66",
        },
        {
            "id": "phyllo-connected-youtube",
            "status": "CONNECTED",
            "work_platform_id": "youtube-platform",
        },
        {
            "id": "phyllo-connected-instagram",
            "status": "CONNECTED",
            "work_platform_id": "9bb8913b-ddd9-430b-a66a-d74d846e6c66",
        },
    ]
    phyllo.accounts_by_id["phyllo-connected-youtube"] = {
        "id": "phyllo-connected-youtube",
        "user": {"id": "phyllo-user-1"},
        "work_platform_id": "youtube-platform",
        "platform_username": "YoutubeErrado",
        "display_name": "YouTube Errado",
        "status": "connected",
    }
    phyllo.accounts_by_id["phyllo-connected-instagram"] = {
        "id": "phyllo-connected-instagram",
        "user": {"id": "phyllo-user-1"},
        "work_platform_id": "9bb8913b-ddd9-430b-a66a-d74d846e6c66",
        "platform_username": "InstagramCerto",
        "display_name": "Instagram Certo",
        "status": "connected",
    }

    reconciled = service.reconcile_phyllo_connecting_sessions(limit=10)

    assert len(reconciled) == 1
    row = db_session.execute(
        text(
            """
            SELECT connected_account_id, connected_account_handle
            FROM social_onboarding_sessions
            WHERE id = :session_id
            """
        ),
        {"session_id": session["id"]},
    ).mappings().one()
    assert row["connected_account_id"] == "phyllo-connected-instagram"
    assert row["connected_account_handle"] == "instagramcerto"


def test_social_onboarding_reconciler_expires_old_phyllo_connection(
    db_session: Session,
) -> None:
    phyllo = FakePhylloClient()
    service = make_phyllo_service(db_session, phyllo)
    session = service.create_session(current=current_one(), objective="grow_audience")
    service.create_phyllo_connect_token(current=current_one(), session_id=str(session["id"]))
    db_session.execute(
        text(
            """
            UPDATE social_onboarding_sessions
            SET updated_at = NOW() - INTERVAL '31 minutes'
            WHERE id = :session_id
            """
        ),
        {"session_id": session["id"]},
    )
    db_session.commit()

    reconciled = service.reconcile_phyllo_connecting_sessions(limit=10)

    assert reconciled == [
        {
            "session_id": str(session["id"]),
            "status": "failed",
            "reason": "phyllo_connection_timeout",
        }
    ]
    status = db_session.execute(
        text("SELECT status FROM social_onboarding_sessions WHERE id = :session_id"),
        {"session_id": session["id"]},
    ).scalar_one()
    assert status == "failed"


def test_social_onboarding_diagnose_requires_connected_profile(
    db_session: Session,
) -> None:
    service = make_service(db_session)
    session = service.create_session(current=current_one(), objective="authority")

    with pytest.raises(HTTPException) as exc:
        service.enqueue_diagnostic(current=current_one(), session_id=str(session["id"]))

    assert exc.value.status_code == 400


def test_social_onboarding_diagnose_rejects_already_analyzing_session(
    db_session: Session,
) -> None:
    service = make_service(db_session)
    session = service.create_session(current=current_one(), objective="authority")
    service.connect_fake_account(
        current=current_one(),
        session_id=str(session["id"]),
        provider="instagram",
        handle="@marca",
        display_name="Marca",
        profile_url=None,
        followers_count=1200,
        posts_count=80,
        average_engagement_rate=2.4,
    )

    with pytest.raises(HTTPException) as exc:
        service.enqueue_diagnostic(current=current_one(), session_id=str(session["id"]))

    assert exc.value.status_code == 409


def test_social_onboarding_create_archives_previous_current_session(
    db_session: Session,
) -> None:
    service = make_service(db_session)
    first = service.create_session(current=current_one(), objective="grow_audience")
    second = service.create_session(current=current_one(), objective="sell_more")

    first_status = db_session.execute(
        text("SELECT status FROM social_onboarding_sessions WHERE id = :session_id"),
        {"session_id": first["id"]},
    ).scalar_one()
    current = service.get_current(current=current_one())

    assert first_status == "archived"
    assert current is not None
    assert current["id"] == second["id"]
    assert current["objective"] == "sell_more"


def test_social_onboarding_job_rolls_back_retryable_db_error_without_marking_failed(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = make_service(db_session)
    session = service.create_session(current=current_one(), objective="authority")
    analyzing, _ = service.connect_fake_account(
        current=current_one(),
        session_id=str(session["id"]),
        provider="instagram",
        handle="@marca",
        display_name="Marca",
        profile_url=None,
        followers_count=1200,
        posts_count=80,
        average_engagement_rate=2.4,
    )

    class ExistingSessionContext:
        def __enter__(self) -> Session:
            return db_session

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(onboarding_jobs, "SessionLocal", lambda: ExistingSessionContext())
    monkeypatch.setattr(onboarding_service, "_build_report", lambda *_args: {"bad": "\x00"})

    with pytest.raises(SQLAlchemyError):
        onboarding_jobs.diagnose_social_onboarding(
            JobExecutionContext(
                job_id="job",
                tenant_id=str(TENANT_1),
                membership_id=None,
                job_type="social.onboarding.diagnose",
                queue_name="worker-social-analysis",
                payload={
                    "session_id": str(session["id"]),
                    "analysis_version": analyzing["analysis_version"],
                },
                attempts=1,
            )
        )

    still_analyzing = service.get_session(current=current_one(), session_id=str(session["id"]))
    assert still_analyzing["status"] == "analyzing"
    assert still_analyzing["error_code"] is None


def test_social_onboarding_retryable_failure_can_succeed_on_second_attempt(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = make_service(db_session)
    session = service.create_session(current=current_one(), objective="authority")
    analyzing, _ = service.connect_fake_account(
        current=current_one(),
        session_id=str(session["id"]),
        provider="instagram",
        handle="@marca",
        display_name="Marca",
        profile_url=None,
        followers_count=1200,
        posts_count=80,
        average_engagement_rate=2.4,
    )

    class ExistingSessionContext:
        def __enter__(self) -> Session:
            return db_session

        def __exit__(self, *args: object) -> None:
            return None

    original_build_report = onboarding_service._build_report
    calls = {"count": 0}

    def flaky_build_report(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("provider temporarily unavailable")
        return original_build_report(*args, **kwargs)

    monkeypatch.setattr(onboarding_jobs, "SessionLocal", lambda: ExistingSessionContext())
    monkeypatch.setattr(onboarding_service, "_build_report", flaky_build_report)

    with pytest.raises(RuntimeError):
        onboarding_jobs.diagnose_social_onboarding(
            JobExecutionContext(
                job_id="job-1",
                tenant_id=str(TENANT_1),
                membership_id=None,
                job_type="social.onboarding.diagnose",
                queue_name="worker-social-analysis",
                payload={
                    "session_id": str(session["id"]),
                    "analysis_version": analyzing["analysis_version"],
                },
                attempts=1,
            )
        )
    after_first = service.get_session(current=current_one(), session_id=str(session["id"]))
    assert after_first["status"] == "analyzing"
    assert after_first["error_code"] is None

    result = onboarding_jobs.diagnose_social_onboarding(
        JobExecutionContext(
            job_id="job-1",
            tenant_id=str(TENANT_1),
            membership_id=None,
            job_type="social.onboarding.diagnose",
            queue_name="worker-social-analysis",
            payload={
                "session_id": str(session["id"]),
                "analysis_version": analyzing["analysis_version"],
            },
            attempts=2,
        )
    )

    assert result["status"] == "ready"
    ready = service.get_session(current=current_one(), session_id=str(session["id"]))
    assert ready["status"] == "ready"
    assert ready["error_code"] is None


def test_social_onboarding_failed_mark_is_version_scoped(
    db_session: Session,
) -> None:
    service = make_service(db_session)
    session = service.create_session(current=current_one(), objective="grow_audience")
    first, _ = service.connect_fake_account(
        current=current_one(),
        session_id=str(session["id"]),
        provider="instagram",
        handle="@marca",
        display_name="Marca",
        profile_url=None,
        followers_count=1200,
        posts_count=80,
        average_engagement_rate=2.4,
    )
    service.run_diagnostic(
        tenant_id=str(TENANT_1),
        session_id=str(session["id"]),
        analysis_version=first["analysis_version"],
    )
    second, _ = service.connect_fake_account(
        current=current_one(),
        session_id=str(session["id"]),
        provider="youtube",
        handle="@marca_tv",
        display_name="Marca TV",
        profile_url=None,
        followers_count=2200,
        posts_count=120,
        average_engagement_rate=2.8,
    )
    service.run_diagnostic(
        tenant_id=str(TENANT_1),
        session_id=str(session["id"]),
        analysis_version=second["analysis_version"],
    )

    service.mark_diagnostic_failed(
        tenant_id=str(TENANT_1),
        session_id=str(session["id"]),
        analysis_version=first["analysis_version"],
        error_code="stale",
        error_message="old job failed late",
    )

    ready = service.get_session(current=current_one(), session_id=str(session["id"]))
    assert ready["status"] == "ready"
    assert ready["analysis_version"] == second["analysis_version"]
    assert ready["error_code"] is None


def test_social_onboarding_failed_mark_does_not_touch_newer_analyzing_version(
    db_session: Session,
) -> None:
    service = make_service(db_session)
    session = service.create_session(current=current_one(), objective="grow_audience")
    first, _ = service.connect_fake_account(
        current=current_one(),
        session_id=str(session["id"]),
        provider="instagram",
        handle="@marca",
        display_name="Marca",
        profile_url=None,
        followers_count=1200,
        posts_count=80,
        average_engagement_rate=2.4,
    )
    second, _ = service.connect_fake_account(
        current=current_one(),
        session_id=str(session["id"]),
        provider="youtube",
        handle="@marca_tv",
        display_name="Marca TV",
        profile_url=None,
        followers_count=2200,
        posts_count=120,
        average_engagement_rate=2.8,
    )

    service.mark_diagnostic_failed(
        tenant_id=str(TENANT_1),
        session_id=str(session["id"]),
        analysis_version=first["analysis_version"],
        error_code="stale",
        error_message="old job failed late",
    )

    analyzing = service.get_session(current=current_one(), session_id=str(session["id"]))
    assert analyzing["status"] == "analyzing"
    assert analyzing["analysis_version"] == second["analysis_version"]
    assert analyzing["error_code"] is None


def test_social_onboarding_reconciler_marks_stale_analyzing_failed(
    db_session: Session,
) -> None:
    service = make_service(db_session)
    stale = service.create_session(current=current_one(), objective="grow_audience")
    _connected, job = service.connect_fake_account(
        current=current_one(),
        session_id=str(stale["id"]),
        provider="instagram",
        handle="@marca",
        display_name="Marca",
        profile_url=None,
        followers_count=1200,
        posts_count=80,
        average_engagement_rate=2.4,
    )
    db_session.execute(
        text(
            """
            UPDATE jobs
            SET status = 'dead_letter',
                updated_at = NOW()
            WHERE id = :job_id
            """
        ),
        {"job_id": job.id},
    )
    db_session.commit()

    reconciled = service.reconcile_abandoned_analyses(
        limit=10,
    )

    assert len(reconciled) == 1
    failed = service.get_session(current=current_one(), session_id=str(stale["id"]))
    assert failed["status"] == "failed"
    assert failed["error_code"] == "analysis_abandoned"


def test_social_onboarding_reconciler_does_not_fail_old_pending_job(
    db_session: Session,
) -> None:
    service = make_service(db_session)
    pending = service.create_session(current=current_one(), objective="grow_audience")
    service.connect_fake_account(
        current=current_one(),
        session_id=str(pending["id"]),
        provider="instagram",
        handle="@marca",
        display_name="Marca",
        profile_url=None,
        followers_count=1200,
        posts_count=80,
        average_engagement_rate=2.4,
    )
    db_session.execute(
        text(
            """
            UPDATE social_onboarding_sessions
            SET analysis_started_at = NOW() - INTERVAL '2 hours'
            WHERE id = :session_id
            """
        ),
        {"session_id": pending["id"]},
    )
    db_session.commit()

    reconciled = service.reconcile_abandoned_analyses(
        limit=10,
    )

    assert reconciled == []
    still_analyzing = service.get_session(current=current_one(), session_id=str(pending["id"]))
    assert still_analyzing["status"] == "analyzing"
    assert still_analyzing["error_code"] is None


def test_social_onboarding_worker_does_not_flip_failed_session_to_ready(
    db_session: Session,
) -> None:
    service = make_service(db_session)
    session = service.create_session(current=current_one(), objective="grow_audience")
    analyzing, _ = service.connect_fake_account(
        current=current_one(),
        session_id=str(session["id"]),
        provider="instagram",
        handle="@marca",
        display_name="Marca",
        profile_url=None,
        followers_count=1200,
        posts_count=80,
        average_engagement_rate=2.4,
    )
    service.mark_diagnostic_failed(
        tenant_id=str(TENANT_1),
        session_id=str(session["id"]),
        analysis_version=analyzing["analysis_version"],
        error_code="analysis_abandoned",
        error_message="timed out",
    )

    result = service.run_diagnostic(
        tenant_id=str(TENANT_1),
        session_id=str(session["id"]),
        analysis_version=analyzing["analysis_version"],
    )

    assert result["skipped"] is True
    assert result["reason"] == "session_not_analyzing"
    failed = service.get_session(current=current_one(), session_id=str(session["id"]))
    assert failed["status"] == "failed"
    assert failed["error_code"] == "analysis_abandoned"


def test_social_content_draft_generation_keeps_single_current_real_postgres(
    db_session: Session,
) -> None:
    service = make_service(db_session)
    seeded = seed_social_calendar_entry(db_session, service)

    first = service.generate_content_draft(
        current=current_one(),
        entry_id=str(seeded["entry_id"]),
    )
    second = service.generate_content_draft(
        current=current_one(),
        entry_id=str(seeded["entry_id"]),
    )

    rows = db_session.execute(
        text(
            """
            SELECT draft_version, is_current
            FROM social_content_drafts
            WHERE tenant_id = :tenant_id
              AND calendar_entry_id = :entry_id
            ORDER BY draft_version
            """
        ),
        {"tenant_id": TENANT_1, "entry_id": seeded["entry_id"]},
    ).mappings().all()

    assert first["draft_version"] == 1
    assert second["draft_version"] == 2
    assert [(row["draft_version"], row["is_current"]) for row in rows] == [
        (1, False),
        (2, True),
    ]


def test_social_content_draft_archive_releases_current_slot_real_postgres(
    db_session: Session,
) -> None:
    service = make_service(db_session)
    seeded = seed_social_calendar_entry(db_session, service)
    draft = service.generate_content_draft(
        current=current_one(),
        entry_id=str(seeded["entry_id"]),
    )

    archived = service.update_content_draft(
        current=current_one(),
        draft_id=str(draft["id"]),
        patch={"status": "archived"},
    )

    assert archived["status"] == "archived"
    assert archived["is_current"] is False
    with pytest.raises(HTTPException) as exc_info:
        service.get_current_content_draft(
            current=current_one(),
            entry_id=str(seeded["entry_id"]),
        )
    assert exc_info.value.status_code == 404

    next_draft = service.generate_content_draft(
        current=current_one(),
        entry_id=str(seeded["entry_id"]),
    )

    assert next_draft["draft_version"] == 2
    assert next_draft["is_current"] is True


def test_social_content_draft_update_rejects_cross_tenant_real_postgres(
    db_session: Session,
) -> None:
    service = make_service(db_session)
    seeded = seed_social_calendar_entry(db_session, service)
    draft = service.generate_content_draft(
        current=current_one(),
        entry_id=str(seeded["entry_id"]),
    )

    with pytest.raises(HTTPException) as exc_info:
        service.update_content_draft(
            current=current_two(),
            draft_id=str(draft["id"]),
            patch={"title": "Tentativa de outro tenant"},
        )

    assert exc_info.value.status_code == 404
