"""Tests for the evidence API (M8) and the case evidence backfill."""
import uuid

import pytest
from fastapi.testclient import TestClient

from agents.audit.main import app
from agents.audit.services.case_grouping_service import backfill_case_evidence
from agents.audit.services.case_service import open_case
from agents.audit.services.evidence_service import evidence_for
from agents.audit.tests.test_case_grouping import old_exception, rule_for
from agents.audit.tests.test_cases_api import AUDITOR_A, AUDITOR_B, BOARD, MANAGER, as_user, case
from agents.audit.tests.test_documents import PDF, temp_storage  # noqa: F401  (fixture: files go to tmp)
from shared.audit_log import list_for_entity
from shared.config import settings
from shared.db import get_db

client = TestClient(app)
HOSPITAL = uuid.UUID(as_user("AM", MANAGER)["X-Tenant-Id"])     # the hospital the case helpers use


@pytest.fixture(autouse=True)
def api_setup(monkeypatch, db_session):
    monkeypatch.setattr(settings, "environment", "development")
    app.dependency_overrides[get_db] = lambda: db_session
    yield
    app.dependency_overrides.pop(get_db, None)


def upload(case_id, roles="AM", user=MANAGER, data=PDF, filename="approval.pdf", content_type="application/pdf"):
    return client.post(f"/api/v1/audit/cases/{case_id}/evidence", headers=as_user(roles, user),
                       data={"title": "Approval email"}, files={"file": (filename, data, content_type)})


def test_upload_list_and_download_same_bytes(db_session):
    c = case(db_session, "HIGH", AUDITOR_A)
    db_session.commit()
    r = upload(c.id)
    assert r.status_code == 201, r.text
    evidence = r.json()
    assert (evidence["filename"], evidence["is_snapshot"], evidence["status"]) == ("approval.pdf", False, "ACTIVE")

    listed = client.get(f"/api/v1/audit/cases/{c.id}/evidence", headers=as_user("AUD", AUDITOR_A)).json()
    assert [e["id"] for e in listed] == [evidence["id"]]
    download = client.get(f"/api/v1/audit/evidence/{evidence['id']}/download", headers=as_user("AUD", AUDITOR_A))
    assert download.status_code == 200 and download.content == PDF
    assert download.headers["content-type"] == "application/pdf"
    assert client.post(f"/api/v1/audit/evidence/{evidence['id']}/verify",
                       headers=as_user("AUD", AUDITOR_A)).json() == {"ok": True}


def test_wrong_file_type_is_422(db_session):
    c = case(db_session, "HIGH")
    db_session.commit()
    r = upload(c.id, filename="tool.exe", content_type="application/octet-stream")
    assert r.status_code == 422


def test_auditor_cannot_see_evidence_of_someone_elses_case(db_session):
    c = case(db_session, "HIGH", AUDITOR_A)
    db_session.commit()
    evidence_id = upload(c.id).json()["id"]
    assert client.get(f"/api/v1/audit/evidence/{evidence_id}", headers=as_user("AUD", AUDITOR_B)).status_code == 404
    assert client.get(f"/api/v1/audit/cases/{c.id}/evidence", headers=as_user("AUD", AUDITOR_B)).status_code == 404


def test_management_can_read_but_not_upload(db_session):
    c = case(db_session, "HIGH")
    db_session.commit()
    upload(c.id)
    assert client.get(f"/api/v1/audit/cases/{c.id}/evidence", headers=as_user("MGT", BOARD)).status_code == 200
    assert upload(c.id, roles="MGT", user=BOARD).status_code == 403


def test_tampered_file_gives_409_and_the_alert_is_kept(db_session, temp_storage):
    c = case(db_session, "HIGH")
    db_session.commit()
    evidence_id = uuid.UUID(upload(c.id).json()["id"])
    [item] = evidence_for(db_session, HOSPITAL, "CASE", c.id)
    (temp_storage / f"{item.tenant_id}/{item.document_id}").write_bytes(b"replaced")

    r = client.get(f"/api/v1/audit/evidence/{evidence_id}/download", headers=as_user("AM", MANAGER))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "INTEGRITY_FAILED"
    actions = [row.action for row in list_for_entity(db_session, HOSPITAL, "audit_evidence", evidence_id)]
    assert "evidence.integrity_failed" in actions                # committed, not rolled back
    notes = client.get("/api/v1/notifications", headers=as_user("AM", MANAGER)).json()
    assert any(n["kind"] == "evidence.integrity_failed" for n in notes)


def test_supersede_needs_a_reason(db_session):
    c = case(db_session, "HIGH")
    db_session.commit()
    evidence_id = upload(c.id).json()["id"]
    path = f"/api/v1/audit/evidence/{evidence_id}/supersede"
    assert client.post(path, json={"reason": "  "}, headers=as_user("AM", MANAGER)).status_code == 422
    r = client.post(path, json={"reason": "Wrong file"}, headers=as_user("AM", MANAGER))
    assert r.status_code == 200 and r.json()["status"] == "SUPERSEDED"


def test_backfill_gives_each_case_its_snapshot_evidence_once(db_session):
    tenant = uuid.uuid4()
    rule = rule_for(db_session, tenant)
    cases = []
    for _ in range(2):                         # cases opened the old way: exceptions but no evidence
        exception = old_exception(db_session, rule, uuid.uuid4())
        cases.append(open_case(db_session, tenant, domain="PROCUREMENT", title="Old case", source="RULE",
                               primary_entity_type="purchase_order", primary_entity_id=exception.entity_id,
                               priority="HIGH", actor_id=None, exception_ids=[exception.id]))
    assert backfill_case_evidence(db_session, tenant) == {"cases_updated": 2, "evidence_linked": 2}
    assert all(len(evidence_for(db_session, tenant, "CASE", c.id)) == 1 for c in cases)
    assert backfill_case_evidence(db_session, tenant) == {"cases_updated": 0, "evidence_linked": 0}
