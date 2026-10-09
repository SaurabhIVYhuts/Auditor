"""Tests for the finding service (AUD-031): draft, submit, review, and what it means for the case."""
import uuid
from datetime import timedelta

import pytest

from agents.audit.findings.state_machine import InvalidTransition
from agents.audit.services.case_service import (
    FindingsStillOpen, ManagerApprovalRequired, ReasonRequired, _hospital_today, assign_case, change_status,
    open_case,
)
from agents.audit.services.evidence_service import link_evidence, snapshot_evidence, supersede_evidence
from agents.audit.services.finding_service import (
    EvidenceRequired, FieldsRequired, confirm_finding, create_finding, dismiss_finding, get_finding,
    list_findings, return_finding, submit_finding, update_finding,
)
from agents.audit.services.rule_registry import MakerCheckerError
from agents.audit.services.snapshot_service import capture_snapshot
from shared.audit_log import list_for_entity
from shared.notifications import list_for_user

AUTHOR, MANAGER, OTHER_MANAGER, OWNER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
COMPLETE = {"condition": "PO PO-1 for Rs 2,00,000 approved at level 1 only",
            "criteria": "Policy: POs above the high-value limit need level-2 approval",
            "recommendation": "Obtain retrospective level-2 approval and remind approvers",
            "risk_level": "HIGH"}


def tomorrow():
    return _hospital_today() + timedelta(days=1)


def a_case(db, tenant=None, priority="HIGH"):
    return open_case(db, tenant or uuid.uuid4(), domain="PROCUREMENT", title="High-value PO", source="MANUAL",
                     primary_entity_type="purchase_order", primary_entity_id=uuid.uuid4(), priority=priority,
                     actor_id=MANAGER)


def with_evidence(db, finding):
    record = capture_snapshot(db, tenant_id=finding.tenant_id, source_system="procurement",
                              entity_type="purchase_order", entity_id=uuid.uuid4(), data={"po_number": "PO-1"})
    evidence = snapshot_evidence(db, record, "PO PO-1 snapshot")
    link_evidence(db, evidence, "FINDING", finding.id, AUTHOR)
    return evidence


def submitted(db, case=None, **fields):
    finding = create_finding(db, case or a_case(db), "High-value PO without level-2 approval", AUTHOR,
                             **{**COMPLETE, **fields})
    evidence = with_evidence(db, finding)
    submit_finding(db, finding, AUTHOR)
    return finding, evidence


def confirm(db, finding, actor=MANAGER, roles=("AM",), **kw):
    return confirm_finding(db, finding, actor, list(roles), **{"owner_user_id": OWNER, "due_date": tomorrow(), **kw})


def test_full_path_create_evidence_submit_confirm(db_session):
    finding, _ = submitted(db_session)
    assert finding.finding_number.startswith("FND-") and finding.status == "UNDER_REVIEW"
    assert finding.submitted_by == AUTHOR and finding.submitted_at is not None
    confirm(db_session, finding)
    assert (finding.status, finding.confirmed_by, finding.owner_user_id) == ("CONFIRMED", MANAGER, OWNER)
    assert get_finding(db_session, finding.tenant_id, finding.id) is finding
    assert get_finding(db_session, uuid.uuid4(), finding.id) is None
    assert list_findings(db_session, finding.tenant_id, status="CONFIRMED") == [finding]


def test_submit_without_evidence_is_refused(db_session):
    finding = create_finding(db_session, a_case(db_session), "No evidence yet", AUTHOR, **COMPLETE)
    with pytest.raises(EvidenceRequired):
        submit_finding(db_session, finding, AUTHOR)


def test_submit_lists_the_missing_fields(db_session):
    finding = create_finding(db_session, a_case(db_session), "Half written", AUTHOR, condition="Something odd")
    with_evidence(db_session, finding)
    with pytest.raises(FieldsRequired) as caught:
        submit_finding(db_session, finding, AUTHOR)
    assert caught.value.missing == ["criteria", "recommendation", "risk_level"]


def test_only_draft_can_be_edited_and_only_changes_are_logged(db_session):
    finding = create_finding(db_session, a_case(db_session), "Draft", AUTHOR, **COMPLETE)
    update_finding(db_session, finding, AUTHOR, risk_level="HIGH", cause="Approver on leave")
    log = list_for_entity(db_session, finding.tenant_id, "audit_finding", finding.id)
    assert log[-1].details == {"cause": {"from": None, "to": "Approver on leave"}}
    with_evidence(db_session, finding)
    submit_finding(db_session, finding, AUTHOR)
    with pytest.raises(ValueError):
        update_finding(db_session, finding, AUTHOR, cause="too late")


def test_author_confirming_own_finding_is_maker_checker(db_session):
    finding, _ = submitted(db_session)
    with pytest.raises(MakerCheckerError):
        confirm(db_session, finding, actor=AUTHOR)


