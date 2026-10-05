"""Tests for the procurement event consumer (AUD-004)."""
import uuid

import pytest
from sqlalchemy import func, select

from agents.audit.events.envelope import EventEnvelope
from agents.audit.events.procurement_event_consumer import handle_procurement_event
from agents.audit.events.procurement_reader import PROCUREMENT_EVENTS, MockProcurementReader
from agents.audit.models import AuditProcessedEvent, AuditSourceRecord
from agents.audit.services.snapshot_service import verify_snapshot

READER = MockProcurementReader()


def make_event(event_type="procurement.po.approved", entity_type="purchase_order", entity_id=None):
    return EventEnvelope.model_validate({
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "version": 1,
        "occurred_at": "2026-10-01T08:30:00Z",
        "tenant_id": str(uuid.uuid4()),
        "actor": {"type": "user", "id": str(uuid.uuid4())},
        "entity": {"type": entity_type, "id": str(entity_id or uuid.uuid4())},
        "correlation_id": str(uuid.uuid4()),
    })


def count_snapshots(db, entity_id):
    return db.scalar(
        select(func.count()).select_from(AuditSourceRecord).where(AuditSourceRecord.entity_id == entity_id)
    )


class FailingReader:
    def get_record(self, tenant_id, entity_type, entity_id):
        raise LookupError("record not found in procurement")


def test_processed_events_table_has_unique_event_id():
    assert AuditProcessedEvent.__table__.c.event_id.unique is True
    assert AuditProcessedEvent.__table__.schema == "audit"


def test_event_becomes_verified_snapshot(db_session):
    event = make_event()
    result = handle_procurement_event(db_session, event, READER)

    assert result.status == "processed"
    snapshot = db_session.get(AuditSourceRecord, result.source_record_id)
    assert snapshot.source_system == "procurement"
    assert snapshot.entity_type == "purchase_order"
    assert snapshot.entity_id == event.entity.id
    assert verify_snapshot(snapshot) is True


def test_same_event_twice_creates_only_one_snapshot(db_session):
    event = make_event()
    first = handle_procurement_event(db_session, event, READER)
    second = handle_procurement_event(db_session, event, READER)

    assert first.status == "processed"
    assert second.status == "duplicate"
    assert count_snapshots(db_session, event.entity.id) == 1


def test_non_procurement_event_is_ignored(db_session):
    event = make_event(event_type="insurance.claim.settled", entity_type="claim")
    result = handle_procurement_event(db_session, event, READER)
    assert result.status == "ignored"
    assert count_snapshots(db_session, event.entity.id) == 0


def test_event_with_wrong_entity_type_is_rejected(db_session):
    event = make_event(event_type="procurement.po.approved", entity_type="invoice")
    with pytest.raises(ValueError):
        handle_procurement_event(db_session, event, READER)
    assert count_snapshots(db_session, event.entity.id) == 0


def test_failed_fetch_saves_nothing_so_event_can_be_retried(db_session):
    event = make_event()
    with pytest.raises(LookupError):
        handle_procurement_event(db_session, event, FailingReader())
    assert count_snapshots(db_session, event.entity.id) == 0


def test_every_listed_procurement_event_is_processed(db_session):
    for event_type, entity_type in PROCUREMENT_EVENTS.items():
        result = handle_procurement_event(db_session, make_event(event_type, entity_type), READER)
        assert result.status == "processed", event_type


def test_simultaneous_duplicate_is_reported_not_crashed(db_session, monkeypatch):
    event = make_event()
    first = handle_procurement_event(db_session, event, READER)  # "another worker" saves it
    assert first.status == "processed"

    # This worker's check ran before that save was visible (a real race condition).
    monkeypatch.setattr(
        "agents.audit.events.procurement_event_consumer._already_handled",
        lambda db, event_id: False,
    )
    second = handle_procurement_event(db_session, event, READER)

    assert second.status == "duplicate"
    assert count_snapshots(db_session, event.entity.id) == 1  # the extra snapshot was undone
