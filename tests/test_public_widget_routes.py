from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.public_widget import get_public_widget_service
from app.main import create_app

WIDGET_ID = "labby_test_widget"
CONVERSATION_ID = UUID("abababab-abab-abab-abab-abababababab")
MESSAGE_ID = UUID("cdcdcdcd-cdcd-cdcd-cdcd-cdcdcdcdcdcd")


class FakePublicWidgetService:
    def __init__(self) -> None:
        self.loader_payload = None
        self.config_payload = None
        self.received_payload = None
        self.list_payload = None

    def loader_js(self, **kwargs):
        self.loader_payload = kwargs
        return "window.__labby_widget_test = true;"

    def config(self, **kwargs):
        self.config_payload = kwargs
        return {
            "widget_id": WIDGET_ID,
            "color": "#00d4aa",
            "greeting": "Ola",
            "position": "bottom-right",
            "name": "Labby Chat",
            "active": True,
        }

    def receive_message(self, **kwargs):
        self.received_payload = kwargs
        return {
            "status": "ok",
            "conversa_id": CONVERSATION_ID,
            "conversation_id": CONVERSATION_ID,
            "message_id": MESSAGE_ID,
            "duplicate": False,
            "bot_response": None,
            "last_message_id": MESSAGE_ID,
        }

    def list_messages(self, **kwargs):
        self.list_payload = kwargs
        return {
            "messages": [
                {
                    "id": MESSAGE_ID,
                    "content": "Ola",
                    "direction": "saida",
                    "sender_type": "bot",
                    "created_at": datetime(2026, 6, 3, tzinfo=UTC),
                }
            ],
            "conversation_id": CONVERSATION_ID,
            "last_message_id": MESSAGE_ID,
        }


def make_client(service: FakePublicWidgetService | None = None):
    fake_service = service or FakePublicWidgetService()
    app = create_app()
    app.dependency_overrides[get_public_widget_service] = lambda: fake_service
    return TestClient(app), fake_service


def test_public_widget_routes_are_available_without_auth() -> None:
    client, service = make_client()

    loader = client.get(f"/widget/{WIDGET_ID}/loader.js")
    assert loader.status_code == 200
    assert "application/javascript" in loader.headers["content-type"]
    assert service.loader_payload["widget_id"] == WIDGET_ID

    config = client.get(f"/widget/{WIDGET_ID}/config")
    assert config.status_code == 200
    assert config.json()["widget_id"] == WIDGET_ID

    sent = client.post(
        f"/widget/{WIDGET_ID}/messages",
        json={
            "visitor_id": "visitor-1",
            "visitor_name": "Paula",
            "message": "Oi",
            "client_message_id": "msg-1",
        },
    )
    assert sent.status_code == 200
    assert service.received_payload["visitor_id"] == "visitor-1"
    assert service.received_payload["client_message_id"] == "msg-1"

    listed = client.get(
        f"/widget/{WIDGET_ID}/messages",
        params={"visitor_id": "visitor-1", "after": str(MESSAGE_ID)},
    )
    assert listed.status_code == 200
    assert listed.json()["messages"][0]["content"] == "Ola"
    assert service.list_payload["after"] == str(MESSAGE_ID)
