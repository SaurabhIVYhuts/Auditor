"""Finding service (AUD-031): draft, submit, review (confirm / return / dismiss) audit findings.

A finding is a human-confirmed observation: it needs evidence before it can be submitted, and
someone other than its author or submitter (an Audit Manager) must confirm it (maker-checker).
Every step is checked by the finding state machine and written to the audit log
(entity_type "audit_finding"). Flushes, never commits.
"""
import uuid
from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.audit.cases.numbering import next_number
from agents.audit.cases.state_machine import CaseStatus
from agents.audit.findings.state_machine import FindingStatus, ensure_transition
from agents.audit.models import (
    AuditCase, AuditEvidence, AuditEvidenceLink, AuditFinding, EvidenceStatus, LinkTarget, Severity,
)
from agents.audit.permissions import AuditRole, has_permission
from agents.audit.services.case_service import (
    CaseClosed, ManagerApprovalRequired, ReasonRequired, _hospital_today, _hospital_year, _now,
)
from agents.audit.services.rule_registry import MakerCheckerError
from shared.audit_log import log_action
from shared.notifications import notify_role, notify_user

FINDING_ENTITY = "audit_finding"
FINDING_PREFIX = "FND"
CONFIRM_PERMISSION = "finding:confirm"      # Audit Manager only
DISMISS_PERMISSION = "finding:dismiss"      # Audit Manager only
EDITABLE_FIELDS = frozenset({
    "title", "condition", "criteria", "cause", "effect", "recommendation", "financial_impact",
    "risk_level", "owner_user_id", "owner_department_id", "due_date", "previous_finding_id",
})
REQUIRED_TO_SUBMIT = ("title", "condition", "criteria", "recommendation", "risk_level")


class FieldsRequired(ValueError):
    """Some fields must be filled in first."""

    def __init__(self, missing: list[str], step: str):
        super().__init__(f"Fill in before {step}: {', '.join(missing)}")
        self.missing = missing


class EvidenceRequired(ValueError):
    """A finding must rest on at least one ACTIVE evidence item."""


def _json(value):
    """Values as they are stored in the audit log (JSON)."""
    if isinstance(value, (uuid.UUID, date, Decimal)):
        return str(value)
    return value


def _log(db: Session, finding: AuditFinding, actor_id: uuid.UUID | None, action: str, **details) -> None:
    log_action(db, finding.tenant_id, actor_id, action, FINDING_ENTITY, finding.id, details)


def _check_fields(fields: dict) -> None:
    unknown = set(fields) - EDITABLE_FIELDS
    if unknown:
        raise ValueError(f"These fields cannot be set: {sorted(unknown)}")
    if fields.get("risk_level") is not None:
        Severity(fields["risk_level"])
    if "title" in fields and not (fields["title"] or "").strip():
        raise ValueError("The title cannot be empty")


def _require_permission(actor_roles: Iterable[str], permission: str, what: str) -> None:
    if not has_permission(actor_roles, permission):
        raise ManagerApprovalRequired(f"Only an Audit Manager can {what}")


def create_finding(db: Session, case: AuditCase, title: str, actor_id: uuid.UUID | None, **fields) -> AuditFinding:
    """Start a DRAFT finding on a case that is not CLOSED."""
    if case.status == CaseStatus.CLOSED.value:
        raise CaseClosed(f"Case {case.case_number} is closed: reopen the case first")
    _check_fields({"title": title, **fields})
    finding = AuditFinding(
        tenant_id=case.tenant_id, case_id=case.id, title=title.strip(),
        finding_number=next_number(db, case.tenant_id, FINDING_PREFIX, _hospital_year()),
        created_by=actor_id, **fields,
    )
    db.add(finding)
    db.flush()
    _log(db, finding, actor_id, "finding.created", finding_number=finding.finding_number, case_id=str(case.id))
    return finding


def update_finding(db: Session, finding: AuditFinding, actor_id: uuid.UUID | None, **fields) -> AuditFinding:
    """Edit a DRAFT finding. Logs only the fields that really changed."""
    if finding.status != FindingStatus.DRAFT.value:
        raise ValueError("Only a DRAFT finding can be edited")
    _check_fields(fields)
    changed = {}
    for field, new in fields.items():
        old = getattr(finding, field)
        if new != old:
            setattr(finding, field, new)
            changed[field] = {"from": _json(old), "to": _json(new)}
    if changed:
        finding.updated_by = actor_id
        db.flush()
        _log(db, finding, actor_id, "finding.updated", **changed)
    return finding


def _has_active_evidence(db: Session, finding: AuditFinding) -> bool:
    return db.scalar(
        select(AuditEvidence.id)
        .join(AuditEvidenceLink, AuditEvidenceLink.evidence_id == AuditEvidence.id)
        .where(AuditEvidenceLink.target_type == LinkTarget.FINDING.value,
               AuditEvidenceLink.target_id == finding.id,
               AuditEvidence.status == EvidenceStatus.ACTIVE.value)
        .limit(1)
    ) is not None


