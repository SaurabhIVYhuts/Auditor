"""Tests for the finding API (M11): the full path, review rules, and who sees which finding."""
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from agents.audit.main import app
from agents.audit.services.case_service import _hospital_today, change_status
from agents.audit.services.evidence_service import link_evidence, upload_evidence
from agents.audit.tests.test_cases_api import AUDITOR_A, AUDITOR_B, BOARD, HOSPITAL, MANAGER, as_user, case
from agents.audit.tests.test_documents import PDF, temp_storage  # noqa: F401  (fixture: files go to tmp)
from shared.config import settings
from shared.db import get_db

client = TestClient(app)
OTHER_MANAGER, OWNER, SOMEONE_ELSE = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
COMPLETE = {"condition": "PO approved at level 1 only", "criteria": "Level-2 approval above the limit",
            "recommendation": "Obtain retrospective approval", "risk_level": "HIGH"}


@pytest.fixture(autouse=True)
def api_setup(monkeypatch, db_session):
    monkeypatch.setattr(settings, "environment", "development")
    app.dependency_overrides[get_db] = lambda: db_session
    yield
    app.dependency_overrides.pop(get_db, None)


def call(method, path, roles, user, **kw):
    return client.request(method, f"/api/v1/audit{path}", headers=as_user(roles, user), **kw)


def new_finding(db, roles="AUD", user=AUDITOR_A, priority="HIGH", **fields):
    c = case(db, priority, AUDITOR_A)
    db.commit()
    r = call("POST", f"/cases/{c.id}/findings", roles, user, json={"title": "PO without level-2 approval",
                                                                    **COMPLETE, **fields})
    assert r.status_code == 201, r.text
    return c, r.json()


def add_evidence(finding_id, roles="AUD", user=AUDITOR_A):
    r = call("POST", f"/findings/{finding_id}/evidence", roles, user, data={"title": "Approval email"},
             files={"file": ("approval.pdf", PDF, "application/pdf")})
    assert r.status_code == 201, r.text
    return r.json()


def submit(finding_id, roles="AUD", user=AUDITOR_A):
    return call("POST", f"/findings/{finding_id}/submit", roles, user)


def confirm(finding_id, roles="AM", user=OTHER_MANAGER, owner=OWNER):
    due = str(_hospital_today() + timedelta(days=14))
    return call("POST", f"/findings/{finding_id}/confirm", roles, user, json={"owner_user_id": str(owner), "due_date": due})


def confirmed_finding(db, owner=OWNER, **fields):
    c, f = new_finding(db, **fields)
    add_evidence(f["id"])
    assert submit(f["id"]).status_code == 200
    r = confirm(f["id"], owner=owner)
    assert r.status_code == 200, r.text
    return c, r.json()


def test_full_api_path(db_session):
    c, f = new_finding(db_session)
    assert (f["status"], f["allowed_next"]) == ("DRAFT", ["UNDER_REVIEW"])
    evidence = add_evidence(f["id"])
    case_evidence = call("GET", f"/cases/{c.id}/evidence", "AUD", AUDITOR_A).json()
    assert evidence["id"] in [e["id"] for e in case_evidence]            # linked to the case too

    submitted = submit(f["id"]).json()
    assert submitted["status"] == "UNDER_REVIEW"
    confirmed = confirm(f["id"]).json()
    assert (confirmed["status"], confirmed["owner_user_id"]) == ("CONFIRMED", str(OWNER))

    detail = call("GET", f"/findings/{f['id']}", "AM", MANAGER).json()
    assert [e["id"] for e in detail["evidence"]] == [evidence["id"]]
    actions = [t["action"] for t in call("GET", f"/findings/{f['id']}/timeline", "AM", MANAGER).json()]
    assert actions == ["finding.created", "finding.submitted", "finding.confirmed"]


def test_submit_without_evidence_or_fields_is_422(db_session):
    _, f = new_finding(db_session)
    r = submit(f["id"])
    assert r.status_code == 422 and "evidence" in r.json()["detail"]["message"]
    _, half = new_finding(db_session, risk_level=None, recommendation=None)
    add_evidence(half["id"])
    r = submit(half["id"])
    assert r.status_code == 422 and r.json()["detail"]["missing"] == ["recommendation", "risk_level"]


def test_author_manager_confirming_own_finding_is_maker_checker(db_session):
    _, f = new_finding(db_session, roles="AM", user=MANAGER)
    add_evidence(f["id"], "AM", MANAGER)
    submit(f["id"], "AM", MANAGER)
    r = confirm(f["id"], user=MANAGER)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "MAKER_CHECKER"


def test_auditor_cannot_confirm(db_session):
    _, f = new_finding(db_session)
    add_evidence(f["id"])
    submit(f["id"])
    r = confirm(f["id"], roles="AUD", user=AUDITOR_A)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "MANAGER_APPROVAL"


def test_invalid_move_is_409_with_allowed_next(db_session):
    _, f = new_finding(db_session)
    r = confirm(f["id"])
    assert r.status_code == 409 and r.json()["detail"]["allowed_next"] == ["UNDER_REVIEW"]


def test_management_sees_confirmed_findings_but_not_drafts(db_session):
    _, draft = new_finding(db_session)
    _, done = confirmed_finding(db_session)
    assert call("GET", f"/findings/{draft['id']}", "MGT", BOARD).status_code == 404
    assert call("GET", f"/findings/{done['id']}", "MGT", BOARD).status_code == 200
    listed = [f["id"] for f in call("GET", "/findings", "MGT", BOARD).json()]
    assert done["id"] in listed and draft["id"] not in listed


def test_auditee_sees_only_own_confirmed_findings(db_session):
    _, draft = new_finding(db_session, owner_user_id=str(OWNER))
    _, mine = confirmed_finding(db_session, owner=OWNER)
    _, theirs = confirmed_finding(db_session, owner=SOMEONE_ELSE)
    assert call("GET", f"/findings/{mine['id']}", "OWN", OWNER).status_code == 200
    assert call("GET", f"/findings/{draft['id']}", "OWN", OWNER).status_code == 404
    assert call("GET", f"/findings/{theirs['id']}", "OWN", OWNER).status_code == 404
    assert [f["id"] for f in call("GET", "/findings", "OWN", OWNER).json()] == [mine["id"]]
    assert call("GET", f"/findings/{mine['id']}", "OWN", OWNER).json()["evidence"] == []   # no evidence:read


def test_evidence_linked_only_to_a_finding_is_visible_through_the_finding(db_session):
    _, f = new_finding(db_session)
    item = upload_evidence(db_session, HOSPITAL, title="Finding-only note", filename="note.txt",
                           content_type="text/plain", data=b"note", actor_id=AUDITOR_A)
    link_evidence(db_session, item, "FINDING", uuid.UUID(f["id"]), AUDITOR_A)
    db_session.commit()
    assert call("GET", f"/evidence/{item.id}", "AUD", AUDITOR_A).status_code == 200
    assert call("GET", f"/evidence/{item.id}", "AUD", AUDITOR_B).status_code == 404


def test_case_close_with_an_open_finding_is_409(db_session):
    c, _ = new_finding(db_session, priority="MEDIUM")
    for status in ("IN_INVESTIGATION", "PENDING_REVIEW", "FINDING_CONFIRMED", "ACTION_IN_PROGRESS"):
        change_status(db_session, c, status, MANAGER, ["AM"])
    db_session.commit()
    r = call("POST", f"/cases/{c.id}/close", "AM", MANAGER)
    assert r.status_code == 409 and r.json()["detail"]["message"] == "1 finding still open"
