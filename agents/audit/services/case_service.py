"""Case service (AUD-020): open, assign and move cases through the state machine.

Every change is checked by the state machine and written to the audit log in the same
transaction. Does NOT commit: the caller does.
"""
import uuid
from collections.abc import Iterable
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from agents.audit.cases.numbering import next_case_number
from agents.audit.cases.state_machine import OPEN_STATUSES, CaseStatus, ensure_transition
from agents.audit.actions.state_machine import OPEN_STATUSES as ACTION_OPEN_STATUSES
from agents.audit.findings.state_machine import OPEN_STATUSES as FINDING_OPEN_STATUSES
from agents.audit.models import (
    AuditCase, AuditCaseComment, AuditCaseException, AuditException, AuditFinding, CaseDomain, CaseSource,
    CorrectiveAction, ExceptionStatus, Severity,
)
from agents.audit.permissions import AuditRole, has_permission
from shared.audit_log import AuditLog, list_for_entity, log_action
from shared.config import settings
from shared.notifications import notify_role, notify_user

CASE_ENTITY = "audit_case"
NEEDS_MANAGER_TO_CLOSE = frozenset({Severity.HIGH.value, Severity.CRITICAL.value})
MANAGER_PERMISSION = "case:close_high_risk"      # held by the Audit Manager role only


class ReasonRequired(ValueError):
    """Dismissing a case as NO_ISSUE needs a written reason."""


class ManagerApprovalRequired(PermissionError):
    """This step on a high-risk case must be done by an Audit Manager."""


class CaseClosed(ValueError):
    """The case is CLOSED; it must be reopened before this can be done."""


