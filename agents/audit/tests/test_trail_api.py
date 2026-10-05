"""Tests for the trail API endpoints."""
import uuid

import pytest
from fastapi.testclient import TestClient

from agents.audit.main import app
from agents.audit.services.snapshot_service import capture_snapshot
from shared.config import settings
from shared.db import get_db

client = TestClient(app)


@pytest.fixture(autouse=True)
def dev_login_and_shared_session(monkeypatch, db_session):
    # Dev header login on, and the API uses the test's session (rolled back afterwards).
    monkeypatch.setattr(settings, "environment", "development")
    app.dependency_overrides[get_db] = lambda: db_session
    yield
    app.dependency_overrides.pop(get_db, None)


def headers(tenant_id, roles="AUD"):
    return {"X-User-Id": str(uuid.uuid4()), "X-Tenant-Id": str(tenant_id), "X-Roles": roles}


def save(db, tenant_id, entity_type, data, entity_id=None):
    return capture_snapshot(
        db, tenant_id=tenant_id, source_system="procurement",
        entity_type=entity_type, entity_id=entity_id or uuid.uuid4(), data=data,
    )


def test_trail_requires_login():
    assert client.get("/api/v1/audit/trail/po/PO-1").status_code == 401


def test_auditee_cannot_view_trail():
    response = client.get("/api/v1/audit/trail/po/PO-1", headers=headers(uuid.uuid4(), "OWN"))
    assert response.status_code == 403


def test_auditor_sees_po_chain_of_own_tenant(db_session):
    tenant, po = uuid.uuid4(), f"PO-{uuid.uuid4().hex[:8]}"
    save(db_session, tenant, "purchase_order", {"po_number": po, "grand_total": 100})
    save(db_session, tenant, "grn", {"grn_number": "GRN-1", "po_number": po})

    response = client.get(f"/api/v1/audit/trail/po/{po}", headers=headers(tenant))

    assert response.status_code == 200
    body = response.json()
    assert [e["entity_type"] for e in body] == ["purchase_order", "grn"]
    assert all(e["checksum_ok"] for e in body)


def test_other_tenant_gets_empty_trail(db_session):
    tenant, po = uuid.uuid4(), f"PO-{uuid.uuid4().hex[:8]}"
    save(db_session, tenant, "purchase_order", {"po_number": po, "grand_total": 100})

    response = client.get(f"/api/v1/audit/trail/po/{po}", headers=headers(uuid.uuid4()))

    assert response.status_code == 200
    assert response.json() == []


def test_record_history_endpoint(db_session):
    tenant, po_id = uuid.uuid4(), uuid.uuid4()
    save(db_session, tenant, "purchase_order", {"po_number": "PO-H", "grand_total": 100}, po_id)
    save(db_session, tenant, "purchase_order", {"po_number": "PO-H", "grand_total": 120}, po_id)

    response = client.get(
        f"/api/v1/audit/source-records/purchase_order/{po_id}/history", headers=headers(tenant)
    )

    assert response.status_code == 200
    assert sorted(e["snapshot"]["grand_total"] for e in response.json()) == [100, 120]
