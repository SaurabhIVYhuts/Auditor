"""Tests for the health endpoints."""
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


def test_database_health_ok():
    # Needs the local PostgreSQL running and a correct .env
    response = client.get("/api/v1/health/db")
    assert response.status_code == 200
    assert response.json() == {"database": "ok"}


def test_database_health_unavailable(monkeypatch):
    # Pretend the database is down, without actually stopping it
    monkeypatch.setattr("agents.audit.api.health.check_database", lambda: False)
    response = client.get("/api/v1/health/db")
    assert response.status_code == 503
    assert response.json() == {"database": "unavailable"}
