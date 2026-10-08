"""Tests for the case API (M1): who sees which case, detail, timeline, manual cases."""
import uuid

import pytest
from fastapi.testclient import TestClient

from agents.audit.main import app
from agents.audit.services.case_grouping_service import case_for_new_exception
from agents.audit.services.case_service import add_comment, assign_case, change_status, open_case
from agents.audit.tests.test_case_grouping import old_exception, rule_for
from shared.config import settings
from shared.db import get_db

client = TestClient(app)
HOSPITAL = uuid.uuid4()
MANAGER, AUDITOR_A, AUDITOR_B, BOARD = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


@pytest.fixture(autouse=True)
def api_setup(monkeypatch, db_session):
    monkeypatch.setattr(settings, "environment", "development")
    app.dependency_overrides[get_db] = lambda: db_session
    yield
    app.dependency_overrides.pop(get_db, None)


def as_user(roles, user, tenant=HOSPITAL):
    return {"X-User-Id": str(user), "X-Tenant-Id": str(tenant), "X-Roles": roles}


def case(db, priority, assigned_to=None, restricted=False, title=None):
    c = open_case(db, HOSPITAL, domain="PROCUREMENT", title=title or f"{priority} case", source="MANUAL",
                  primary_entity_type="purchase_order", primary_entity_id=uuid.uuid4(),
                  priority=priority, actor_id=MANAGER)
    if assigned_to:
        assign_case(db, c, assigned_to, MANAGER)
    c.is_restricted = restricted
    db.flush()
    return c


@pytest.fixture
def cases(db_session):
    return {
        "high_a": case(db_session, "HIGH", AUDITOR_A),
        "low_b": case(db_session, "LOW", AUDITOR_B),
        "critical": case(db_session, "CRITICAL"),
        "restricted_a": case(db_session, "CRITICAL", AUDITOR_A, restricted=True),
    }


def numbers(response):
    assert response.status_code == 200, response.text
    return {c["case_number"] for c in response.json()}


def test_audit_manager_sees_all_cases_including_restricted(cases):
    seen = numbers(client.get("/api/v1/audit/cases", headers=as_user("AM", MANAGER)))
    assert seen == {c.case_number for c in cases.values()}


def test_auditor_sees_only_own_unrestricted_cases(cases):
    seen = numbers(client.get("/api/v1/audit/cases", headers=as_user("AUD", AUDITOR_A)))
    assert seen == {cases["high_a"].case_number}                    # restricted_a is hidden


def test_management_sees_only_high_and_critical(cases):
    seen = numbers(client.get("/api/v1/audit/cases", headers=as_user("MGT", BOARD)))
    assert seen == {cases["high_a"].case_number, cases["critical"].case_number}


def test_hidden_case_detail_is_404(cases):
    hidden = cases["restricted_a"].id
    assert client.get(f"/api/v1/audit/cases/{hidden}", headers=as_user("AUD", AUDITOR_A)).status_code == 404
    assert client.get(f"/api/v1/audit/cases/{hidden}", headers=as_user("AM", MANAGER)).status_code == 200


def test_other_hospital_gets_404(cases):
    r = client.get(f"/api/v1/audit/cases/{cases['high_a'].id}", headers=as_user("AM", MANAGER, uuid.uuid4()))
    assert r.status_code == 404


def test_list_filters(cases):
    r = client.get("/api/v1/audit/cases", params={"priority": "LOW"}, headers=as_user("AM", MANAGER))
    assert numbers(r) == {cases["low_b"].case_number}
    r = client.get("/api/v1/audit/cases", params={"status": "OPEN"}, headers=as_user("AM", MANAGER))
    assert numbers(r) == {cases["critical"].case_number}


MANUAL = {"domain": "OTHER", "title": "Concern raised by finance", "priority": "MEDIUM",
          "primary_entity_type": "vendor", "primary_entity_id": str(uuid.uuid4())}


def test_audit_manager_creates_manual_case_with_domain_other():
    r = client.post("/api/v1/audit/cases", json=MANUAL, headers=as_user("AM", MANAGER))
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["source"], body["domain"], body["status"]) == ("MANUAL", "OTHER", "OPEN")
    assert body["allowed_next"] == ["ASSIGNED"]


def test_auditor_cannot_create_a_case():
    assert client.post("/api/v1/audit/cases", json=MANUAL, headers=as_user("AUD", AUDITOR_A)).status_code == 403


def test_unknown_domain_is_422():
    r = client.post("/api/v1/audit/cases", json={**MANUAL, "domain": "SPACE"}, headers=as_user("AM", MANAGER))
    assert r.status_code == 422


def test_detail_lists_exceptions_with_rule_code(db_session):
    rule = rule_for(db_session, HOSPITAL, code="PRC-APR-01")
    exception = old_exception(db_session, rule, uuid.uuid4())
    grouped, _ = case_for_new_exception(db_session, exception, rule)
    r = client.get(f"/api/v1/audit/cases/{grouped.id}", headers=as_user("AM", MANAGER))
    assert r.status_code == 200
    [listed] = r.json()["exceptions"]
    assert (listed["id"], listed["rule_code"], listed["severity"]) == (str(exception.id), "PRC-APR-01", "HIGH")


