"""Tests for the corrective action API (M12): who sees which action, owner steps, verify, close."""
import uuid
from datetime import timedelta

from agents.audit.models import CorrectiveAction
from agents.audit.services.case_service import _hospital_today
from agents.audit.tests.test_cases_api import AUDITOR_A, MANAGER
from agents.audit.tests.test_documents import PDF, temp_storage  # noqa: F401  (fixture: files go to tmp)
from agents.audit.tests.test_findings_api import OWNER, SOMEONE_ELSE, api_setup, call, confirmed_finding  # noqa: F401


def create(finding_id, owner=OWNER, roles="AM", user=MANAGER, **fields):
    body = {"description": "Obtain retrospective level-2 approval", "owner_user_id": str(owner),
            "due_date": str(_hospital_today() + timedelta(days=10)), **fields}
    return call("POST", f"/findings/{finding_id}/actions", roles, user, json=body)


def upload(action_id, roles="OWN", user=OWNER):
    return call("POST", f"/actions/{action_id}/evidence", roles, user, data={"title": "Signed approval"},
                files={"file": ("approval.pdf", PDF, "application/pdf")})


def test_create_needs_description_owner_and_due_date(db_session):
    _, f = confirmed_finding(db_session)
    r = call("POST", f"/findings/{f['id']}/actions", "AM", MANAGER, json={})
    assert r.status_code == 422 and set(r.json()["detail"]["missing"]) == {"description", "owner_user_id", "due_date"}
    assert create(f["id"], roles="OWN", user=OWNER).status_code == 403
    past = create(f["id"], due_date=str(_hospital_today() - timedelta(days=1)))
    assert past.status_code == 422


def test_auditee_sees_and_works_only_own_actions(db_session):
    _, f = confirmed_finding(db_session)
    mine = create(f["id"]).json()
    theirs = create(f["id"], owner=SOMEONE_ELSE).json()
    assert mine["action_number"].startswith("ACT-") and mine["allowed_next"] == ["IN_PROGRESS"]

    listed = call("GET", "/actions", "OWN", OWNER).json()
    assert [a["id"] for a in listed] == [mine["id"]]
    assert call("GET", f"/actions/{theirs['id']}", "OWN", OWNER).status_code == 404
    assert len(call("GET", f"/actions?finding_id={f['id']}", "AUD", AUDITOR_A).json()) == 2
    assert [a["id"] for a in call("GET", "/actions?mine=true", "AUD", AUDITOR_A).json()] == []

    assert upload(theirs["id"]).status_code == 404                     # someone else's action
    assert upload(mine["id"]).status_code == 201
    assert call("POST", f"/actions/{theirs['id']}/start", "OWN", OWNER).status_code == 404
    started = call("POST", f"/actions/{mine['id']}/start", "OWN", OWNER)
    assert started.status_code == 200 and started.json()["status"] == "IN_PROGRESS"
    detail = call("GET", f"/actions/{mine['id']}", "OWN", OWNER).json()
    assert [e["title"] for e in detail["evidence"]] == ["Signed approval"]     # owner sees own evidence


def test_submit_without_evidence_and_wrong_verifier_are_refused(db_session):
    _, f = confirmed_finding(db_session)
    a = create(f["id"]).json()
    call("POST", f"/actions/{a['id']}/start", "OWN", OWNER)
    r = call("POST", f"/actions/{a['id']}/submit", "OWN", OWNER)
    assert r.status_code == 422
    upload(a["id"])
    assert call("POST", f"/actions/{a['id']}/submit", "OWN", OWNER).status_code == 200
    assert call("POST", f"/actions/{a['id']}/verify", "OWN", OWNER, json={}).status_code == 403


def test_auditor_who_owns_the_action_cannot_verify_it(db_session):
    _, f = confirmed_finding(db_session)
    a = create(f["id"], owner=AUDITOR_A).json()
    call("POST", f"/actions/{a['id']}/start", "AUD,OWN", AUDITOR_A)
    upload(a["id"], roles="AUD,OWN", user=AUDITOR_A)
    call("POST", f"/actions/{a['id']}/submit", "AUD,OWN", AUDITOR_A)
    r = call("POST", f"/actions/{a['id']}/verify", "AUD,OWN", AUDITOR_A, json={})
    assert (r.status_code, r.json()["detail"]["code"]) == (403, "MAKER_CHECKER")


def test_return_sends_the_action_back(db_session):
    _, f = confirmed_finding(db_session)
    a = create(f["id"]).json()
    call("POST", f"/actions/{a['id']}/start", "OWN", OWNER)
    upload(a["id"])
    call("POST", f"/actions/{a['id']}/submit", "OWN", OWNER)
    r = call("POST", f"/actions/{a['id']}/return", "AUD", AUDITOR_A, json={"note": "Approver missing"})
    assert (r.status_code, r.json()["status"], r.json()["return_note"]) == (200, "RETURNED", "Approver missing")
    assert call("GET", f"/findings/{f['id']}", "AUD", AUDITOR_A).json()["status"] == "REOPENED"


def test_full_loop_to_finding_closed(db_session):
    c, f = confirmed_finding(db_session)
    a = create(f["id"]).json()
    assert call("POST", f"/findings/{f['id']}/close", "AUD", AUDITOR_A).status_code == 409   # not verified yet
    assert call("POST", f"/actions/{a['id']}/start", "OWN", OWNER).status_code == 200
    evidence = upload(a["id"]).json()
    assert call("POST", f"/actions/{a['id']}/submit", "OWN", OWNER).json()["status"] == "SUBMITTED"
    case_evidence = call("GET", f"/cases/{c.id}/evidence", "AUD", AUDITOR_A).json()
    assert evidence["id"] in [e["id"] for e in case_evidence]                 # linked to the case too

    verified = call("POST", f"/actions/{a['id']}/verify", "AUD", AUDITOR_A, json={"note": "Checked"})
    assert (verified.status_code, verified.json()["status"]) == (200, "VERIFIED"), verified.text
    assert call("GET", f"/findings/{f['id']}", "AUD", AUDITOR_A).json()["status"] == "VERIFIED"
    assert call("POST", f"/findings/{f['id']}/close", "OWN", OWNER).status_code == 403
    closed = call("POST", f"/findings/{f['id']}/close", "AUD", AUDITOR_A)
    assert (closed.status_code, closed.json()["status"]) == (200, "CLOSED"), closed.text
    assert call("GET", f"/actions/{a['id']}", "OWN", OWNER).json()["status"] == "CLOSED"


def test_overdue_filter(db_session):
    _, f = confirmed_finding(db_session)
    a = create(f["id"]).json()
    assert call("GET", "/actions?overdue_only=true", "AUD", AUDITOR_A).json() == []
    db_session.get(CorrectiveAction, uuid.UUID(a["id"])).due_date = _hospital_today() - timedelta(days=2)
    db_session.commit()
    assert [x["id"] for x in call("GET", "/actions?overdue_only=true", "AUD", AUDITOR_A).json()] == [a["id"]]
