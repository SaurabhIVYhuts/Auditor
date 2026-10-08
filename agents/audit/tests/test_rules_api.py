"""Tests for the rule API (M2), including maker-checker."""
import uuid

import pytest
from fastapi.testclient import TestClient

from agents.audit.main import app
from agents.audit.tests.test_rule_engine import PRC_APR_01
from shared.audit_log import list_for_entity
from shared.config import settings
from shared.db import get_db

client = TestClient(app)
HOSPITAL, AUTHOR, APPROVER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
NEW_RULE = {"rule_code": "PRC-APR-01", "name": "High-value PO without approval",
            "domain": "PROCUREMENT", "severity": "HIGH", "definition": PRC_APR_01}


@pytest.fixture(autouse=True)
def api_setup(monkeypatch, db_session):
    monkeypatch.setattr(settings, "environment", "development")
    app.dependency_overrides[get_db] = lambda: db_session
    yield
    app.dependency_overrides.pop(get_db, None)


def as_user(roles, user=AUTHOR, tenant=HOSPITAL):
    return {"X-User-Id": str(user), "X-Tenant-Id": str(tenant), "X-Roles": roles}


def create(user=AUTHOR, **changes):
    r = client.post("/api/v1/audit/rules", json={**NEW_RULE, **changes}, headers=as_user("AM", user))
    assert r.status_code == 201, r.text
    return r.json()


def test_create_rule_starts_as_draft():
    rule = create()
    assert (rule["status"], rule["current_version"]) == ("DRAFT", 1)


def test_auditor_can_read_but_not_write():
    assert client.get("/api/v1/audit/rules", headers=as_user("AUD")).status_code == 200
    assert client.post("/api/v1/audit/rules", json=NEW_RULE, headers=as_user("AUD")).status_code == 403


def test_invalid_rule_is_refused_with_reasons():
    bad = {**NEW_RULE, "definition": {**PRC_APR_01, "condition": {"field": "po.secret", "op": ">", "value": 1}}}
    r = client.post("/api/v1/audit/rules", json=bad, headers=as_user("AM"))
    assert r.status_code == 422 and "unknown field" in str(r.json()["detail"]["errors"])


def test_duplicate_rule_code_is_409():
    create()
    assert client.post("/api/v1/audit/rules", json=NEW_RULE, headers=as_user("AM")).status_code == 409


def test_author_cannot_activate_own_high_rule():
    rule = create(user=AUTHOR)
    r = client.post(f"/api/v1/audit/rules/{rule['id']}/activate", headers=as_user("AM", AUTHOR))
    assert r.status_code == 403 and r.json()["detail"] == "MAKER_CHECKER"


def test_second_person_activates_then_rule_can_run():
    rule = create(user=AUTHOR)
    r = client.post(f"/api/v1/audit/rules/{rule['id']}/activate", headers=as_user("AM", APPROVER))
    assert r.status_code == 200 and r.json()["status"] == "ACTIVE"
    run = client.post(f"/api/v1/audit/rules/{rule['id']}/run", headers=as_user("AM", APPROVER))
    assert run.status_code == 200 and run.json()["trigger_type"] == "MANUAL"
    runs = client.get(f"/api/v1/audit/rules/{rule['id']}/runs", headers=as_user("AUD"))
    assert len(runs.json()) == 1


def test_edit_creates_new_version_and_needs_reactivation():
    rule = create(user=AUTHOR)
    client.post(f"/api/v1/audit/rules/{rule['id']}/activate", headers=as_user("AM", APPROVER))
    r = client.put(f"/api/v1/audit/rules/{rule['id']}", headers=as_user("AM", AUTHOR),
                   json={"definition": PRC_APR_01, "change_note": "re-check"})
    assert r.status_code == 200
    assert (r.json()["current_version"], r.json()["status"]) == (2, "DRAFT")


def test_run_on_draft_rule_is_409():
    rule = create()
    assert client.post(f"/api/v1/audit/rules/{rule['id']}/run", headers=as_user("AM")).status_code == 409


def test_other_hospital_cannot_see_the_rule():
    rule = create()
    r = client.get(f"/api/v1/audit/rules/{rule['id']}", headers=as_user("AM", tenant=uuid.uuid4()))
    assert r.status_code == 404


def test_rule_functions_lists_the_whitelist():
    r = client.get("/api/v1/audit/rule-functions", headers=as_user("AUD"))
    assert r.status_code == 200 and "duplicate_of" in r.json()["functions"]


def test_compliance_officer_cannot_activate():
    rule = create()
    r = client.post(f"/api/v1/audit/rules/{rule['id']}/activate", headers=as_user("CO", APPROVER))
    assert r.status_code == 403


def rule_log(db, rule):
    return list_for_entity(db, HOSPITAL, "audit_rule", uuid.UUID(rule["id"]))


def test_create_activate_run_are_written_to_the_audit_log(db_session):
    rule = create(user=AUTHOR)
    client.post(f"/api/v1/audit/rules/{rule['id']}/activate", headers=as_user("AM", APPROVER))
    client.post(f"/api/v1/audit/rules/{rule['id']}/run", headers=as_user("AM", APPROVER))

    log = rule_log(db_session, rule)
    assert [row.action for row in log] == ["rule.created", "rule.activated", "rule.run"]
    assert [row.actor_id for row in log] == [AUTHOR, APPROVER, APPROVER]
    assert log[1].details["approved_by"] == str(APPROVER)
    assert log[2].details["status"] == "SUCCEEDED"


def test_refused_activation_writes_no_log(db_session):
    rule = create(user=AUTHOR)
    r = client.post(f"/api/v1/audit/rules/{rule['id']}/activate", headers=as_user("AM", AUTHOR))
    assert r.status_code == 403
    assert [row.action for row in rule_log(db_session, rule)] == ["rule.created"]
