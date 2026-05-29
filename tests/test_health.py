from fastapi.testclient import TestClient

from app.main import create_app


def test_root_health() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_labby_health() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v2/labby/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "labby-backend"