class FindingsStillOpen(ValueError):
    """A case cannot close while it still has findings that need work."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hospital_today() -> date:
    """Today's date in the hospital's time zone."""
    return _now().astimezone(ZoneInfo(settings.hospital_timezone)).date()


def _hospital_year() -> int:
    """Current year in the hospital's time zone (a case opened at 00:15 IST on 1 Jan is next year's)."""
    return _hospital_today().year


def _log(db: Session, case: AuditCase, actor_id: uuid.UUID | None, action: str, **details) -> None:
    log_action(db, case.tenant_id, actor_id, action, CASE_ENTITY, case.id, details)


def open_case(
    db: Session, tenant_id: uuid.UUID, *, domain: str, title: str, source: str,
    primary_entity_type: str, primary_entity_id: uuid.UUID, priority: str,
    actor_id: uuid.UUID | None, department_id: uuid.UUID | None = None,
    exception_ids: Iterable[uuid.UUID] = (),
) -> AuditCase:
    """Open a new case (status OPEN) and link its exceptions, which become IN_CASE."""
    CaseDomain(domain)       # each raises ValueError for an unknown value
    CaseSource(source)
    Severity(priority)
    exception_ids = list(dict.fromkeys(exception_ids))          # drop repeats, keep order
    exceptions = db.scalars(select(AuditException).where(
        AuditException.id.in_(exception_ids), AuditException.tenant_id == tenant_id,
    )).all() if exception_ids else []
    if len(exceptions) != len(exception_ids):
        raise ValueError("Some exceptions were not found for this hospital")
    if any(exc.status != ExceptionStatus.NEW.value for exc in exceptions):
        raise ValueError("Only NEW exceptions can be added to a case")

    case = AuditCase(
        tenant_id=tenant_id,
        case_number=next_case_number(db, tenant_id, _hospital_year()),
        domain=domain, title=title, source=source,
        primary_entity_type=primary_entity_type, primary_entity_id=primary_entity_id,
        department_id=department_id, priority=priority, created_by=actor_id,
    )
    db.add(case)
    db.flush()
    _log(db, case, actor_id, "case.opened", case_number=case.case_number, exceptions=len(exceptions))
    for exc in exceptions:
        add_exception_to_case(db, case, exc, actor_id)
    if priority == Severity.CRITICAL.value:
        notify_role(db, tenant_id, AuditRole.AUDIT_MANAGER.value, "case.critical_opened",
                    f"Critical case {case.case_number} opened", case.title, CASE_ENTITY, case.id)
    return case


def add_exception_to_case(
    db: Session, case: AuditCase, exception: AuditException, actor_id: uuid.UUID | None,
) -> AuditCaseException:
    """Link a NEW exception of the same hospital to a case that is not CLOSED; it becomes IN_CASE."""
    if case.status == CaseStatus.CLOSED.value:
        raise CaseClosed(f"Case {case.case_number} is closed: reopen the case first")
    if exception.tenant_id != case.tenant_id:
        raise ValueError("The exception belongs to another hospital")
    if exception.status != ExceptionStatus.NEW.value:
        raise ValueError("Only NEW exceptions can be added to a case")
    link = AuditCaseException(tenant_id=case.tenant_id, case_id=case.id, exception_id=exception.id,
                              created_by=actor_id)
    db.add(link)
    exception.status = ExceptionStatus.IN_CASE.value
    db.flush()
    _log(db, case, actor_id, "case.exception_added", exception_id=str(exception.id))
    return link


def assign_case(db: Session, case: AuditCase, assignee_id: uuid.UUID, actor_id: uuid.UUID | None) -> AuditCase:
    """Assign (or reassign) a case. The first assignment moves it from OPEN to ASSIGNED."""
    if case.status == CaseStatus.CLOSED.value:
        raise CaseClosed(f"Case {case.case_number} is closed: reopen the case first")
    previous = case.assigned_to
    if case.status == CaseStatus.OPEN.value:
        ensure_transition(case.status, CaseStatus.ASSIGNED)
        case.status = CaseStatus.ASSIGNED.value
    case.assigned_to = assignee_id
    case.updated_by = actor_id
    db.flush()
    _log(db, case, actor_id, "case.assigned",
         **{"from": str(previous) if previous else None, "to": str(assignee_id)})
    if assignee_id != previous:                               # reassigning to the same person: no message
        notify_user(db, case.tenant_id, assignee_id, "case.assigned",
                    f"Case {case.case_number} assigned to you", case.title, CASE_ENTITY, case.id)
    return case


def _ensure_nothing_open(db: Session, case: AuditCase) -> None:
    """Refuse to close while findings or corrective actions of the case still need work."""
    findings = db.scalar(select(func.count()).select_from(AuditFinding).where(
        AuditFinding.case_id == case.id, AuditFinding.is_deleted.is_(False),
        AuditFinding.status.in_(sorted(FINDING_OPEN_STATUSES)),
    ))
    actions = db.scalar(select(func.count()).select_from(CorrectiveAction).where(
        CorrectiveAction.case_id == case.id, CorrectiveAction.is_deleted.is_(False),
        CorrectiveAction.status.in_(sorted(ACTION_OPEN_STATUSES)),
    ))
    parts = [f"{n} {word}{'s' if n != 1 else ''}" for n, word in ((findings, "finding"), (actions, "action")) if n]
    if parts:
        raise FindingsStillOpen(f"{' / '.join(parts)} still open")


def change_status(
    db: Session, case: AuditCase, target: str, actor_id: uuid.UUID | None,
    actor_roles: Iterable[str], reason: str | None = None,
) -> AuditCase:
    """Move a case to a new status, following the state machine and the approval rules."""
    target = CaseStatus(target)
    current = case.status
    ensure_transition(current, target)                       # raises InvalidTransition
    reason = reason.strip() if reason else None
    is_manager = has_permission(actor_roles, MANAGER_PERMISSION)

    if target == CaseStatus.NO_ISSUE:
        if not reason:
            raise ReasonRequired("A reason is required to close a case as NO_ISSUE")
        if case.priority == Severity.CRITICAL.value and not is_manager:
            raise ManagerApprovalRequired("Only an Audit Manager can dismiss a CRITICAL case as NO_ISSUE")
        case.closure_reason = reason
    if target == CaseStatus.CLOSED:
        if case.priority in NEEDS_MANAGER_TO_CLOSE and not is_manager:
            raise ManagerApprovalRequired("Only an Audit Manager can close a HIGH or CRITICAL case")
        _ensure_nothing_open(db, case)
        case.closed_at = _now()
    if target == CaseStatus.REOPENED:
        case.closed_at = None
        case.closure_reason = None                           # the audit log keeps the earlier reason

    case.status = target.value
    case.updated_by = actor_id
    db.flush()
    _log(db, case, actor_id, "case.status_changed", **{"from": current, "to": target.value, "reason": reason})
    return case


UPDATABLE_FIELDS = frozenset({"title", "priority", "is_restricted", "department_id"})


def update_case(db: Session, case: AuditCase, actor_id: uuid.UUID | None, changes: dict) -> AuditCase:
    """Change a case's title, priority, restriction or department. Logs only fields that really changed.

    `changes` holds only the fields the caller sent; department_id=None clears the department.
    """
    unknown = set(changes) - UPDATABLE_FIELDS
    if unknown:
        raise ValueError(f"These fields cannot be changed: {sorted(unknown)}")
    if changes.get("priority") is not None:
        Severity(changes["priority"])                         # ValueError for an unknown priority
    if "title" in changes and not (changes["title"] or "").strip():
        raise ValueError("The title cannot be empty")

    changed = {}
    for field, new in changes.items():
        if field in ("title", "priority", "is_restricted") and new is None:
            continue                                          # only department_id may be cleared
        old = getattr(case, field)
        if new != old:
            setattr(case, field, new)
            changed[field] = {"from": str(old) if isinstance(old, uuid.UUID) else old,
                              "to": str(new) if isinstance(new, uuid.UUID) else new}
    if changed:
        case.updated_by = actor_id
        db.flush()
        _log(db, case, actor_id, "case.updated", **changed)
    return case


def add_comment(db: Session, case: AuditCase, author_id: uuid.UUID, body: str) -> AuditCaseComment:
    """Add an internal comment. The log records that a comment was added, not its text."""
    body = (body or "").strip()
    if not body:
        raise ValueError("A comment cannot be empty")
    comment = AuditCaseComment(tenant_id=case.tenant_id, case_id=case.id, author_id=author_id,
                               body=body, created_by=author_id)
    db.add(comment)
    db.flush()
    _log(db, case, author_id, "case.commented", comment_id=str(comment.id))
    return comment


def get_case(db: Session, tenant_id: uuid.UUID, case_id: uuid.UUID) -> AuditCase | None:
    """The case, or None if it does not exist, is deleted, or belongs to another hospital."""
    case = db.get(AuditCase, case_id)
    if case is None or case.tenant_id != tenant_id or case.is_deleted:
        return None
    return case


def list_cases(
    db: Session, tenant_id: uuid.UUID, *, status: str | None = None, domain: str | None = None,
    priority: str | None = None, assigned_to: uuid.UUID | None = None, open_only: bool = False,
    visibility: ColumnElement[bool] | None = None,
) -> list[AuditCase]:
    """This hospital's cases, newest first, with optional filters.

    visibility: an extra condition limiting which cases the caller may see (built by the API).
    """
    stmt = select(AuditCase).where(AuditCase.tenant_id == tenant_id, AuditCase.is_deleted.is_(False))
    if visibility is not None:
        stmt = stmt.where(visibility)
    if priority:
        stmt = stmt.where(AuditCase.priority == priority)
    if status:
        stmt = stmt.where(AuditCase.status == status)
    if domain:
        stmt = stmt.where(AuditCase.domain == domain)
    if assigned_to:
        stmt = stmt.where(AuditCase.assigned_to == assigned_to)
    if open_only:
        stmt = stmt.where(AuditCase.status.in_(sorted(OPEN_STATUSES)))
    # opened_at can tie inside one transaction; the case number breaks the tie (same year).
    return list(db.scalars(stmt.order_by(AuditCase.opened_at.desc(), AuditCase.case_number.desc())))


def case_comments(db: Session, case: AuditCase) -> list[AuditCaseComment]:
    """The case's comments, oldest first."""
    return list(db.scalars(
        select(AuditCaseComment).where(
            AuditCaseComment.case_id == case.id, AuditCaseComment.tenant_id == case.tenant_id,
            AuditCaseComment.is_deleted.is_(False),
        ).order_by(AuditCaseComment.created_at, AuditCaseComment.id)
    ))


def case_timeline(db: Session, case: AuditCase) -> list[AuditLog]:
    """Everything that happened to the case, oldest first (from the audit log)."""
    return list_for_entity(db, case.tenant_id, CASE_ENTITY, case.id)


def case_exceptions(db: Session, case: AuditCase) -> list[AuditException]:
    """The exceptions linked to this case."""
    return list(db.scalars(
        select(AuditException)
        .join(AuditCaseException, AuditCaseException.exception_id == AuditException.id)
        .where(AuditCaseException.case_id == case.id, AuditCaseException.tenant_id == case.tenant_id)
        .order_by(AuditCaseException.added_at)
    ))
