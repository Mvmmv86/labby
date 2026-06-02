from uuid import UUID

from fastapi.testclient import TestClient

from app.api.v2.labby.sales_webhooks import get_sales_webhook_receiver
from app.main import create_app

CHANNEL_ID = UUID("66666666-6666-6666-6666-666666666666")
EVENT_ID = UUID("77777777-7777-7777-7777-777777777777")
JOB_ID = UUID("88888888-8888-8888-8888-888888888888")


class FakeSalesWebhookReceiver:
    def __init__(self) -> None:
        self.payload = None
        self.headers = None

    def receive_evolution(self, **kwargs):
        self.payload = kwargs["payload"]
        self.headers = kwargs["headers"]
        return {
            "status": "queued",
            "webhook_event_id": EVENT_ID,
            "job_id": JOB_ID,
            "duplicate": False,
        }


def make_client(
    receiver: FakeSalesWebhookReceiver | None = None,
) -> tuple[TestClient, FakeSalesWebhookReceiver]:
    fake_receiver = receiver or FakeSalesWebhookReceiver()
    app = create_app()
    app.dependency_overrides[get_sales_webhook_receiver] = lambda: fake_receiver
    return TestClient(app), fake_receiver


def test_evolution_webhook_is_public_and_queues_event() -> None:
    client, receiver = make_client()

    response = client.post(
        f"/api/v2/labby/webhooks/evolution/{CHANNEL_ID}",
        json={
            "event": "messages.upsert",
            "data": {"key": {"id": "wa-1", "remoteJid": "5511999990000@s.whatsapp.net"}},
        },
        headers={"X-Labby-Webhook-Secret": "secret"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert receiver.payload["event"] == "messages.upsert"
    assert receiver.headers["x-labby-webhook-secret"] == "secret"
