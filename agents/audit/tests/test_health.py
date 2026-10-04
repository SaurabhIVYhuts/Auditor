"""Tests for the health endpoint."""
from fastapi.testclient import TestClient

from agents.audit.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "auditor-agent"}


def test_unknown_url_returns_404():
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
