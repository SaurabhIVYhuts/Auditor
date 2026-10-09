"""Phase 4 exit check: the full human audit loop, through the API, with three different people.

Rahul (Audit Manager), Priya (Auditor), Sunita (department owner). From an automatic case to a
confirmed finding, a corrective action with proof, verification by someone else, and closure.
"""
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from agents.audit.demo.dev_users import PRIYA, RAHUL, SUNITA
from agents.audit.demo.phase2_scenario import run_phase2_scenario
from agents.audit.main import app
from agents.audit.services.case_service import _hospital_today, list_cases
from agents.audit.services.pack_seeder import activate_pack, seed_procurement_pack
from agents.audit.tests.test_documents import PDF, temp_storage  # noqa: F401  (fixture: files go to tmp)
from agents.audit.tests.test_phase3_exit import rule_code_of
from shared.config import settings
from shared.db import get_db

client = TestClient(app)
AUTHOR, APPROVER = uuid.uuid4(), uuid.uuid4()
ROLES = {RAHUL: "AM", PRIYA: "AUD", SUNITA: "OWN"}
FINDING = {
    "title": "PO-DEMO-1 approved without level-2 approval",
    "condition": "PO-DEMO-1 (Rs 150,000) was approved with no approvals recorded",
    "criteria": "Purchase policy: orders above the limit need level-2 approval",
    "cause": "The approval step was skipped in the procurement system",
    "effect": "Spending above the limit without the required check",
    "recommendation": "Obtain retrospective level-2 approval and enforce the approval step",
    "risk_level": "HIGH",
    "financial_impact": "150000.00",
}


@pytest.fixture(autouse=True)
def api_setup(monkeypatch, db_session):
    monkeypatch.setattr(settings, "environment", "development")
    app.dependency_overrides[get_db] = lambda: db_session
    yield
    app.dependency_overrides.pop(get_db, None)


def as_(user, tenant):
    """A small client for one person: as_(PRIYA, hospital)("POST", "/cases/...", json=...)."""
    def call(method, path, **kw):
        headers = {"X-User-Id": str(user), "X-Tenant-Id": str(tenant), "X-Roles": ROLES[user]}
        return client.request(method, f"/api/v1{path}", headers=headers, **kw)
    return call


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def upload(call, path, title, filename="proof.pdf"):
    return ok(call("POST", path, data={"title": title}, files={"file": (filename, PDF, "application/pdf")}), 201)


