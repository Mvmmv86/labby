from fastapi.testclient import TestClient

import app.api.v2.labby.health as labby_health
import app.main as app_main
from app.core.health import DependencyStatus


def test_root_healthz_returns_dependency_status(monkeypatch) -> None:
    def fake_readiness_status() -> tuple[bool, dict[str, DependencyStatus]]:
        return True, {
            "database": DependencyStatus(ok=True),
            "redis": DependencyStatus(ok=True),
        }

    monkeypatch.setattr(app_main, "readiness_status", fake_readiness_status)
    client = TestClient(app_main.create_app())

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["dependencies"]["database"]["ok"] is True
    assert response.json()["dependencies"]["redis"]["ok"] is True


def test_root_healthz_returns_503_when_dependency_fails(monkeypatch) -> None:
    def fake_readiness_status() -> tuple[bool, dict[str, DependencyStatus]]:
        return False, {
            "database": DependencyStatus(ok=True),
            "redis": DependencyStatus(ok=False, error="ConnectionError"),
        }

    monkeypatch.setattr(app_main, "readiness_status", fake_readiness_status)
    client = TestClient(app_main.create_app())

    response = client.get("/healthz")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["dependencies"]["redis"]["error"] == "ConnectionError"


def test_labby_healthz_uses_same_readiness_contract(monkeypatch) -> None:
    def fake_readiness_status() -> tuple[bool, dict[str, DependencyStatus]]:
        return True, {
            "database": DependencyStatus(ok=True),
            "redis": DependencyStatus(ok=True),
        }

    monkeypatch.setattr(labby_health, "readiness_status", fake_readiness_status)
    client = TestClient(app_main.create_app())

    response = client.get("/api/v2/labby/healthz")

    assert response.status_code == 200
    assert response.json()["service"] == "labby-backend"

