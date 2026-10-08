"""Phase 3 exit check: exceptions become managed cases."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from agents.audit.demo.phase2_scenario import run_phase2_scenario
from agents.audit.main import app
from agents.audit.models import AuditException, AuditRule
from agents.audit.services.case_service import case_exceptions, list_cases
from agents.audit.services.pack_seeder import activate_pack, seed_procurement_pack
from shared.config import settings
from shared.db import get_db
from shared.notifications import list_for_user

client = TestClient(app)
AUTHOR, APPROVER, MANAGER, AUDITOR = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


@pytest.fixture(autouse=True)
def api_setup(monkeypatch, db_session):
    monkeypatch.setattr(settings, "environment", "development")
    app.dependency_overrides[get_db] = lambda: db_session
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def hospital(db_session):
    """A new hospital with the procurement pack ACTIVE and the Phase 2 scenario already run."""
    tenant = uuid.uuid4()
    seed_procurement_pack(db_session, tenant, created_by=AUTHOR)
    activate_pack(db_session, tenant, approved_by=APPROVER)
    run_phase2_scenario(db_session, tenant)
    return tenant


def rule_code_of(db, case):
    [exception] = case_exceptions(db, case)
    return db.get(AuditRule, exception.rule_id).rule_code


def test_every_exception_is_in_exactly_one_open_case(db_session, hospital):
    exceptions = db_session.scalars(select(AuditException).where(AuditException.tenant_id == hospital)).all()
    cases = list_cases(db_session, hospital)
    assert len(exceptions) == 7 and all(e.status == "IN_CASE" for e in exceptions)
    assert len(cases) == 7 and all(c.status == "OPEN" for c in cases)
    for case in cases:
        [exception] = case_exceptions(db_session, case)
        assert case.priority == exception.severity               # priority = rule severity

    [critical] = [c for c in cases if c.priority == "CRITICAL"]
    assert rule_code_of(db_session, critical) == "PRC-PAYINV-01"
    notes = list_for_user(db_session, hospital, MANAGER, ["AM"])
    assert [(n.kind, n.entity_id) for n in notes] == [("case.critical_opened", critical.id)]

    run_phase2_scenario(db_session, hospital)                    # re-run: every event is a duplicate
    assert len(list_cases(db_session, hospital)) == 7


def call(method, path, roles, user, tenant, json=None):
    headers = {"X-User-Id": str(user), "X-Tenant-Id": str(tenant), "X-Roles": roles}
    return client.request(method, f"/api/v1/audit{path}", json=json, headers=headers)


def test_full_case_lifecycle_through_the_api(db_session, hospital):
    [case] = [c for c in list_cases(db_session, hospital) if rule_code_of(db_session, c) == "PRC-APR-01"]
    db_session.commit()          # like earlier requests; a refused call's rollback must not undo it
    path = f"/cases/{case.id}"

    assert call("POST", f"{path}/assign", "AM", MANAGER, hospital, {"assignee_id": str(AUDITOR)}).status_code == 200
    for status in ("IN_INVESTIGATION", "PENDING_REVIEW", "FINDING_CONFIRMED", "ACTION_IN_PROGRESS"):
        r = call("POST", f"{path}/status", "AUD", AUDITOR, hospital, {"status": status})
        assert r.status_code == 200 and r.json()["status"] == status

    refused = call("POST", f"{path}/close", "AUD", AUDITOR, hospital)
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "MANAGER_APPROVAL"
    closed = call("POST", f"{path}/close", "AM", MANAGER, hospital)
    assert closed.status_code == 200
    assert closed.json()["status"] == "CLOSED" and closed.json()["closed_at"] is not None

    timeline = call("GET", f"{path}/timeline", "AM", MANAGER, hospital).json()
    assert [t["action"] for t in timeline] == [
        "case.opened", "case.exception_added", "case.assigned"] + ["case.status_changed"] * 5
    assert [t["details"]["to"] for t in timeline[3:]] == [
        "IN_INVESTIGATION", "PENDING_REVIEW", "FINDING_CONFIRMED", "ACTION_IN_PROGRESS", "CLOSED"]
    assert [t["actor_id"] for t in timeline[3:]] == [str(AUDITOR)] * 4 + [str(MANAGER)]

    notes = client.get("/api/v1/notifications", headers={
        "X-User-Id": str(AUDITOR), "X-Tenant-Id": str(hospital), "X-Roles": "AUD"}).json()
    assert [(n["kind"], n["entity_id"]) for n in notes] == [("case.assigned", str(case.id))]
