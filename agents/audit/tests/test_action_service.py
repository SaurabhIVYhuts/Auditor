"""Tests for corrective actions (AUD-032): the owner's loop, verification, and what it does to the finding."""
import uuid
from datetime import timedelta

import pytest

from agents.audit.models import AuditCase
from agents.audit.services.action_service import (
    create_action, return_action, run_action_reminders, start_action, submit_action, verify_action,
)
from agents.audit.services.case_service import (
    FindingsStillOpen, ManagerApprovalRequired, _hospital_today, assign_case, change_status,
)
from agents.audit.services.evidence_service import link_evidence, upload_evidence
from agents.audit.services.finding_service import EvidenceRequired, close_finding
from agents.audit.services.rule_registry import MakerCheckerError, set_config_value
from agents.audit.tests.test_documents import PDF, temp_storage  # noqa: F401  (fixture: files go to tmp)
from agents.audit.tests.test_finding_service import AUTHOR, MANAGER, OWNER, confirm, submitted, tomorrow
from agents.audit.workflow import NotAllowed
from shared.audit_log import list_for_entity
from shared.notifications import list_for_user


def confirmed(db, **fields):
    finding, _ = submitted(db, **fields)
    confirm(db, finding)
    return finding


def new_action(db, finding, owner=OWNER):
    return create_action(db, finding, "Obtain retrospective level-2 approval", owner, tomorrow(), MANAGER, ["AM"])


def evidence_for(db, action, actor=OWNER):
    item = upload_evidence(db, action.tenant_id, title="Signed approval", filename="approval.pdf",
                           content_type="application/pdf", data=PDF, actor_id=actor)
    link_evidence(db, item, "ACTION", action.id, actor)
    return item


def handed_in(db, finding, owner=OWNER):
    action = new_action(db, finding, owner)
    start_action(db, action, owner)
    evidence_for(db, action, owner)
    submit_action(db, action, owner)
    return action


def walk_case(db, case):
    assign_case(db, case, AUTHOR, MANAGER)
    for status in ("IN_INVESTIGATION", "PENDING_REVIEW", "FINDING_CONFIRMED", "ACTION_IN_PROGRESS"):
        change_status(db, case, status, MANAGER, ["AM"])


def test_full_loop_from_confirmed_finding_to_closed_case(db_session):
    finding = confirmed(db_session)
    case = db_session.get(AuditCase, finding.case_id)
    walk_case(db_session, case)

    action = new_action(db_session, finding)
    assert (action.status, finding.status) == ("OPEN", "ACTION_ASSIGNED")
    assert action.action_number.startswith("ACT-")
    with pytest.raises(FindingsStillOpen, match="1 finding / 1 action still open"):
        change_status(db_session, case, "CLOSED", MANAGER, ["AM"])

    start_action(db_session, action, OWNER)
    evidence_for(db_session, action)
    submit_action(db_session, action, OWNER)
    assert (action.status, finding.status) == ("SUBMITTED", "RESOLVED")

    verify_action(db_session, action, AUTHOR, ["AUD"], note="Approval email checked")
    assert (action.status, action.verified_by, finding.status) == ("VERIFIED", AUTHOR, "VERIFIED")

    close_finding(db_session, finding, AUTHOR, ["AUD"])
    assert (finding.status, action.status) == ("CLOSED", "CLOSED") and action.closed_at is not None
    change_status(db_session, case, "CLOSED", MANAGER, ["AM"])
    assert case.status == "CLOSED"


def test_submit_without_evidence_is_refused(db_session):
    action = new_action(db_session, confirmed(db_session))
    start_action(db_session, action, OWNER)
    with pytest.raises(EvidenceRequired):
        submit_action(db_session, action, OWNER)


def test_only_the_owner_starts_and_submits(db_session):
    action = new_action(db_session, confirmed(db_session))
    with pytest.raises(NotAllowed):
        start_action(db_session, action, AUTHOR)
    start_action(db_session, action, OWNER)
    evidence_for(db_session, action)
    with pytest.raises(NotAllowed):
        submit_action(db_session, action, AUTHOR)


def test_owner_cannot_verify_own_action(db_session):
    action = handed_in(db_session, confirmed(db_session))
    with pytest.raises(MakerCheckerError):
        verify_action(db_session, action, OWNER, ["AUD"])


def test_auditee_cannot_verify(db_session):
    action = handed_in(db_session, confirmed(db_session))
    with pytest.raises(NotAllowed):
        verify_action(db_session, action, uuid.uuid4(), ["OWN"])


def test_return_reopens_the_finding_then_restart_reassigns_it(db_session):
    finding = confirmed(db_session)
    action = handed_in(db_session, finding)
    assert finding.status == "RESOLVED"
    with pytest.raises(ValueError):
        return_action(db_session, action, AUTHOR, ["AUD"], "  ")
    return_action(db_session, action, AUTHOR, ["AUD"], "The email does not show the level-2 approver")
    assert (action.status, finding.status) == ("RETURNED", "REOPENED")
    assert "action.returned" in [n.kind for n in list_for_user(db_session, finding.tenant_id, OWNER, ["OWN"])]
    start_action(db_session, action, OWNER)
    assert (action.status, finding.status) == ("IN_PROGRESS", "ACTION_ASSIGNED")