def submit_finding(db: Session, finding: AuditFinding, actor_id: uuid.UUID | None) -> AuditFinding:
    """DRAFT -> UNDER_REVIEW. Needs the key fields and at least one ACTIVE evidence item."""
    ensure_transition(finding.status, FindingStatus.UNDER_REVIEW)
    missing = [f for f in REQUIRED_TO_SUBMIT if not getattr(finding, f)]
    if missing:
        raise FieldsRequired(missing, "submitting")
    if not _has_active_evidence(db, finding):
        raise EvidenceRequired("Link at least one piece of evidence before submitting")
    finding.status = FindingStatus.UNDER_REVIEW.value
    finding.submitted_by, finding.submitted_at = actor_id, _now()
    finding.updated_by = actor_id
    db.flush()
    _log(db, finding, actor_id, "finding.submitted")
    notify_role(db, finding.tenant_id, AuditRole.AUDIT_MANAGER.value, "finding.pending_review",
                f"Finding {finding.finding_number} is ready for review", finding.title, FINDING_ENTITY, finding.id)
    return finding


def confirm_finding(
    db: Session, finding: AuditFinding, actor_id: uuid.UUID, actor_roles: Iterable[str],
    owner_user_id: uuid.UUID | None = None, due_date: date | None = None,
) -> AuditFinding:
    """UNDER_REVIEW -> CONFIRMED by an Audit Manager who neither wrote nor submitted it."""
    ensure_transition(finding.status, FindingStatus.CONFIRMED)
    _require_permission(actor_roles, CONFIRM_PERMISSION, "confirm a finding")
    if actor_id in {finding.created_by, finding.submitted_by} - {None}:
        raise MakerCheckerError("MAKER_CHECKER: the author or submitter of a finding cannot confirm it")
    owner = owner_user_id or finding.owner_user_id
    due = due_date or finding.due_date
    missing = [name for name, value in (("owner_user_id", owner), ("due_date", due)) if value is None]
    if missing:
        raise FieldsRequired(missing, "confirming")
    if due < _hospital_today():
        raise ValueError("The due date cannot be in the past")

    finding.owner_user_id, finding.due_date = owner, due
    finding.status = FindingStatus.CONFIRMED.value
    finding.confirmed_by, finding.confirmed_at = actor_id, _now()
    finding.updated_by = actor_id
    db.flush()
    _log(db, finding, actor_id, "finding.confirmed", owner_user_id=str(owner), due_date=str(due))
    notify_user(db, finding.tenant_id, owner, "finding.confirmed",
                f"Finding {finding.finding_number} confirmed: action needed by {due}", finding.title,
                FINDING_ENTITY, finding.id)
    if finding.risk_level == Severity.CRITICAL.value:
        notify_role(db, finding.tenant_id, AuditRole.MANAGEMENT.value, "finding.critical_confirmed",
                    f"Critical finding {finding.finding_number} confirmed", finding.title, FINDING_ENTITY, finding.id)
    return finding


def return_finding(db: Session, finding: AuditFinding, actor_id: uuid.UUID, actor_roles: Iterable[str],
                   note: str) -> AuditFinding:
    """UNDER_REVIEW -> DRAFT with a note, so the author can make changes."""
    ensure_transition(finding.status, FindingStatus.DRAFT)
    _require_permission(actor_roles, CONFIRM_PERMISSION, "return a finding for changes")
    note = (note or "").strip()
    if not note:
        raise ReasonRequired("A note is required when returning a finding")
    submitter = finding.submitted_by
    finding.status = FindingStatus.DRAFT.value
    finding.submitted_by = finding.submitted_at = None
    finding.updated_by = actor_id
    db.flush()
    _log(db, finding, actor_id, "finding.returned", note=note)
    if submitter:
        notify_user(db, finding.tenant_id, submitter, "finding.returned",
                    f"Finding {finding.finding_number} returned for changes", note, FINDING_ENTITY, finding.id)
    return finding


def dismiss_finding(db: Session, finding: AuditFinding, actor_id: uuid.UUID, actor_roles: Iterable[str],
                    reason: str) -> AuditFinding:
    """UNDER_REVIEW -> DISMISSED with a reason (the reason feeds rule tuning later)."""
    ensure_transition(finding.status, FindingStatus.DISMISSED)
    _require_permission(actor_roles, DISMISS_PERMISSION, "dismiss a finding")
    reason = (reason or "").strip()
    if not reason:
        raise ReasonRequired("A reason is required to dismiss a finding")
    finding.status = FindingStatus.DISMISSED.value
    finding.dismiss_reason = reason
    finding.updated_by = actor_id
    db.flush()
    _log(db, finding, actor_id, "finding.dismissed", reason=reason)
    return finding


def get_finding(db: Session, tenant_id: uuid.UUID, finding_id: uuid.UUID) -> AuditFinding | None:
    """The finding, or None if it does not exist, is deleted, or belongs to another hospital."""
    finding = db.get(AuditFinding, finding_id)
    if finding is None or finding.tenant_id != tenant_id or finding.is_deleted:
        return None
    return finding


def list_findings(
    db: Session, tenant_id: uuid.UUID, case_id: uuid.UUID | None = None, status: str | None = None,
    owner: uuid.UUID | None = None,
) -> list[AuditFinding]:
    """This hospital's findings, newest first, with optional filters."""
    stmt = select(AuditFinding).where(AuditFinding.tenant_id == tenant_id, AuditFinding.is_deleted.is_(False))
    if case_id:
        stmt = stmt.where(AuditFinding.case_id == case_id)
    if status:
        stmt = stmt.where(AuditFinding.status == status)
    if owner:
        stmt = stmt.where(AuditFinding.owner_user_id == owner)
    return list(db.scalars(stmt.order_by(AuditFinding.created_at.desc(), AuditFinding.finding_number.desc())))
