"""Tests for the event envelope and the mock procurement reader."""
import uuid

import pytest
from pydantic import ValidationError

from agents.audit.events.envelope import EventEnvelope
from agents.audit.events.procurement_reader import PROCUREMENT_EVENTS, MockProcurementReader


def sample_event(**overrides) -> dict:
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "procurement.po.approved",
        "version": 1,
        "occurred_at": "2026-10-01T08:30:00Z",
        "tenant_id": str(uuid.uuid4()),
        "actor": {"type": "user", "id": str(uuid.uuid4())},
        "entity": {"type": "purchase_order", "id": str(uuid.uuid4()), "number": "PO-2026-00042"},
        "data": {"grand_total": 150000},
        "correlation_id": str(uuid.uuid4()),
    }
    event.update(overrides)
    return event


def test_valid_event_is_accepted():
    envelope = EventEnvelope.model_validate(sample_event())
    assert envelope.event_type == "procurement.po.approved"
    assert envelope.entity.number == "PO-2026-00042"


def test_unknown_extra_fields_are_ignored():
    envelope = EventEnvelope.model_validate(sample_event(new_field_from_producer="x"))
    assert not hasattr(envelope, "new_field_from_producer")


@pytest.mark.parametrize("missing", ["event_id", "tenant_id", "entity", "occurred_at"])
def test_event_missing_required_field_is_rejected(missing):
    event = sample_event()
    del event[missing]
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(event)


def test_timestamp_without_timezone_is_rejected():
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(sample_event(occurred_at="2026-10-01T08:30:00"))


def test_every_listed_event_maps_to_a_readable_record():
    reader = MockProcurementReader()
    tenant_id, entity_id = uuid.uuid4(), uuid.uuid4()
    for event_type, entity_type in PROCUREMENT_EVENTS.items():
        record = reader.get_record(tenant_id, entity_type, entity_id)
        assert record["id"] == str(entity_id), event_type


def test_mock_reader_rejects_unknown_entity_type():
    with pytest.raises(LookupError):
        MockProcurementReader().get_record(uuid.uuid4(), "spaceship", uuid.uuid4())