def test_finding_waits_until_every_action_is_handed_in(db_session):
    finding = confirmed(db_session)
    first, second = new_action(db_session, finding), new_action(db_session, finding)
    start_action(db_session, first, OWNER)
    evidence_for(db_session, first)
    submit_action(db_session, first, OWNER)
    assert finding.status == "ACTION_ASSIGNED"              # second action not handed in yet
    start_action(db_session, second, OWNER)
    evidence_for(db_session, second)
    submit_action(db_session, second, OWNER)
    assert finding.status == "RESOLVED"
    with pytest.raises(ValueError, match="confirmed finding"):
        new_action(db_session, finding)                     # a RESOLVED finding takes no new actions
    verify_action(db_session, first, AUTHOR, ["AUD"])
    assert finding.status == "RESOLVED"                     # one still waiting for verification
    verify_action(db_session, second, AUTHOR, ["AUD"])
    assert finding.status == "VERIFIED"


def test_critical_finding_actions_need_audit_manager_to_verify(db_session):
    action = handed_in(db_session, confirmed(db_session, risk_level="CRITICAL"))
    with pytest.raises(ManagerApprovalRequired):
        verify_action(db_session, action, AUTHOR, ["AUD"])
    verify_action(db_session, action, MANAGER, ["AM"])
    assert action.status == "VERIFIED"


def test_past_due_date_and_unconfirmed_findings_are_refused(db_session):
    finding = confirmed(db_session)
    with pytest.raises(ValueError, match="past"):
        create_action(db_session, finding, "Fix", OWNER, _hospital_today() - timedelta(days=1), MANAGER, ["AM"])
    draft, _ = submitted(db_session)                          # UNDER_REVIEW, not confirmed
    with pytest.raises(ValueError, match="confirmed finding"):
        new_action(db_session, draft)
    with pytest.raises(NotAllowed):
        create_action(db_session, finding, "Fix", OWNER, tomorrow(), uuid.uuid4(), ["MGT"])


def test_owner_is_notified_and_every_step_logged(db_session):
    finding = confirmed(db_session)
    action = handed_in(db_session, finding)
    verify_action(db_session, action, AUTHOR, ["AUD"])
    kinds = [n.kind for n in list_for_user(db_session, finding.tenant_id, OWNER, ["OWN"])]
    assert "action.assigned" in kinds
    log = list_for_entity(db_session, action.tenant_id, "corrective_action", action.id)
    assert [row.action for row in log] == ["action.created", "action.started", "action.submitted", "action.verified"]
    assert [row.actor_id for row in log] == [MANAGER, OWNER, OWNER, AUTHOR]
    synced = [row.details["to"] for row in list_for_entity(db_session, finding.tenant_id, "audit_finding", finding.id)
              if row.action == "finding.status_changed"]
    assert synced == ["ACTION_ASSIGNED", "RESOLVED", "VERIFIED"]


def kinds_for(db, tenant, roles, user=None):
    return [n.kind for n in list_for_user(db, tenant, user or uuid.uuid4(), roles)]


def remind(db, action, days_from_due):
    """Run the daily reminders as if today were due_date + days_from_due (negative = before)."""
    return run_action_reminders(db, action.tenant_id, today=action.due_date + timedelta(days=days_from_due))


def test_reminders_7_3_1_days_before_then_overdue_then_escalated(db_session):
    action = new_action(db_session, confirmed(db_session))
    tenant = action.tenant_id
    assert remind(db_session, action, -10) == {"due_soon": 0, "overdue": 0, "escalated": 0}
    for days, key in ((-7, "due-7"), (-3, "due-3"), (-1, "due-1")):
        assert remind(db_session, action, days)["due_soon"] == 1
        assert action.reminders_sent[-1] == key
    assert remind(db_session, action, -1) == {"due_soon": 0, "overdue": 0, "escalated": 0}   # same day again
    assert kinds_for(db_session, tenant, ["OWN"], OWNER).count("action.due") == 3

    assert remind(db_session, action, 1) == {"due_soon": 0, "overdue": 1, "escalated": 0}
    assert "action.overdue" in kinds_for(db_session, tenant, ["AM"])            # Audit Managers told too
    assert "action.overdue" in kinds_for(db_session, tenant, ["OWN"], OWNER)
    assert remind(db_session, action, 30) == {"due_soon": 0, "overdue": 0, "escalated": 0}  # not MORE than 30
    assert remind(db_session, action, 31) == {"due_soon": 0, "overdue": 0, "escalated": 1}
    assert "action.escalated" in kinds_for(db_session, tenant, ["MGT"])
    assert remind(db_session, action, 31) == {"due_soon": 0, "overdue": 0, "escalated": 0}  # sent once
    assert action.reminders_sent == ["due-7", "due-3", "due-1", "overdue", "escalated"]
    log = [row.action for row in list_for_entity(db_session, tenant, "corrective_action", action.id)]
    assert log.count("action.reminder_sent") == 5


def test_late_first_run_sends_only_the_closest_reminder(db_session):
    action = new_action(db_session, confirmed(db_session))
    assert remind(db_session, action, -2)["due_soon"] == 1
    assert action.reminders_sent == ["due-3"]
    assert remind(db_session, action, 45) == {"due_soon": 0, "overdue": 1, "escalated": 1}


def test_submitted_actions_get_no_reminders(db_session):
    action = handed_in(db_session, confirmed(db_session))
    assert remind(db_session, action, -1) == {"due_soon": 0, "overdue": 0, "escalated": 0}
    assert remind(db_session, action, 40) == {"due_soon": 0, "overdue": 0, "escalated": 0}
    assert action.reminders_sent == []


def test_reminder_days_come_from_audit_config(db_session):
    action = new_action(db_session, confirmed(db_session))
    set_config_value(db_session, tenant_id=action.tenant_id, key="action_reminder_days", value=[14])
    set_config_value(db_session, tenant_id=action.tenant_id, key="action_escalation_days", value=5)
    assert remind(db_session, action, -7)["due_soon"] == 1 and action.reminders_sent == ["due-14"]
    assert remind(db_session, action, 6) == {"due_soon": 0, "overdue": 1, "escalated": 1}
