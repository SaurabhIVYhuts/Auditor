"""Procurement event consumer (task AUD-004).

Turns a procurement event into a snapshot in the Audit Data Hub:
event -> check type -> skip if already handled -> fetch full record (read-only)
-> save snapshot with checksum -> remember the event as handled -> run ACTIVE rules.

Does NOT commit: the caller commits, so the snapshot and the "handled" mark
are saved together or not at all. If fetching fails, the error is raised and
nothing is saved, so the event can be retried later.
"""
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agents.audit.events.envelope import EventEnvelope
from agents.audit.events.procurement_reader import PROCUREMENT_EVENTS, ProcurementReader
from agents.audit.models import AuditProcessedEvent
from agents.audit.services.snapshot_service import capture_snapshot
from agents.audit.services.rule_engine import run_rules_for_event

# Name of the UNIQUE constraint on audit_processed_events.event_id.
EVENT_ID_UNIQUE_CONSTRAINT = "uq_audit_processed_events_event_id"


@dataclass(frozen=True)
class ConsumeResult:
    status: Literal["processed", "duplicate", "ignored"]
    source_record_id: uuid.UUID | None = None
    exceptions_created: int = 0


def _already_handled(db: Session, event_id: uuid.UUID) -> bool:
    found = db.scalar(select(AuditProcessedEvent.id).where(AuditProcessedEvent.event_id == event_id))
    return found is not None


def handle_procurement_event(
    db: Session, envelope: EventEnvelope, reader: ProcurementReader
) -> ConsumeResult:
    entity_type = PROCUREMENT_EVENTS.get(envelope.event_type)
    if entity_type is None:
        return ConsumeResult("ignored")

    if _already_handled(db, envelope.event_id):
        return ConsumeResult("duplicate")

    if envelope.entity.type != entity_type:
        raise ValueError(
            f"Event {envelope.event_type} must be about {entity_type!r}, got {envelope.entity.type!r}"
        )

    record = reader.get_record(envelope.tenant_id, entity_type, envelope.entity.id)

    try:
        # Savepoint: if another worker saved this same event a moment ago, the UNIQUE
        # event_id rejects ours. We then undo only this part and report "duplicate".
        with db.begin_nested():
            snapshot = capture_snapshot(
                db,
                tenant_id=envelope.tenant_id,
                source_system="procurement",
                entity_type=entity_type,
                entity_id=envelope.entity.id,
                data=record,
            )
            db.add(
                AuditProcessedEvent(
                    tenant_id=envelope.tenant_id,
                    event_id=envelope.event_id,
                    event_type=envelope.event_type,
                    correlation_id=envelope.correlation_id,
                    source_record_id=snapshot.id,
                )
            )
            db.flush()
    except IntegrityError as exc:
        if EVENT_ID_UNIQUE_CONSTRAINT not in str(exc.orig):
            raise  # a different database problem: never hide it
        return ConsumeResult("duplicate")

    # Run every ACTIVE rule that listens to this event, in the same transaction as the snapshot.
    runs = run_rules_for_event(
        db, tenant_id=envelope.tenant_id, event_type=envelope.event_type, record=snapshot
    )
    return ConsumeResult(
        "processed", snapshot.id, exceptions_created=sum(r.exceptions_created for r in runs)
    )
