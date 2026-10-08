"""Tests for in-app notifications (AUD-023): who is told what, and who can read it."""
import uuid

import pytest
from fastapi.testclient import TestClient

from agents.audit.events.procurement_event_consumer import handle_procurement_event
from agents.audit.main import app
from agents.audit.services.case_service import assign_case, open_case
from agents.audit.services.rule_registry import create_rule
from agents.audit.tests.test_rule_engine import PRC_APR_01, PoReader, hospital, make_event
from shared.config import settings
from shared.db import get_db
from shared.notifications import list_for_user, mark_read, notify_role, notify_user

client = TestClient(app)
MANAGER, AUDITOR, OTHER_AUDITOR = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


@pytest.fixture(autouse=True)
def api_setup(monkeypatch, db_session):
    monkeypatch.setattr(settings, "environment", "development")
    app.dependency_overrides[get_db] = lambda: db_session
    yield
    app.dependency_overrides.pop(get_db, None)


def new_case(db, tenant, priority="HIGH"):
    return open_case(db, tenant, domain="PROCUREMENT", title="Invoice amount above PO total", source="MANUAL",
                     primary_entity_type="invoice", primary_entity_id=uuid.uuid4(), priority=priority,
                     actor_id=MANAGER)


def kinds(db, tenant, user, roles):
    return [n.kind for n in list_for_user(db, tenant, user, roles)]


def test_assign_notifies_the_assignee_only(db_session):
    tenant = uuid.uuid4()
    case = new_case(db_session, tenant)
    assign_case(db_session, case, AUDITOR, MANAGER)
    [note] = list_for_user(db_session, tenant, AUDITOR, ["AUD"])
    assert (note.kind, note.title) == ("case.assigned", f"Case {case.case_number} assigned to you")
    assert (note.entity_type, note.entity_id) == ("audit_case", case.id)
    assert kinds(db_session, tenant, OTHER_AUDITOR, ["AUD"]) == []


def test_reassigning_to_the_same_person_sends_nothing_new(db_session):
    tenant = uuid.uuid4()
    case = new_case(db_session, tenant)
    assign_case(db_session, case, AUDITOR, MANAGER)
    assign_case(db_session, case, AUDITOR, MANAGER)
    assert kinds(db_session, tenant, AUDITOR, ["AUD"]) == ["case.assigned"]


def test_critical_case_notifies_audit_managers_high_does_not(db_session):
    tenant = uuid.uuid4()
    new_case(db_session, tenant, "HIGH")
    assert kinds(db_session, tenant, MANAGER, ["AM"]) == []
    critical = new_case(db_session, tenant, "CRITICAL")
    [note] = list_for_user(db_session, tenant, MANAGER, ["AM"])
    assert (note.kind, note.recipient_role, note.entity_id) == ("case.critical_opened", "AM", critical.id)
    assert kinds(db_session, tenant, AUDITOR, ["AUD"]) == []


def test_list_shows_own_and_role_newest_first_and_never_other_hospitals(db_session):
    tenant = uuid.uuid4()
    notify_role(db_session, tenant, "AM", "test.role", "For managers", "")
    notify_user(db_session, tenant, MANAGER, "test.own", "For me", "")
    notify_user(db_session, uuid.uuid4(), MANAGER, "test.elsewhere", "Other hospital", "")
    assert kinds(db_session, tenant, MANAGER, ["AM"]) == ["test.own", "test.role"]


def test_mark_read_own_only(db_session):
    tenant = uuid.uuid4()
    note = notify_user(db_session, tenant, AUDITOR, "test.own", "For the auditor", "")
    assert mark_read(db_session, tenant, note.id, OTHER_AUDITOR, ["AUD"]) is None
    assert mark_read(db_session, tenant, note.id, AUDITOR, ["AUD"]).read_at is not None
    assert list_for_user(db_session, tenant, AUDITOR, ["AUD"], unread_only=True) == []


def headers(user, tenant, roles):
    return {"X-User-Id": str(user), "X-Tenant-Id": str(tenant), "X-Roles": roles}


def test_api_list_and_mark_read(db_session):
    tenant = uuid.uuid4()
    note = notify_user(db_session, tenant, AUDITOR, "test.own", "For the auditor", "Body")
    listed = client.get("/api/v1/notifications", params={"unread_only": True},
                        headers=headers(AUDITOR, tenant, "AUD")).json()
    assert [n["id"] for n in listed] == [str(note.id)]

    assert client.post(f"/api/v1/notifications/{note.id}/read",
                       headers=headers(OTHER_AUDITOR, tenant, "AUD")).status_code == 404
    assert client.post(f"/api/v1/notifications/{note.id}/read",
                       headers=headers(AUDITOR, uuid.uuid4(), "AUD")).status_code == 404
    r = client.post(f"/api/v1/notifications/{note.id}/read", headers=headers(AUDITOR, tenant, "AUD"))
    assert r.status_code == 200 and r.json()["read_at"] is not None


def test_event_to_critical_case_notifies_audit_managers(db_session):
    tenant = hospital(db_session)
    rule = create_rule(db_session, tenant_id=tenant, rule_code="PRC-APR-01", name="High-value PO without approval",
                       domain="PROCUREMENT", severity="CRITICAL", definition=PRC_APR_01)
    rule.status = "ACTIVE"
    db_session.flush()
    handle_procurement_event(db_session, make_event(tenant), PoReader())
    [note] = list_for_user(db_session, tenant, MANAGER, ["AM"])
    assert note.kind == "case.critical_opened" and "fraud" not in (note.title + note.body).lower()