def test_timeline_and_comments_in_order(db_session):
    c = case(db_session, "HIGH", AUDITOR_A)
    add_comment(db_session, c, AUDITOR_A, "Requested approval records")
    timeline = client.get(f"/api/v1/audit/cases/{c.id}/timeline", headers=as_user("AUD", AUDITOR_A)).json()
    assert [t["action"] for t in timeline] == ["case.opened", "case.assigned", "case.commented"]
    comments = client.get(f"/api/v1/audit/cases/{c.id}/comments", headers=as_user("AUD", AUDITOR_A)).json()
    assert [x["body"] for x in comments] == ["Requested approval records"]


# --- Case actions ---

def act(case_id, action, roles, user, json=None):
    return client.post(f"/api/v1/audit/cases/{case_id}/{action}", json=json, headers=as_user(roles, user))


def walk(db, c, *statuses):
    for status in statuses:
        change_status(db, c, status, MANAGER, ["AM"], reason="checked")


def test_audit_manager_assigns_case():
    c = client.post("/api/v1/audit/cases", json=MANUAL, headers=as_user("AM", MANAGER)).json()
    r = act(c["id"], "assign", "AM", MANAGER, {"assignee_id": str(AUDITOR_A)})
    assert r.status_code == 200 and (r.json()["status"], r.json()["assigned_to"]) == ("ASSIGNED", str(AUDITOR_A))


def test_auditor_cannot_assign(db_session):
    c = case(db_session, "HIGH", AUDITOR_A)
    assert act(c.id, "assign", "AUD", AUDITOR_A, {"assignee_id": str(AUDITOR_B)}).status_code == 403


def test_assigned_auditor_starts_investigation(db_session):
    c = case(db_session, "HIGH", AUDITOR_A)
    r = act(c.id, "status", "AUD", AUDITOR_A, {"status": "IN_INVESTIGATION"})
    assert r.status_code == 200 and r.json()["status"] == "IN_INVESTIGATION"


def test_invalid_move_is_409_with_allowed_next(db_session):
    c = case(db_session, "HIGH")
    r = act(c.id, "status", "AM", MANAGER, {"status": "CLOSED"})
    assert r.status_code == 409
    assert r.json()["detail"] == {"message": "cannot move from OPEN to CLOSED", "allowed_next": ["ASSIGNED"]}


def test_no_issue_without_reason_is_422(db_session):
    c = case(db_session, "LOW", AUDITOR_A)
    walk(db_session, c, "IN_INVESTIGATION", "PENDING_REVIEW")
    assert act(c.id, "status", "AUD", AUDITOR_A, {"status": "NO_ISSUE"}).status_code == 422


def test_closing_high_case_needs_audit_manager_then_reopen(db_session):
    c = case(db_session, "HIGH", AUDITOR_A)
    walk(db_session, c, "IN_INVESTIGATION", "PENDING_REVIEW", "FINDING_CONFIRMED", "ACTION_IN_PROGRESS")
    # Save the setup like an earlier request would; the refused call's rollback must not undo it.
    # (Only a savepoint is released: the test transaction is still rolled back at the end.)
    db_session.commit()
    refused = act(c.id, "close", "AUD", AUDITOR_A)
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "MANAGER_APPROVAL"
    closed = act(c.id, "close", "AM", MANAGER, {"reason": "debit note recovered"})
    assert closed.status_code == 200 and closed.json()["status"] == "CLOSED"
    reopened = act(c.id, "reopen", "AM", MANAGER)
    assert reopened.status_code == 200 and reopened.json()["status"] == "REOPENED"


def test_comment_saved_but_management_cannot_comment(db_session):
    c = case(db_session, "HIGH", AUDITOR_A)
    r = act(c.id, "comments", "AUD", AUDITOR_A, {"body": "Vendor contacted"})
    assert r.status_code == 201 and r.json()["body"] == "Vendor contacted"
    assert act(c.id, "comments", "MGT", BOARD, {"body": "hello"}).status_code == 403


def test_auditor_acting_on_someone_elses_case_gets_404(db_session):
    c = case(db_session, "HIGH", AUDITOR_A)
    assert act(c.id, "status", "AUD", AUDITOR_B, {"status": "IN_INVESTIGATION"}).status_code == 404


def test_update_logs_only_changed_fields(db_session):
    c = case(db_session, "HIGH", title="Original title")
    r = client.put(f"/api/v1/audit/cases/{c.id}", headers=as_user("AM", MANAGER),
                   json={"title": "Original title", "priority": "CRITICAL"})
    assert r.status_code == 200 and r.json()["priority"] == "CRITICAL"
    timeline = client.get(f"/api/v1/audit/cases/{c.id}/timeline", headers=as_user("AM", MANAGER)).json()
    assert timeline[-1]["action"] == "case.updated"
    assert timeline[-1]["details"] == {"priority": {"from": "HIGH", "to": "CRITICAL"}}
