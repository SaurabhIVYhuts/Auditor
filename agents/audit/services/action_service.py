"""Corrective action service (AUD-032): make confirmed findings lead to real fixes, with proof.

The owner (usually the audited department) starts the action, uploads evidence and submits it;
an auditor who is NOT the owner verifies or returns it. After every change the finding follows
its actions (sync_finding). Every step is in the audit log (entity_type "corrective_action").
Flushes, never commits.
"""
import uuid
from collections.abc import Iterable
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.audit.actions.state_machine import (
    DONE_STATUSES, SUBMITTED_OR_LATER, ActionStatus, ensure_transition,
)
from agents.audit.cases.numbering import next_number
from agents.audit.findings.state_machine import FindingStatus
from agents.audit.findings.state_machine import path as finding_path
from agents.audit.models import (
    AuditCase, AuditEvidence, AuditEvidenceLink, AuditFinding, CorrectiveAction, EvidenceStatus, LinkTarget,
    Severity,
)
from agents.audit.models.action import ACTION_ENTITY
from agents.audit.permissions import AuditRole, has_permission
from agents.audit.services.case_service import ManagerApprovalRequired, ReasonRequired, _hospital_today, _hospital_year, _now
from agents.audit.services.finding_service import FINDING_ENTITY, EvidenceRequired, FieldsRequired
from agents.audit.services.rule_registry import MakerCheckerError
from agents.audit.workflow import NotAllowed
from shared.audit_log import log_action
from shared.notifications import notify_role, notify_user

ACTION_PREFIX = "ACT"
WRITE_PERMISSION = "action:write"          # Auditor, Audit Manager
VERIFY_PERMISSION = "action:verify"        # Auditor, Audit Manager
MANAGER_PERMISSION = "finding:confirm"     # Audit Manager only
FINDINGS_TAKING_ACTIONS = frozenset({FindingStatus.CONFIRMED.value, FindingStatus.ACTION_ASSIGNED.value,
                                     FindingStatus.REOPENED.value})


def _log(db: Session, action: CorrectiveAction, actor_id: uuid.UUID | None, event: str, **details) -> None:
    log_action(db, action.tenant_id, actor_id, event, ACTION_ENTITY, action.id, details)


def _finding(db: Session, action: CorrectiveAction) -> AuditFinding:
    return db.get(AuditFinding, action.finding_id)


def _owner_only(action: CorrectiveAction, actor_id: uuid.UUID | None, what: str) -> None:
    if actor_id != action.owner_user_id:
        raise NotAllowed(f"Only the owner of {action.action_number} can {what}")


def _move(db: Session, action: CorrectiveAction, target: ActionStatus, actor_id: uuid.UUID | None) -> str:
    """Change the action's status (state machine checked); returns the old status."""
    current = action.status
    ensure_transition(current, target)
    action.status, action.updated_by = target.value, actor_id
    return current


def sync_finding(db: Session, finding: AuditFinding, actor_id: uuid.UUID | None) -> None:
    """Make the finding follow its actions:
    all verified -> VERIFIED; all submitted (or later) -> RESOLVED; an action returned after the
    finding was resolved -> REOPENED; otherwise (actions in work) -> ACTION_ASSIGNED.
    """
    statuses = [a.status for a in db.scalars(select(CorrectiveAction).where(
        CorrectiveAction.finding_id == finding.id, CorrectiveAction.is_deleted.is_(False)))]
    if not statuses or finding.status in (FindingStatus.VERIFIED.value, FindingStatus.CLOSED.value):
        return
    if all(s in DONE_STATUSES for s in statuses):
        target = FindingStatus.VERIFIED
    elif all(s in SUBMITTED_OR_LATER for s in statuses):
        target = FindingStatus.RESOLVED
    elif ActionStatus.RETURNED.value in statuses and finding.status in (
            FindingStatus.RESOLVED.value, FindingStatus.REOPENED.value):
        target = FindingStatus.REOPENED
    else:
        target = FindingStatus.ACTION_ASSIGNED
    steps = finding_path(finding.status, target)
    for step in steps or []:                       # None: no allowed route, leave the finding as it is
        previous, finding.status = finding.status, step.value
        log_action(db, finding.tenant_id, actor_id, "finding.status_changed", FINDING_ENTITY, finding.id,
                   {"from": previous, "to": step.value, "reason": "corrective actions"})
    db.flush()


def create_action(
    db: Session, finding: AuditFinding, description: str, owner_user_id: uuid.UUID | None, due_date: date | None,
    actor_id: uuid.UUID, actor_roles: Iterable[str], *, owner_department_id: uuid.UUID | None = None,
    required_evidence_type: str | None = None,
) -> CorrectiveAction:
    """Assign a corrective action on a confirmed finding (audit team only). Notifies the owner."""
    if not has_permission(actor_roles, WRITE_PERMISSION):
        raise NotAllowed("Only the audit team can create corrective actions")
    if finding.status not in FINDINGS_TAKING_ACTIONS:
        raise ValueError("Corrective actions can only be added to a confirmed finding")
    description = (description or "").strip()
    missing = [name for name, value in (("description", description), ("owner_user_id", owner_user_id),
                                        ("due_date", due_date)) if not value]
    if missing:
        raise FieldsRequired(missing, "creating the action")
    if due_date < _hospital_today():
        raise ValueError("The due date cannot be in the past")
    action = CorrectiveAction(
        tenant_id=finding.tenant_id, finding_id=finding.id, case_id=finding.case_id,
        action_number=next_number(db, finding.tenant_id, ACTION_PREFIX, _hospital_year()),
        description=description, owner_user_id=owner_user_id, owner_department_id=owner_department_id,
        due_date=due_date, required_evidence_type=required_evidence_type, created_by=actor_id,
    )
    db.add(action)
    db.flush()
    _log(db, action, actor_id, "action.created", finding_id=str(finding.id), owner_user_id=str(owner_user_id),
         due_date=str(due_date))
    notify_user(db, action.tenant_id, owner_user_id, "action.assigned",
                f"Corrective action {action.action_number} assigned to you, due {due_date}", description,
                ACTION_ENTITY, action.id)
    sync_finding(db, finding, actor_id)
    return action


