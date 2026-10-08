"""Tests for the case service (AUD-020): open, assign, status changes, approvals, audit log."""
import uuid
from datetime import datetime, timezone

import pytest

from agents.audit.cases.state_machine import InvalidTransition
from agents.audit.services import case_service
from agents.audit.services.case_service import (
    CaseClosed, ManagerApprovalRequired, ReasonRequired, add_comment, assign_case, case_exceptions,
    case_timeline, change_status, get_case, list_cases, open_case,
)
from agents.audit.tests.test_case_models import make_exception
from shared.audit_log import list_for_entity

ACTOR, AUDITOR = uuid.uuid4(), uuid.uuid4()


def new_case(db, tenant=None, priority="HIGH", exceptions=(), domain="PROCUREMENT"):
    return open_case(db, tenant or uuid.uuid4(), domain=domain, title="High-value PO without approval",
                     source="RULE", primary_entity_type="purchase_order", primary_entity_id=uuid.uuid4(),
                     priority=priority, actor_id=ACTOR, exception_ids=[e.id for e in exceptions])


def walk(db, case, *statuses, roles=("AUD",), reason=None):
    for status in statuses:
        change_status(db, case, status, ACTOR, roles, reason=reason)


def test_open_case_numbers_it_and_links_exceptions(db_session):
    tenant = uuid.uuid4()
    excs = [make_exception(db_session, tenant), make_exception(db_session, tenant)]
    case = new_case(db_session, tenant, exceptions=excs)
    assert case.case_number == f"AUD-{case_service._hospital_year()}-00001"
    assert case.status == "OPEN"
    assert all(e.status == "IN_CASE" for e in excs)


def test_exception_already_in_a_case_cannot_be_added_again(db_session):
    tenant = uuid.uuid4()
    exc = make_exception(db_session, tenant)
    new_case(db_session, tenant, exceptions=[exc])
    with pytest.raises(ValueError):
        new_case(db_session, tenant, exceptions=[exc])


def test_assign_moves_open_to_assigned_and_reassign_keeps_status(db_session):
    case = new_case(db_session)
    assign_case(db_session, case, AUDITOR, ACTOR)
    assert (case.status, case.assigned_to) == ("ASSIGNED", AUDITOR)
    other = uuid.uuid4()
    assign_case(db_session, case, other, ACTOR)
    assert (case.status, case.assigned_to) == ("ASSIGNED", other)


def test_invalid_move_is_refused(db_session):
    case = new_case(db_session)
    with pytest.raises(InvalidTransition, match="cannot move from OPEN to CLOSED"):
        change_status(db_session, case, "CLOSED", ACTOR, ["AM"])


def test_no_issue_needs_a_reason(db_session):
    case = new_case(db_session, priority="MEDIUM")
    assign_case(db_session, case, AUDITOR, ACTOR)
    walk(db_session, case, "IN_INVESTIGATION", "PENDING_REVIEW")
    with pytest.raises(ReasonRequired):
        change_status(db_session, case, "NO_ISSUE", ACTOR, ["AUD"], reason="   ")
    change_status(db_session, case, "NO_ISSUE", ACTOR, ["AUD"], reason="Emergency purchase, post-facto PR on file")
    assert case.closure_reason == "Emergency purchase, post-facto PR on file"


def test_critical_no_issue_needs_audit_manager(db_session):
    case = new_case(db_session, priority="CRITICAL")
    assign_case(db_session, case, AUDITOR, ACTOR)
    walk(db_session, case, "IN_INVESTIGATION", "PENDING_REVIEW")
    with pytest.raises(ManagerApprovalRequired):
        change_status(db_session, case, "NO_ISSUE", ACTOR, ["AUD"], reason="checked")
    change_status(db_session, case, "NO_ISSUE", ACTOR, ["AM"], reason="checked")
    assert case.status == "NO_ISSUE"


def test_high_case_close_needs_audit_manager_and_reopen_clears_closed_at(db_session):
    case = new_case(db_session, priority="HIGH")
    assign_case(db_session, case, AUDITOR, ACTOR)
    walk(db_session, case, "IN_INVESTIGATION", "PENDING_REVIEW", "FINDING_CONFIRMED", "ACTION_IN_PROGRESS")
    with pytest.raises(ManagerApprovalRequired):
        change_status(db_session, case, "CLOSED", ACTOR, ["AUD"])
    assert case.status == "ACTION_IN_PROGRESS"

    change_status(db_session, case, "CLOSED", ACTOR, ["AM"])
    assert case.status == "CLOSED" and case.closed_at is not None
    change_status(db_session, case, "REOPENED", ACTOR, ["AM"])
    assert case.status == "REOPENED" and case.closed_at is None


def test_low_case_can_be_closed_by_auditor(db_session):
    case = new_case(db_session, priority="LOW")
    assign_case(db_session, case, AUDITOR, ACTOR)
    walk(db_session, case, "IN_INVESTIGATION", "PENDING_REVIEW")
    change_status(db_session, case, "NO_ISSUE", ACTOR, ["AUD"], reason="duplicate of earlier case")
    change_status(db_session, case, "CLOSED", ACTOR, ["AUD"])
    assert case.status == "CLOSED"


