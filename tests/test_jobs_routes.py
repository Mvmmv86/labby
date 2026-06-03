from uuid import UUID

from fastapi.testclient import TestClient

from app.api.v2.labby.jobs import get_job_queue_service
from app.core.dependencies import CurrentMembership, get_current_membership
from app.domains.jobs.job_service import QueueMetric, SalesOutboundStuckMetric
from app.main import create_app


class FakeJobQueueService:
    def __init__(self) -> None:
        self.tenant_id = None

    def queue_metrics(self, *, tenant_id: str):
        self.tenant_id = tenant_id
        return [
            QueueMetric(queue_name="worker-ai", status="pending", count=3),
            QueueMetric(queue_name="worker-email", status="dead_letter", count=1),
        ]

    def sales_outbound_stuck_metrics(self, *, tenant_id: str):
        self.tenant_id = tenant_id
        return [
            SalesOutboundStuckMetric(
                status="sending",
                count=2,
                oldest_created_at=None,
            )
        ]


def make_current_membership(role: str = "owner") -> CurrentMembership:
    return CurrentMembership(
        user_id=UUID("11111111-1111-1111-1111-111111111111"),
        tenant_id=UUID("22222222-2222-2222-2222-222222222222"),
        membership_id=UUID("33333333-3333-3333-3333-333333333333"),
        email="marcus@example.com",
        nome="Marcus",
        role=role,
        modules=("sales", "social_media"),
    )


def make_client(
    service: FakeJobQueueService | None = None,
    role: str = "owner",
) -> tuple[TestClient, FakeJobQueueService]:
    fake_service = service or FakeJobQueueService()
    app = create_app()
    app.dependency_overrides[get_job_queue_service] = lambda: fake_service
    app.dependency_overrides[get_current_membership] = lambda: make_current_membership(role)
    return TestClient(app), fake_service


def test_jobs_metrics_are_tenant_scoped() -> None:
    client, service = make_client()

    response = client.get("/api/v2/labby/jobs/metrics")

    assert response.status_code == 200
    assert service.tenant_id == "22222222-2222-2222-2222-222222222222"
    assert response.json()["metrics"] == [
        {"queue_name": "worker-ai", "status": "pending", "count": 3},
        {"queue_name": "worker-email", "status": "dead_letter", "count": 1},
    ]
    assert response.json()["sales_outbound_stuck"] == [
        {"status": "sending", "count": 2, "oldest_created_at": None}
    ]


def test_jobs_metrics_require_admin_role() -> None:
    client, _ = make_client(role="viewer")

    response = client.get("/api/v2/labby/jobs/metrics")

    assert response.status_code == 403