def start_action(db: Session, action: CorrectiveAction, actor_id: uuid.UUID) -> CorrectiveAction:
    """The owner starts (or restarts, after a return) the work."""
    _owner_only(action, actor_id, "start it")
    previous = _move(db, action, ActionStatus.IN_PROGRESS, actor_id)
    db.flush()
    _log(db, action, actor_id, "action.started", **{"from": previous})
    sync_finding(db, _finding(db, action), actor_id)
    return action


def _has_active_evidence(db: Session, action: CorrectiveAction) -> bool:
    return db.scalar(
        select(AuditEvidence.id)
        .join(AuditEvidenceLink, AuditEvidenceLink.evidence_id == AuditEvidence.id)
        .where(AuditEvidenceLink.target_type == LinkTarget.ACTION.value, AuditEvidenceLink.target_id == action.id,
               AuditEvidence.status == EvidenceStatus.ACTIVE.value)
        .limit(1)
    ) is not None


def submit_action(db: Session, action: CorrectiveAction, actor_id: uuid.UUID) -> CorrectiveAction:
    """The owner hands the action in for verification; it needs at least one ACTIVE evidence item."""
    _owner_only(action, actor_id, "submit it")
    ensure_transition(action.status, ActionStatus.SUBMITTED)
    if not _has_active_evidence(db, action):
        raise EvidenceRequired("Upload at least one piece of evidence before submitting the action")
    _move(db, action, ActionStatus.SUBMITTED, actor_id)
    action.submitted_at = _now()
    db.flush()
    _log(db, action, actor_id, "action.submitted")
    case = db.get(AuditCase, action.case_id)
    title = f"Corrective action {action.action_number} submitted for verification"
    if case and case.assigned_to:
        notify_user(db, action.tenant_id, case.assigned_to, "action.submitted", title, action.description,
                    ACTION_ENTITY, action.id)
    else:
        notify_role(db, action.tenant_id, AuditRole.AUDIT_MANAGER.value, "action.submitted", title,
                    action.description, ACTION_ENTITY, action.id)
    sync_finding(db, _finding(db, action), actor_id)
    return action


def _check_verifier(db: Session, action: CorrectiveAction, actor_id: uuid.UUID, actor_roles: Iterable[str]) -> None:
    if not has_permission(actor_roles, VERIFY_PERMISSION):
        raise NotAllowed("Only the audit team can verify corrective actions")
    if actor_id == action.owner_user_id:
        raise MakerCheckerError("MAKER_CHECKER: the owner of an action cannot verify it")
    if _finding(db, action).risk_level == Severity.CRITICAL.value and not has_permission(actor_roles,
                                                                                         MANAGER_PERMISSION):
        raise ManagerApprovalRequired("Only an Audit Manager can verify actions of a CRITICAL finding")


def verify_action(db: Session, action: CorrectiveAction, actor_id: uuid.UUID, actor_roles: Iterable[str],
                  note: str | None = None) -> CorrectiveAction:
    """Accept the owner's work (someone other than the owner; an Audit Manager for CRITICAL findings)."""
    ensure_transition(action.status, ActionStatus.VERIFIED)
    _check_verifier(db, action, actor_id, actor_roles)
    _move(db, action, ActionStatus.VERIFIED, actor_id)
    action.verified_by, action.verified_at = actor_id, _now()
    action.verification_note = (note or "").strip() or None
    db.flush()
    _log(db, action, actor_id, "action.verified", note=action.verification_note)
    sync_finding(db, _finding(db, action), actor_id)
    return action


def return_action(db: Session, action: CorrectiveAction, actor_id: uuid.UUID, actor_roles: Iterable[str],
                  note: str) -> CorrectiveAction:
    """Send the action back to the owner with a note (e.g. the evidence does not show the fix)."""
    ensure_transition(action.status, ActionStatus.RETURNED)
    _check_verifier(db, action, actor_id, actor_roles)
    note = (note or "").strip()
    if not note:
        raise ReasonRequired("A note is required when returning an action")
    _move(db, action, ActionStatus.RETURNED, actor_id)
    action.return_note = note
    db.flush()
    _log(db, action, actor_id, "action.returned", note=note)
    notify_user(db, action.tenant_id, action.owner_user_id, "action.returned",
                f"Corrective action {action.action_number} returned for more work", note, ACTION_ENTITY, action.id)
    sync_finding(db, _finding(db, action), actor_id)
    return action


def actions_for_finding(db: Session, finding: AuditFinding) -> list[CorrectiveAction]:
    return list(db.scalars(select(CorrectiveAction).where(
        CorrectiveAction.finding_id == finding.id, CorrectiveAction.is_deleted.is_(False),
    ).order_by(CorrectiveAction.created_at, CorrectiveAction.action_number)))
