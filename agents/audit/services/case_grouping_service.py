"""Case grouping (AUD-021): every new rule exception goes into a case, automatically.

If the same rule already flagged the same record in a case that is still open and was opened
within the grouping window, the new exception joins that case. Otherwise a new case is opened.
A CLOSED case is never reused: a re-trigger after closure opens a new case.
Does NOT commit: the caller does.
"""
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.audit.cases.state_machine import CaseStatus
from agents.audit.models import (
    AuditCase, AuditCaseException, AuditEvidenceLink, AuditException, AuditRule, AuditSourceRecord,
    CaseSource, ExceptionStatus, LinkTarget,
)
from agents.audit.services.case_service import _now, add_exception_to_case, case_exceptions, open_case
from agents.audit.services.evidence_service import capture_for_case
from agents.audit.services.rule_registry import ConfigMissingError, get_config_value

GROUPING_WINDOW_KEY = "case_grouping_window_days"
# Used when a hospital has not set its own window; the architecture's example value is 7 days.
DEFAULT_GROUPING_WINDOW_DAYS = 7


def grouping_window_days(db: Session, tenant_id: uuid.UUID) -> int:
    try:
        return int(get_config_value(db, tenant_id, GROUPING_WINDOW_KEY))
    except ConfigMissingError:
        return DEFAULT_GROUPING_WINDOW_DAYS


def _open_case_with_same_finding(db: Session, exception: AuditException, window_days: int) -> AuditCase | None:
    """Newest not-CLOSED case of this hospital, opened within the window, that already holds
    an exception from the same rule on the same record."""
    return db.scalar(
        select(AuditCase)
        .join(AuditCaseException, AuditCaseException.case_id == AuditCase.id)
        .join(AuditException, AuditException.id == AuditCaseException.exception_id)
        .where(
            AuditCase.tenant_id == exception.tenant_id,
            AuditCase.is_deleted.is_(False),
            AuditCase.status != CaseStatus.CLOSED.value,
            AuditCase.opened_at >= _now() - timedelta(days=window_days),
            AuditException.rule_id == exception.rule_id,
            AuditException.entity_id == exception.entity_id,
        )
        .order_by(AuditCase.opened_at.desc())
        .limit(1)
    )


def _department_of(db: Session, exception: AuditException) -> uuid.UUID | None:
    snapshot = db.get(AuditSourceRecord, exception.source_record_id)
    value = snapshot.snapshot.get("department_id") if snapshot else None
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None                                           # not a valid id: leave the case unassigned to a department


def case_for_new_exception(db: Session, exception: AuditException, rule: AuditRule) -> tuple[AuditCase, bool]:
    """Put a new rule exception into a case, with the record's snapshot as evidence. Returns (case, created)."""
    window = grouping_window_days(db, exception.tenant_id)
    case = _open_case_with_same_finding(db, exception, window)
    created = case is None
    if case is not None:
        add_exception_to_case(db, case, exception, actor_id=None)
    else:
        case = open_case(
            db, exception.tenant_id, domain=rule.domain, title=rule.name, source=CaseSource.RULE.value,
            primary_entity_type=exception.entity_type, primary_entity_id=exception.entity_id,
            priority=rule.severity, actor_id=None, department_id=_department_of(db, exception),
            exception_ids=[exception.id],
        )
    capture_for_case(db, db.get(AuditSourceRecord, exception.source_record_id), case)
    return case, created


def backfill_cases(db: Session, tenant_id: uuid.UUID) -> dict[str, int]:
    """Put this hospital's NEW rule exceptions (made before grouping existed) into cases, oldest first.

    Exceptions without a rule (anomaly models, later) are skipped and counted. Safe to run again:
    grouped exceptions become IN_CASE, so a second run finds nothing to do.
    """
    new_exceptions = db.scalars(select(AuditException).where(
        AuditException.tenant_id == tenant_id,
        AuditException.status == ExceptionStatus.NEW.value,
        AuditException.is_deleted.is_(False),
    ).order_by(AuditException.created_at, AuditException.id)).all()

    counts = {"exceptions": 0, "cases_created": 0, "joined": 0, "skipped": 0}
    for exception in new_exceptions:
        if exception.rule_id is None:
            counts["skipped"] += 1
            continue
        _, created = case_for_new_exception(db, exception, db.get(AuditRule, exception.rule_id))
        counts["exceptions"] += 1
        counts["cases_created" if created else "joined"] += 1
    return counts


def backfill_case_evidence(db: Session, tenant_id: uuid.UUID) -> dict[str, int]:
    """Give every case that has no evidence yet the snapshot evidence of its exceptions' records.

    For cases opened before evidence capture existed. Cases without exceptions (manual) are left
    alone. Safe to run again: a case that already has evidence is skipped.
    """
    has_evidence = select(AuditEvidenceLink.id).where(
        AuditEvidenceLink.target_type == LinkTarget.CASE.value, AuditEvidenceLink.target_id == AuditCase.id,
    ).exists()
    cases = db.scalars(select(AuditCase).where(
        AuditCase.tenant_id == tenant_id, AuditCase.is_deleted.is_(False), ~has_evidence,
    ).order_by(AuditCase.case_number)).all()

    counts = {"cases_updated": 0, "evidence_linked": 0}
    for case in cases:
        records = {exc.source_record_id for exc in case_exceptions(db, case)}
        for record_id in sorted(records, key=str):
            capture_for_case(db, db.get(AuditSourceRecord, record_id), case)
            counts["evidence_linked"] += 1
        if records:
            counts["cases_updated"] += 1
    return counts
