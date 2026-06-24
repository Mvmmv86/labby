from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.v2.labby.social_onboarding import get_social_onboarding_service
from app.core.dependencies import CurrentMembership, get_current_membership
from app.domains.jobs.job_service import JobRecord
from app.main import create_app

TENANT_ID = UUID("22222222-2222-2222-2222-222222222222")
MEMBERSHIP_ID = UUID("33333333-3333-3333-3333-333333333333")
SESSION_ID = UUID("44444444-4444-4444-4444-444444444444")
REFERENCE_ID = UUID("55555555-5555-5555-5555-555555555555")
JOB_ID = UUID("66666666-6666-6666-6666-666666666666")
PLAN_ID = UUID("77777777-7777-7777-7777-777777777777")
ACTION_ITEM_ID = UUID("88888888-8888-8888-8888-888888888888")
CALENDAR_ENTRY_ID = UUID("99999999-9999-9999-9999-999999999999")
DRAFT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


class FakeSocialOnboardingService:
    def __init__(self) -> None:
        self.current = None
        self.created_objective = None
        self.connected_payload = None
        self.reference_payload = None

    def get_current(self, *, current):
        self.current = current
        return make_session_row()

    def create_session(self, *, current, objective):
        self.current = current
        self.created_objective = objective
        return make_session_row(objective=objective)

    def get_session(self, *, current, session_id):
        self.current = current
        return make_session_row(id=UUID(str(session_id)))

    def update_session(self, *, current, session_id, patch):
        self.current = current
        return make_session_row(id=UUID(str(session_id)), **patch)

    def connect_fake_account(
        self,
        *,
        current,
        session_id,
        provider,
        handle,
        display_name,
        profile_url,
        followers_count,
        posts_count,
        average_engagement_rate,
    ):
        self.current = current
        self.connected_payload = {
            "session_id": session_id,
            "provider": provider,
            "handle": handle,
            "display_name": display_name,
            "profile_url": profile_url,
            "followers_count": followers_count,
            "posts_count": posts_count,
            "average_engagement_rate": average_engagement_rate,
        }
        return (
            make_session_row(
                id=UUID(str(session_id)),
                status="analyzing",
                primary_provider=provider,
                connection_mode="simulated",
                connected_account_handle=handle.strip().lstrip("@").lower(),
            ),
            make_job_record(),
        )

    def create_phyllo_connect_token(self, *, current, session_id):
        self.current = current
        return {
            "user_id": "phyllo-user",
            "sdk_token": "sdk-token",
            "environment": "staging",
            "client_display_name": "Labby",
            "work_platform_id": "instagram-platform",
            "products": ["IDENTITY", "ENGAGEMENT"],
        }

    def complete_phyllo_connection(
        self,
        *,
        current,
        session_id,
        phyllo_user_id,
        account_id,
        work_platform_id,
    ):
        self.current = current
        self.connected_payload = {
            "session_id": session_id,
            "phyllo_user_id": phyllo_user_id,
            "account_id": account_id,
            "work_platform_id": work_platform_id,
        }
        return (
            make_session_row(
                id=UUID(str(session_id)),
                status="analyzing",
                primary_provider="instagram",
                connection_mode="oauth",
                connected_account_handle="marca",
            ),
            make_job_record(),
        )

    def add_reference(self, *, current, session_id, provider, handle, label, profile_url):
        self.current = current
        self.reference_payload = {
            "session_id": session_id,
            "provider": provider,
            "handle": handle,
            "label": label,
            "profile_url": profile_url,
        }
        return make_reference_row(provider=provider, handle=handle.strip().lstrip("@").lower())

    def enqueue_reference_sync(self, *, current, session_id, reference_id):
        self.current = current
        self.reference_payload = {
            "session_id": session_id,
            "reference_id": reference_id,
        }
        return (
            make_reference_row(
                id=UUID(str(reference_id)),
                sync_status="pending",
                global_sync_status="pending",
            ),
            make_job_record(
                job_type="social.references.sync",
                idempotency_key="social.references.sync:instagram:referencia:v2",
            ),
        )

    def enqueue_diagnostic(self, *, current, session_id):
        self.current = current
        return make_session_row(id=UUID(str(session_id)), status="analyzing"), make_job_record()

    def enqueue_specialist_analysis(self, *, current, session_id):
        self.current = current
        return (
            make_session_row(
                id=UUID(str(session_id)),
                status="ready",
                analysis_report={
                    "specialist_brief": {"ready_for_ai": True},
                    "specialist_analysis": {
                        "status": "queued",
                        "analysis_version": 1,
                    },
                },
            ),
            make_job_record(
                job_type="social.onboarding.specialist_analysis",
                idempotency_key=f"social.onboarding.specialist:{session_id}:v1",
            ),
        )

    def get_action_plan(self, *, current, session_id):
        self.current = current
        return make_action_plan_row(onboarding_session_id=UUID(str(session_id)))

    def generate_action_plan(self, *, current, session_id):
        self.current = current
        return make_action_plan_row(onboarding_session_id=UUID(str(session_id)))

    def update_action_plan_item(self, *, current, item_id, patch):
        self.current = current
        self.connected_payload = {"item_id": item_id, "patch": patch}
        return make_action_plan_row(
            items=[
                make_action_item_row(
                    id=UUID(str(item_id)),
                    status=patch.get("status") or "pending",
                )
            ]
        )

    def update_calendar_entry(self, *, current, entry_id, patch):
        self.current = current
        self.connected_payload = {"entry_id": entry_id, "patch": patch}
        return make_action_plan_row(
            calendar_entries=[
                make_calendar_entry_row(
                    id=UUID(str(entry_id)),
                    status=patch.get("status") or "planned",
                )
            ]
        )

    def get_current_content_draft(self, *, current, entry_id):
        self.current = current
        return make_content_draft_row(calendar_entry_id=UUID(str(entry_id)))

    def generate_content_draft(self, *, current, entry_id):
        self.current = current
        self.connected_payload = {"entry_id": entry_id}
        return make_content_draft_row(calendar_entry_id=UUID(str(entry_id)), draft_version=2)

    def update_content_draft(self, *, current, draft_id, patch):
        self.current = current
        self.connected_payload = {"draft_id": draft_id, "patch": patch}
        return make_content_draft_row(id=UUID(str(draft_id)), **patch)

    def request_content_production(self, *, current, draft_id):
        self.current = current
        self.connected_payload = {"draft_id": draft_id}
        return make_content_draft_row(
            id=UUID(str(draft_id)),
            status="approved",
            production_status="queued",
            production_version=1,
        )


