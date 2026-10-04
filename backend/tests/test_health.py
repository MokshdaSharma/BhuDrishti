"""Phase 0 — Health endpoint tests.

Run with:
    pytest backend/tests/test_health.py -v
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    """Return a synchronous test client (no DB required for Phase 0)."""
    return TestClient(app)


def test_health_returns_200(client: TestClient) -> None:
    """GET /api/v1/health must return HTTP 200."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200


def test_health_body_shape(client: TestClient) -> None:
    """Response must contain status, version, disclaimer, checks, timestamp."""
    response = client.get("/api/v1/health")
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    assert "Preliminary" in body["disclaimer"]
    assert isinstance(body["checks"], dict)
    assert isinstance(body["timestamp"], int)


def test_health_checks_present(client: TestClient) -> None:
    """Checks dict must contain expected keys."""
    body = client.get("/api/v1/health").json()
    checks = body["checks"]
    assert "database" in checks
    assert "redis" in checks
    assert "mock_model" in checks
    assert "gee" in checks


def test_health_mock_model_default(client: TestClient) -> None:
    """MOCK_MODEL should default to true in the test environment."""
    body = client.get("/api/v1/health").json()
    assert body["checks"]["mock_model"] == "true"


def test_health_gee_disabled_by_default(client: TestClient) -> None:
    """GEE must be disabled when ENABLE_GEE env var is not set."""
    body = client.get("/api/v1/health").json()
    assert body["checks"]["gee"] == "disabled"


def test_openapi_reachable(client: TestClient) -> None:
    """OpenAPI JSON schema must be accessible."""
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "ParcelAI"
