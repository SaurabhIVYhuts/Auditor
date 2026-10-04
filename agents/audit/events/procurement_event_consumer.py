"""Procurement event consumer (task AUD-004).

Turns a procurement event into a snapshot in the Audit Data Hub:
event -> check type -> skip if already handled -> fetch full record (read-only)
-> save snapshot with checksum -> remember the event as handled.

Does NOT commit: the caller commits, so the snapshot and the "handled" mark
are saved together or not at all. If fetching fails, the error is raised and
nothing is saved, so the event can be retried later.
"""
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.audit.events.envelope import EventEnvelope
from agents.audit.events.procurement_reader import PROCUREMENT_EVENTS, ProcurementReader
from agents.audit.models import AuditProcessedEvent
from agents.audit.services.snapshot_service import capture_snapshot


@dataclass(frozen=True)
class ConsumeResult:
    status: Literal["processed", "duplicate", "ignored"]
    source_record_id: uuid.UUID | None = None


def handle_procurement_event(
    db: Session, envelope: EventEnvelope, reader: ProcurementReader
) -> ConsumeResult:
    entity_type = PROCUREMENT_EVENTS.get(envelope.event_type)
    if entity_type is None:
        return ConsumeResult("ignored")

    already_handled = db.scalar(
        select(AuditProcessedEvent.id).where(AuditProcessedEvent.event_id == envelope.event_id)
    )
    if already_handled is not None:
        return ConsumeResult("duplicate")

    if envelope.entity.type != entity_type:
        raise ValueError(
            f"Event {envelope.event_type} must be about {entity_type!r}, got {envelope.entity.type!r}"
        )

    record = reader.get_record(envelope.tenant_id, entity_type, envelope.entity.id)

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
    return ConsumeResult("processed", snapshot.id)