def test_every_action_is_in_the_audit_log_in_order(db_session):
    case = new_case(db_session, priority="LOW")
    assign_case(db_session, case, AUDITOR, ACTOR)
    walk(db_session, case, "IN_INVESTIGATION", "ON_HOLD", "IN_INVESTIGATION")

    log = list_for_entity(db_session, case.tenant_id, "audit_case", case.id)
    assert [row.action for row in log] == [
        "case.opened", "case.assigned", "case.status_changed", "case.status_changed", "case.status_changed"]
    assert [(row.details.get("from"), row.details.get("to")) for row in log[2:]] == [
        ("ASSIGNED", "IN_INVESTIGATION"), ("IN_INVESTIGATION", "ON_HOLD"), ("ON_HOLD", "IN_INVESTIGATION")]
    assert log[1].details == {"from": None, "to": str(AUDITOR)}
    assert all(row.actor_id == ACTOR for row in log)


def test_refused_change_writes_no_log(db_session):
    case = new_case(db_session)
    with pytest.raises(InvalidTransition):
        change_status(db_session, case, "CLOSED", ACTOR, ["AM"])
    assert [row.action for row in list_for_entity(db_session, case.tenant_id, "audit_case", case.id)] == [
        "case.opened"]


# --- Fixes: hospital-time year, reopen clears reason, closed cases cannot be assigned ---

def test_case_number_uses_the_hospital_year_just_after_midnight_ist(db_session, monkeypatch):
    # 31 Dec 2026 18:45 UTC is 1 Jan 2027 00:15 in India: the case belongs to 2027.
    monkeypatch.setattr(case_service, "_now", lambda: datetime(2026, 12, 31, 18, 45, tzinfo=timezone.utc))
    assert new_case(db_session).case_number == "AUD-2027-00001"


def closed_no_issue_case(db):
    case = new_case(db, priority="LOW")
    assign_case(db, case, AUDITOR, ACTOR)
    walk(db, case, "IN_INVESTIGATION", "PENDING_REVIEW")
    change_status(db, case, "NO_ISSUE", ACTOR, ["AUD"], reason="valid emergency purchase")
    change_status(db, case, "CLOSED", ACTOR, ["AUD"])
    return case


def test_reopen_clears_closure_reason_but_log_keeps_it(db_session):
    case = closed_no_issue_case(db_session)
    change_status(db_session, case, "REOPENED", ACTOR, ["AUD"])
    assert case.closure_reason is None
    reasons = [row.details.get("reason") for row in case_timeline(db_session, case)]
    assert "valid emergency purchase" in reasons


def test_closed_case_cannot_be_assigned(db_session):
    case = closed_no_issue_case(db_session)
    with pytest.raises(CaseClosed, match="reopen the case first"):
        assign_case(db_session, case, uuid.uuid4(), ACTOR)


# --- Comments, lookups, timeline ---

def test_comment_is_saved_and_logged(db_session):
    case = new_case(db_session)
    comment = add_comment(db_session, case, AUDITOR, "  Asked procurement for the approval email.  ")
    assert comment.body == "Asked procurement for the approval email."
    assert case_timeline(db_session, case)[-1].action == "case.commented"


def test_blank_comment_is_refused(db_session):
    case = new_case(db_session)
    with pytest.raises(ValueError):
        add_comment(db_session, case, AUDITOR, "   ")


def test_get_case_for_another_hospital_is_none(db_session):
    case = new_case(db_session)
    assert get_case(db_session, case.tenant_id, case.id) is case
    assert get_case(db_session, uuid.uuid4(), case.id) is None


def test_list_cases_filters_and_never_shows_other_hospitals(db_session):
    tenant = uuid.uuid4()
    first = new_case(db_session, tenant, priority="LOW")
    second = new_case(db_session, tenant, domain="INSURANCE")
    third = new_case(db_session, tenant)
    assign_case(db_session, third, AUDITOR, ACTOR)
    closed = closed_no_issue_case(db_session)                      # in another hospital
    new_case(db_session, closed.tenant_id)                         # another hospital's open case

    assert list_cases(db_session, tenant) == [third, second, first]          # newest first
    assert list_cases(db_session, tenant, status="ASSIGNED") == [third]
    assert list_cases(db_session, tenant, domain="INSURANCE") == [second]
    assert list_cases(db_session, tenant, assigned_to=AUDITOR) == [third]
    assert closed not in list_cases(db_session, closed.tenant_id, open_only=True)
    assert len(list_cases(db_session, closed.tenant_id)) == 2


def test_timeline_shows_opened_assigned_commented_status_changed(db_session):
    case = new_case(db_session)
    assign_case(db_session, case, AUDITOR, ACTOR)
    add_comment(db_session, case, AUDITOR, "Started review")
    change_status(db_session, case, "IN_INVESTIGATION", AUDITOR, ["AUD"])
    assert [row.action for row in case_timeline(db_session, case)] == [
        "case.opened", "case.assigned", "case.commented", "case.status_changed"]


def test_case_exceptions_returns_the_linked_exceptions(db_session):
    tenant = uuid.uuid4()
    excs = [make_exception(db_session, tenant), make_exception(db_session, tenant)]
    case = new_case(db_session, tenant, exceptions=excs)
    assert {e.id for e in case_exceptions(db_session, case)} == {e.id for e in excs}