def test_full_human_audit_loop(db_session):
    hospital = uuid.uuid4()
    seed_procurement_pack(db_session, hospital, created_by=AUTHOR)
    activate_pack(db_session, hospital, approved_by=APPROVER)
    run_phase2_scenario(db_session, hospital)
    [case] = [c for c in list_cases(db_session, hospital) if rule_code_of(db_session, c) == "PRC-APR-01"]
    db_session.commit()          # like earlier requests; a refused call's rollback must not undo it
    rahul, priya, sunita = as_(RAHUL, hospital), as_(PRIYA, hospital), as_(SUNITA, hospital)
    c = f"/audit/cases/{case.id}"

    # 1. Rahul assigns Priya; Priya starts and checks the automatic snapshot evidence
    ok(rahul("POST", f"{c}/assign", json={"assignee_id": str(PRIYA)}))
    assert ok(priya("POST", f"{c}/status", json={"status": "IN_INVESTIGATION"}))["status"] == "IN_INVESTIGATION"
    [snapshot] = ok(priya("GET", f"{c}/evidence"))
    assert snapshot["is_snapshot"] and ok(priya("POST", f"/audit/evidence/{snapshot['id']}/verify")) == {"ok": True}

    # 2. Priya writes the finding, adds proof, submits; she cannot confirm her own finding
    finding = ok(priya("POST", f"{c}/findings", json=FINDING), 201)
    f = f"/audit/findings/{finding['id']}"
    assert (finding["status"], finding["case_number"]) == ("DRAFT", case.case_number)
    finding_file = upload(priya, f"{f}/evidence", "Procurement system approval screen")
    assert ok(priya("POST", f"{f}/submit"))["status"] == "UNDER_REVIEW"
    due = str(_hospital_today() + timedelta(days=14))
    refused = priya("POST", f"{f}/confirm", json={"owner_user_id": str(SUNITA), "due_date": due})
    assert refused.status_code == 403, refused.text

    # 3. Rahul confirms with Sunita as owner; Sunita is told and sees the finding, not its evidence
    confirmed = ok(rahul("POST", f"{f}/confirm", json={"owner_user_id": str(SUNITA), "due_date": due}))
    assert (confirmed["status"], confirmed["owner_user_id"], confirmed["confirmed_by"]) == (
        "CONFIRMED", str(SUNITA), str(RAHUL))
    assert ("finding.confirmed", finding["id"]) in [(n["kind"], n["entity_id"]) for n in ok(sunita("GET", "/notifications"))]
    seen = ok(sunita("GET", f))
    assert (seen["title"], seen["evidence"]) == (FINDING["title"], [])
    assert sunita("GET", f"/audit/evidence/{finding_file['id']}").status_code == 404
    for status in ("PENDING_REVIEW", "FINDING_CONFIRMED"):
        assert ok(priya("POST", f"{c}/status", json={"status": status}))["status"] == status

    # 4. Rahul creates the corrective action for Sunita; the case moves to ACTION_IN_PROGRESS
    action = ok(rahul("POST", f"{f}/actions", json={
        "description": "Obtain retrospective level-2 approval for PO-DEMO-1",
        "owner_user_id": str(SUNITA), "due_date": due}), 201)
    a = f"/audit/actions/{action['id']}"
    assert ok(rahul("GET", f))["status"] == "ACTION_ASSIGNED"
    assert ok(rahul("POST", f"{c}/status", json={"status": "ACTION_IN_PROGRESS"}))["status"] == "ACTION_IN_PROGRESS"

    # 5. Sunita does the work and hands it in; she cannot verify it herself
    assert [x["id"] for x in ok(sunita("GET", "/audit/actions?mine=true"))] == [action["id"]]
    assert ok(sunita("POST", f"{a}/start"))["status"] == "IN_PROGRESS"
    action_file = upload(sunita, f"{a}/evidence", "Signed level-2 approval")
    assert ok(sunita("POST", f"{a}/submit"))["status"] == "SUBMITTED"
    assert ok(rahul("GET", f))["status"] == "RESOLVED"
    assert sunita("POST", f"{a}/verify", json={}).status_code == 403

    # 6. The case cannot close while the finding and action are open
    still_open = rahul("POST", f"{c}/close")
    assert still_open.status_code == 409 and "still open" in still_open.json()["detail"]["message"]

    # 7. Priya verifies and closes the finding; Rahul closes the case
    verified = ok(priya("POST", f"{a}/verify", json={"note": "Signed approval matches PO-DEMO-1"}))
    assert (verified["status"], verified["verified_by"]) == ("VERIFIED", str(PRIYA))
    assert ok(priya("GET", f))["status"] == "VERIFIED"
    assert ok(priya("POST", f"{f}/close"))["status"] == "CLOSED"
    assert ok(sunita("GET", a))["status"] == "CLOSED"
    closed = ok(rahul("POST", f"{c}/close"))
    assert closed["status"] == "CLOSED" and closed["closed_at"] is not None

    # 8. Timelines are complete and in order
    case_log = ok(rahul("GET", f"{c}/timeline"))
    assert [t["action"] for t in case_log] == [
        "case.opened", "case.exception_added", "case.assigned"] + ["case.status_changed"] * 5
    assert [(t["details"]["to"], t["actor_id"]) for t in case_log[3:]] == [
        ("IN_INVESTIGATION", str(PRIYA)), ("PENDING_REVIEW", str(PRIYA)), ("FINDING_CONFIRMED", str(PRIYA)),
        ("ACTION_IN_PROGRESS", str(RAHUL)), ("CLOSED", str(RAHUL))]

    finding_log = ok(rahul("GET", f"{f}/timeline"))
    assert [(t["action"], t["actor_id"]) for t in finding_log] == [
        ("finding.created", str(PRIYA)), ("finding.submitted", str(PRIYA)), ("finding.confirmed", str(RAHUL)),
        ("finding.status_changed", str(RAHUL)), ("finding.status_changed", str(SUNITA)),
        ("finding.status_changed", str(PRIYA)), ("finding.closed", str(PRIYA))]
    assert [t["details"]["to"] for t in finding_log if t["action"] == "finding.status_changed"] == [
        "ACTION_ASSIGNED", "RESOLVED", "VERIFIED"]

    action_log = ok(sunita("GET", f"{a}/timeline"))
    assert [(t["action"], t["actor_id"]) for t in action_log] == [
        ("action.created", str(RAHUL)), ("action.started", str(SUNITA)), ("action.submitted", str(SUNITA)),
        ("action.verified", str(PRIYA)), ("action.closed", str(PRIYA))]
    for log in (case_log, finding_log, action_log):
        times = [t["created_at"] for t in log]
        assert times == sorted(times)

    # 9. Every evidence item still matches its fingerprint
    for item in (snapshot, finding_file, action_file):
        assert ok(rahul("POST", f"/audit/evidence/{item['id']}/verify")) == {"ok": True}
