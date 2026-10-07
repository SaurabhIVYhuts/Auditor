"""Exception service (AUD-013): save each rule hit once, and only once.

dedup_key = rule + record + rule version. Running the same rule version on the same record
again never creates a second exception (architecture test T-02). A new rule version is a
new finding, so it gets a new key. Does NOT commit: the caller does.
"""
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agents.audit.models import AuditException, AuditRule, ExceptionSource

DEDUP_CONSTRAINT = "uq_audit_exceptions_dedup_key"


def make_dedup_key(rule_id: uuid.UUID, entity_id: uuid.UUID, rule_version: int) -> str:
    return f"{rule_id}:{entity_id}:v{rule_version}"


def _find(db: Session, dedup_key: str) -> AuditException | None:
    return db.scalar(select(AuditException).where(AuditException.dedup_key == dedup_key))


def record_rule_exception(
    db: Session, *, rule: AuditRule, entity_type: str, entity_id: uuid.UUID,
    source_record_id: uuid.UUID, details: dict[str, Any],
) -> tuple[AuditException, bool]:
    """Save an exception for a rule hit. Returns (exception, created).

    created is False when this rule version had already flagged this record.
    """
    key = make_dedup_key(rule.id, entity_id, rule.current_version)
    existing = _find(db, key)
    if existing is not None:
        return existing, False
    try:
        # Savepoint: if another worker saved the same key a moment ago, undo only this part.
        with db.begin_nested():
            exception = AuditException(
                tenant_id=rule.tenant_id, source=ExceptionSource.RULE.value,
                rule_id=rule.id, rule_version=rule.current_version, severity=rule.severity,
                entity_type=entity_type, entity_id=entity_id,
                source_record_id=source_record_id, details=details, dedup_key=key,
            )
            db.add(exception)
            db.flush()
    except IntegrityError as err:
        if DEDUP_CONSTRAINT not in str(err.orig):
            raise                                  # a different database problem: never hide it
        return _find(db, key), False
    return exception, True