def make_current(modules: tuple[str, ...] = ("social_media",)) -> CurrentMembership:
    return CurrentMembership(
        user_id=UUID("11111111-1111-1111-1111-111111111111"),
        tenant_id=TENANT_ID,
        membership_id=MEMBERSHIP_ID,
        email="admin@example.com",
        nome="Admin",
        role="admin",
        modules=modules,
    )


def make_reference_row(**overrides):
    now = datetime(2026, 6, 8, tzinfo=UTC)
    row = {
        "id": REFERENCE_ID,
        "public_reference_profile_id": None,
        "provider": "instagram",
        "handle": "referencia",
        "label": "Referencia",
        "profile_url": "https://instagram.com/referencia",
        "status": "active",
        "sync_status": "manual_pending",
        "global_sync_status": "manual_pending",
        "public_contents_count": 0,
        "last_synced_at": None,
        "global_last_synced_at": None,
        "data_truth": {"source": "manual_input"},
        "comparison_summary": {},
        "created_at": now,
    }
    row.update(overrides)
    return row


def make_action_item_row(**overrides):
    now = datetime(2026, 6, 8, tzinfo=UTC)
    row = {
        "id": ACTION_ITEM_ID,
        "position": 1,
        "title": "Refinar promessa da bio",
        "description": "Transformar a promessa em uma frase mensuravel.",
        "why_it_matters": "A bio cria expectativa e qualifica o publico.",
        "how_to_execute": "Escrever para quem, dor, resultado e proximo passo.",
        "expected_signal": "Mais visitas qualificadas e respostas no perfil.",
        "measurement": "Comparar visitas e replies antes/depois.",
        "evidence": "Bio lida e posts reais apontam promessa pouco especifica.",
        "priority": "high",
        "status": "pending",
        "source_json": {"provider": "test"},
        "notes": None,
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    return row


def make_content_draft_row(**overrides):
    now = datetime(2026, 6, 8, tzinfo=UTC)
    row = {
        "id": DRAFT_ID,
        "calendar_entry_id": CALENDAR_ENTRY_ID,
        "action_plan_id": PLAN_ID,
        "onboarding_session_id": SESSION_ID,
        "draft_version": 1,
        "status": "draft",
        "format": "REEL",
        "channel": "instagram",
        "title": "Reel de prova social",
        "angle": "Mostrar uma transformacao concreta.",
        "hook": "O que mudou quando a promessa ficou clara.",
        "caption": "Gancho\n\nEvidencia\n\nCTA",
        "cta": "Comente sua duvida",
        "visual_direction": "Video vertical com cortes curtos.",
        "script_json": [
            {"label": "Abertura", "instruction": "Comecar pelo conflito."},
        ],
        "production_checklist_json": [
            {"label": "Validar evidencia real", "done": False},
        ],
        "evidence_json": {"source_reference_handle": "referencia"},
        "metadata_json": {"generated_by": "test"},
        "is_current": True,
        "production_status": "not_started",
        "production_version": 0,
        "production_payload_json": {},
        "production_error_code": None,
        "production_error_message": None,
        "production_provider": None,
        "production_model": None,
        "production_input_tokens": None,
        "production_output_tokens": None,
        "production_cost_usd": 0,
        "production_started_at": None,
        "production_completed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    return row


def make_calendar_entry_row(**overrides):
    now = datetime(2026, 6, 8, tzinfo=UTC)
    row = {
        "id": CALENDAR_ENTRY_ID,
        "action_item_id": ACTION_ITEM_ID,
        "scheduled_at": now,
        "day_index": 1,
        "title": "Reel de prova social",
        "format": "REELS / VIDEO",
        "channel": "instagram",
        "status": "planned",
        "theme": "Prova social",
        "hook": "O que mudou quando a promessa ficou clara.",
        "caption_outline": "Abrir com dor, mostrar evidencia e fechar com CTA.",
        "cta": "Responder com uma duvida.",
        "evidence": "Top contents reais e referencias sincronizadas.",
        "objective": "Aumentar comentarios qualificados.",
        "source_reference_handle": "referencia",
        "metrics_goal_json": {"target": "comments"},
        "metadata_json": {"source": "test"},
        "current_draft": None,
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    return row


def make_action_plan_row(**overrides):
    now = datetime(2026, 6, 8, tzinfo=UTC)
    row = {
        "id": PLAN_ID,
        "tenant_id": TENANT_ID,
        "onboarding_session_id": SESSION_ID,
        "title": "Plano social inicial",
        "summary": "Plano de 7 dias baseado no diagnostico especialista.",
        "status": "active",
        "source_analysis_version": 4,
        "source_specialist_version": "social_specialist_v1",
        "plan_version": 1,
        "metadata_json": {"mode": "comparativo"},
        "items": [make_action_item_row()],
        "calendar_entries": [make_calendar_entry_row()],
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    return row


def make_session_row(**overrides):
    now = datetime(2026, 6, 8, tzinfo=UTC)
    row = {
        "id": SESSION_ID,
        "tenant_id": TENANT_ID,
        "objective": "grow_audience",
        "status": "draft",
        "primary_provider": None,
        "connection_mode": "none",
        "connected_account_handle": None,
        "connected_account_name": None,
        "profile_url": None,
        "progress_steps": [{"key": "objective", "label": "Objetivo", "status": "done"}],
        "profile_snapshot": {},
        "analysis_report": None,
        "analysis_version": 0,
        "references": [make_reference_row()],
        "error_code": None,
        "error_message": None,
        "analysis_started_at": None,
        "analysis_completed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    return row


def make_job_record(**overrides):
    now = datetime(2026, 6, 8, tzinfo=UTC)
    row = {
        "id": str(JOB_ID),
        "tenant_id": str(TENANT_ID),
        "membership_id": str(MEMBERSHIP_ID),
        "job_type": "social.onboarding.diagnose",
        "queue_name": "worker-social-analysis",
        "status": "pending",
        "priority": 0,
        "idempotency_key": "social.onboarding.diagnose:session:v1",
        "payload": {"session_id": str(SESSION_ID)},
        "result": None,
        "error_code": None,
        "error_message": None,
        "attempts": 0,
        "max_attempts": 3,
        "run_after": now,
        "locked_at": None,
        "locked_by": None,
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    return JobRecord(**row)


def make_client(
    service: FakeSocialOnboardingService | None = None,
    *,
    modules: tuple[str, ...] = ("social_media",),
) -> tuple[TestClient, FakeSocialOnboardingService]:
    fake_service = service or FakeSocialOnboardingService()
    app = create_app()
    app.dependency_overrides[get_social_onboarding_service] = lambda: fake_service
    app.dependency_overrides[get_current_membership] = lambda: make_current(modules)
    return TestClient(app), fake_service


def test_create_social_onboarding_session_requires_social_module() -> None:
    client, _ = make_client(modules=("sales",))

    response = client.post(
        "/api/v2/labby/social/onboarding/sessions",
        json={"objective": "grow_audience"},
    )

    assert response.status_code == 403


def test_social_onboarding_current_contract() -> None:
    client, service = make_client()

    response = client.get("/api/v2/labby/social/onboarding/current")

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["id"] == str(SESSION_ID)
    assert body["session"]["references"][0]["handle"] == "referencia"
    assert service.current.tenant_id == TENANT_ID


def test_create_social_onboarding_session_contract() -> None:
    client, service = make_client()

    response = client.post(
        "/api/v2/labby/social/onboarding/sessions",
        json={"objective": "benchmarking"},
    )

    assert response.status_code == 201
    assert response.json()["objective"] == "benchmarking"
    assert service.created_objective == "benchmarking"


def test_connect_fake_account_enqueues_diagnostic_contract() -> None:
    client, service = make_client()

    response = client.post(
        f"/api/v2/labby/social/onboarding/sessions/{SESSION_ID}/fake-connect",
        json={
            "provider": "instagram",
            "handle": "@MinhaMarca",
            "display_name": "Minha Marca",
            "followers_count": 1200,
            "posts_count": 88,
            "average_engagement_rate": 2.4,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["status"] == "analyzing"
    assert body["session"]["connected_account_handle"] == "minhamarca"
    assert body["job"]["job_type"] == "social.onboarding.diagnose"
    assert service.connected_payload["handle"] == "@MinhaMarca"


def test_create_phyllo_connect_token_contract() -> None:
    client, _ = make_client()

    response = client.post(
        f"/api/v2/labby/social/onboarding/sessions/{SESSION_ID}/phyllo/connect-token",
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "user_id": "phyllo-user",
        "sdk_token": "sdk-token",
        "environment": "staging",
        "client_display_name": "Labby",
        "work_platform_id": "instagram-platform",
        "products": ["IDENTITY", "ENGAGEMENT"],
    }


def test_complete_phyllo_connection_contract() -> None:
    client, service = make_client()

    response = client.post(
        f"/api/v2/labby/social/onboarding/sessions/{SESSION_ID}/phyllo/complete",
        json={
            "user_id": "phyllo-user",
            "account_id": "phyllo-account",
            "work_platform_id": "instagram-platform",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["connection_mode"] == "oauth"
    assert body["session"]["connected_account_handle"] == "marca"
    assert body["job"]["job_type"] == "social.onboarding.diagnose"
    assert service.connected_payload["account_id"] == "phyllo-account"


def test_add_reference_contract() -> None:
    client, service = make_client()

    response = client.post(
        f"/api/v2/labby/social/onboarding/sessions/{SESSION_ID}/references",
        json={
            "provider": "x",
            "handle": "@referencia_crypto",
            "label": "Referencia crypto",
        },
    )

    assert response.status_code == 201
    assert response.json()["handle"] == "referencia_crypto"
    assert response.json()["sync_status"] == "manual_pending"
    assert response.json()["public_contents_count"] == 0
    assert service.reference_payload["provider"] == "x"


def test_sync_reference_contract() -> None:
    client, service = make_client()

    response = client.post(
        f"/api/v2/labby/social/onboarding/sessions/{SESSION_ID}/references/{REFERENCE_ID}/sync",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reference"]["id"] == str(REFERENCE_ID)
    assert body["reference"]["sync_status"] == "pending"
    assert body["job"]["job_type"] == "social.references.sync"
    assert service.reference_payload == {
        "session_id": str(SESSION_ID),
        "reference_id": str(REFERENCE_ID),
    }


def test_enqueue_specialist_analysis_contract() -> None:
    client, service = make_client()

    response = client.post(
        f"/api/v2/labby/social/onboarding/sessions/{SESSION_ID}/specialist-analysis",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["status"] == "ready"
    assert body["session"]["analysis_report"]["specialist_analysis"]["status"] == "queued"
    assert body["job"]["job_type"] == "social.onboarding.specialist_analysis"
    assert service.current.tenant_id == TENANT_ID


def test_get_action_plan_contract() -> None:
    client, service = make_client()

    def get_action_plan_with_draft(*, current, session_id):
        service.current = current
        return make_action_plan_row(
            onboarding_session_id=UUID(str(session_id)),
            calendar_entries=[make_calendar_entry_row(current_draft=make_content_draft_row())],
        )

    service.get_action_plan = get_action_plan_with_draft

    response = client.get(
        f"/api/v2/labby/social/onboarding/sessions/{SESSION_ID}/action-plan",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(PLAN_ID)
    assert body["items"][0]["why_it_matters"]
    assert body["items"][0]["how_to_execute"]
    assert body["calendar_entries"][0]["format"] == "REELS / VIDEO"
    assert body["calendar_entries"][0]["current_draft"]["id"] == str(DRAFT_ID)
    assert service.current.tenant_id == TENANT_ID


def test_generate_action_plan_contract() -> None:
    client, service = make_client()

    response = client.post(
        f"/api/v2/labby/social/onboarding/sessions/{SESSION_ID}/action-plan/generate",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "active"
    assert body["source_analysis_version"] == 4
    assert body["calendar_entries"][0]["hook"]
    assert service.current.tenant_id == TENANT_ID


def test_update_action_plan_item_contract() -> None:
    client, service = make_client()

    response = client.patch(
        f"/api/v2/labby/social/onboarding/action-plan/items/{ACTION_ITEM_ID}",
        json={"status": "done", "notes": "Feito no smoke"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["id"] == str(ACTION_ITEM_ID)
    assert body["items"][0]["status"] == "done"
    assert service.connected_payload == {
        "item_id": str(ACTION_ITEM_ID),
        "patch": {"status": "done", "notes": "Feito no smoke"},
    }


def test_update_calendar_entry_contract() -> None:
    client, service = make_client()

    response = client.patch(
        f"/api/v2/labby/social/onboarding/action-plan/calendar/{CALENDAR_ENTRY_ID}",
        json={
            "status": "scheduled",
            "title": "Reel ajustado",
            "format": "REEL",
            "channel": "instagram",
            "theme": "prova social",
            "hook": "Abrir com uma objecao real do publico.",
            "caption_outline": "Roteiro manual revisado",
            "cta": "Comente sua duvida",
            "evidence": "Post de referencia com alto comentario.",
            "objective": "Medir comentarios qualificados.",
            "source_reference_handle": "evandro_pit",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["calendar_entries"][0]["id"] == str(CALENDAR_ENTRY_ID)
    assert body["calendar_entries"][0]["status"] == "scheduled"
    assert service.connected_payload == {
        "entry_id": str(CALENDAR_ENTRY_ID),
        "patch": {
            "status": "scheduled",
            "title": "Reel ajustado",
            "format": "REEL",
            "channel": "instagram",
            "theme": "prova social",
            "hook": "Abrir com uma objecao real do publico.",
            "caption_outline": "Roteiro manual revisado",
            "cta": "Comente sua duvida",
            "evidence": "Post de referencia com alto comentario.",
            "objective": "Medir comentarios qualificados.",
            "source_reference_handle": "evandro_pit",
        },
    }


def test_get_current_content_draft_contract() -> None:
    client, service = make_client()

    response = client.get(
        f"/api/v2/labby/social/onboarding/action-plan/calendar/{CALENDAR_ENTRY_ID}/drafts/current",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(DRAFT_ID)
    assert body["calendar_entry_id"] == str(CALENDAR_ENTRY_ID)
    assert body["script_json"][0]["label"] == "Abertura"
    assert service.current.tenant_id == TENANT_ID


def test_generate_content_draft_contract() -> None:
    client, service = make_client()

    response = client.post(
        f"/api/v2/labby/social/onboarding/action-plan/calendar/{CALENDAR_ENTRY_ID}/drafts/generate",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["draft_version"] == 2
    assert body["status"] == "draft"
    assert body["production_checklist_json"][0]["label"] == "Validar evidencia real"
    assert service.connected_payload == {"entry_id": str(CALENDAR_ENTRY_ID)}


def test_update_content_draft_contract() -> None:
    client, service = make_client()

    response = client.patch(
        f"/api/v2/labby/social/onboarding/action-plan/calendar/drafts/{DRAFT_ID}",
        json={
            "status": "in_review",
            "title": "Reel revisado",
            "caption": "Legenda ajustada manualmente",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(DRAFT_ID)
    assert body["status"] == "in_review"
    assert body["title"] == "Reel revisado"
    assert body["caption"] == "Legenda ajustada manualmente"
    assert service.connected_payload == {
        "draft_id": str(DRAFT_ID),
        "patch": {
            "status": "in_review",
            "title": "Reel revisado",
            "caption": "Legenda ajustada manualmente",
        },
    }


def test_request_content_production_contract() -> None:
    client, service = make_client()

    response = client.post(
        f"/api/v2/labby/social/onboarding/action-plan/calendar/drafts/{DRAFT_ID}/production"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(DRAFT_ID)
    assert body["status"] == "approved"
    assert body["production_status"] == "queued"
    assert body["production_version"] == 1
    assert body["production_payload_json"] == {}
    assert service.connected_payload == {"draft_id": str(DRAFT_ID)}


def test_update_content_draft_rejects_oversized_structured_payload() -> None:
    client, service = make_client()

    response = client.patch(
        f"/api/v2/labby/social/onboarding/action-plan/calendar/drafts/{DRAFT_ID}",
        json={"script_json": [{"label": f"Bloco {index}"} for index in range(13)]},
    )

    assert response.status_code == 422
    assert service.connected_payload is None
