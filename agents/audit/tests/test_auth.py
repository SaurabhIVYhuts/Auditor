"""Tests for the temporary header login and permission enforcement."""
import uuid

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from agents.audit.api.deps import require_permission
from agents.audit.main import app
from shared.config import settings

client = TestClient(app)


def headers(roles: str) -> dict:
    return {"X-User-Id": str(uuid.uuid4()), "X-Tenant-Id": str(uuid.uuid4()), "X-Roles": roles}


@pytest.fixture(autouse=True)
def development_environment(monkeypatch):
    # Every test here starts in development mode, whatever .env says.
    monkeypatch.setattr(settings, "environment", "development")


def test_me_without_login_is_401():
    assert client.get("/api/v1/audit/me").status_code == 401


def test_me_with_invalid_ids_is_401():
    bad = {"X-User-Id": "not-a-uuid", "X-Tenant-Id": "also-bad", "X-Roles": "AM"}
    assert client.get("/api/v1/audit/me", headers=bad).status_code == 401


def test_me_shows_roles_and_permissions():
    response = client.get("/api/v1/audit/me", headers=headers("AM"))
    assert response.status_code == 200
    body = response.json()
    assert body["roles"] == ["AM"]
    assert "finding:confirm" in body["permissions"]


def test_role_codes_are_case_insensitive():
    response = client.get("/api/v1/audit/me", headers=headers(" aud , co "))
    assert response.json()["roles"] == ["AUD", "CO"]


def test_header_login_is_disabled_outside_development(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    response = client.get("/api/v1/audit/me", headers=headers("AM"))
    assert response.status_code == 401


# A tiny app used only in tests, to check require_permission on a protected endpoint.
_protected_app = FastAPI()


@_protected_app.post("/confirm")
def _confirm(user=Depends(require_permission("finding:confirm"))):
    return {"ok": True}


_protected = TestClient(_protected_app)


def test_protected_endpoint_without_login_is_401():
    assert _protected.post("/confirm").status_code == 401


def test_auditor_cannot_confirm_finding_403():
    assert _protected.post("/confirm", headers=headers("AUD")).status_code == 403


def test_audit_manager_can_confirm_finding_200():
    assert _protected.post("/confirm", headers=headers("AM")).status_code == 200