def test_auditor_cannot_confirm(db_session):
    finding, _ = submitted(db_session)
    with pytest.raises(ManagerApprovalRequired):
        confirm(db_session, finding, actor=OTHER_MANAGER, roles=("AUD",))


def test_confirm_needs_owner_and_a_due_date_not_in_the_past(db_session):
    finding, _ = submitted(db_session)
    with pytest.raises(FieldsRequired) as caught:
        confirm_finding(db_session, finding, MANAGER, ["AM"], owner_user_id=OWNER)
    assert caught.value.missing == ["due_date"]
    with pytest.raises(ValueError, match="past"):
        confirm(db_session, finding, due_date=_hospital_today() - timedelta(days=1))
    assert finding.status == "UNDER_REVIEW"


def test_return_and_dismiss_need_a_reason(db_session):
    finding, _ = submitted(db_session)
    with pytest.raises(ReasonRequired):
        return_finding(db_session, finding, MANAGER, ["AM"], "  ")
    return_finding(db_session, finding, MANAGER, ["AM"], "Add the approval matrix reference")
    assert (finding.status, finding.submitted_by) == ("DRAFT", None)
    submit_finding(db_session, finding, AUTHOR)
    with pytest.raises(ReasonRequired):
        dismiss_finding(db_session, finding, MANAGER, ["AM"], "")
    dismiss_finding(db_session, finding, MANAGER, ["AM"], "Emergency purchase, post-facto approval on file")
    assert finding.status == "DISMISSED"
    with pytest.raises(InvalidTransition):
        submit_finding(db_session, finding, AUTHOR)


def test_owner_notified_and_critical_notifies_management(db_session):
    finding, _ = submitted(db_session, risk_level="CRITICAL")
    confirm(db_session, finding)
    owner_notes = [n.kind for n in list_for_user(db_session, finding.tenant_id, OWNER, ["OWN"])]
    board_notes = [n.kind for n in list_for_user(db_session, finding.tenant_id, uuid.uuid4(), ["MGT"])]
    assert owner_notes == ["finding.confirmed"] and board_notes == ["finding.critical_confirmed"]


def test_high_finding_does_not_notify_management(db_session):
    finding, _ = submitted(db_session, risk_level="HIGH")
    confirm(db_session, finding)
    assert list_for_user(db_session, finding.tenant_id, uuid.uuid4(), ["MGT"]) == []


def test_case_cannot_close_while_a_finding_is_open(db_session):
    case = a_case(db_session, priority="MEDIUM")
    assign_case(db_session, case, AUTHOR, MANAGER)
    for status in ("IN_INVESTIGATION", "PENDING_REVIEW", "FINDING_CONFIRMED", "ACTION_IN_PROGRESS"):
        change_status(db_session, case, status, MANAGER, ["AM"])
    finding, _ = submitted(db_session, case)
    with pytest.raises(FindingsStillOpen, match="1 finding still open"):
        change_status(db_session, case, "CLOSED", MANAGER, ["AM"])
    dismiss_finding(db_session, finding, MANAGER, ["AM"], "Covered by an existing finding")
    change_status(db_session, case, "CLOSED", MANAGER, ["AM"])
    assert case.status == "CLOSED"


def test_closed_case_gets_no_new_finding(db_session):
    case = a_case(db_session, priority="LOW")
    assign_case(db_session, case, AUTHOR, MANAGER)
    for status in ("IN_INVESTIGATION", "PENDING_REVIEW"):
        change_status(db_session, case, status, MANAGER, ["AM"])
    change_status(db_session, case, "NO_ISSUE", MANAGER, ["AM"], reason="checked")
    change_status(db_session, case, "CLOSED", MANAGER, ["AM"])
    with pytest.raises(ValueError, match="reopen"):
        create_finding(db_session, case, "Too late", AUTHOR)


def test_superseding_evidence_of_a_confirmed_finding_needs_audit_manager(db_session):
    finding, evidence = submitted(db_session)
    confirm(db_session, finding)
    with pytest.raises(ManagerApprovalRequired):
        supersede_evidence(db_session, evidence, "Better copy", AUTHOR, ["AUD"])
    supersede_evidence(db_session, evidence, "Better copy", MANAGER, ["AM"])
    assert evidence.status == "SUPERSEDED"


def test_evidence_of_a_draft_finding_can_be_superseded_by_the_auditor(db_session):
    finding = create_finding(db_session, a_case(db_session), "Draft", AUTHOR, **COMPLETE)
    evidence = with_evidence(db_session, finding)
    supersede_evidence(db_session, evidence, "Wrong record", AUTHOR, ["AUD"])
    assert evidence.status == "SUPERSEDED"


def test_every_step_is_in_the_audit_log(db_session):
    finding, _ = submitted(db_session)
    confirm(db_session, finding)
    log = list_for_entity(db_session, finding.tenant_id, "audit_finding", finding.id)
    assert [row.action for row in log] == ["finding.created", "finding.submitted", "finding.confirmed"]
    assert [row.actor_id for row in log] == [AUTHOR, AUTHOR, MANAGER]
