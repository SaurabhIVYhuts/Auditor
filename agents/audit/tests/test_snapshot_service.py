"""Tests for the snapshot service (Audit Data Hub)."""
import uuid

import pytest

from agents.audit.models import AuditSourceRecord
from agents.audit.services.snapshot_service import (
    capture_snapshot,
    compute_checksum,
    verify_snapshot,
)

PO_DATA = {
    "po_number": "PO-2026-00042",
    "vendor_id": "V-001",
    "grand_total": 250000,
    "approvals": [{"level": 1, "approver": "U-7"}],
}


def _capture(db, data=None, source_system="procurement"):
    return capture_snapshot(
        db,
        tenant_id=uuid.uuid4(),
        source_system=source_system,
        entity_type="purchase_order",
        entity_id=uuid.uuid4(),
        data=PO_DATA if data is None else data,
    )


def test_checksum_ignores_key_order():
    assert compute_checksum({"a": 1, "b": 2}) == compute_checksum({"b": 2, "a": 1})


def test_checksum_changes_when_any_value_changes():
    changed = {**PO_DATA, "grand_total": 250001}
    assert compute_checksum(PO_DATA) != compute_checksum(changed)


def test_capture_saves_snapshot_that_verifies_after_reload(db_session):
    record = _capture(db_session)
    record_id = record.id

    db_session.expire_all()  # forget cached objects, force a real read from PostgreSQL
    loaded = db_session.get(AuditSourceRecord, record_id)

    assert len(loaded.checksum) == 64
    assert loaded.snapshot["po_number"] == "PO-2026-00042"
    assert verify_snapshot(loaded) is True


def test_tampered_snapshot_is_detected(db_session):
    record = _capture(db_session)
    record.snapshot = {**record.snapshot, "grand_total": 1}  # simulate tampering
    assert verify_snapshot(record) is False


def test_snapshot_is_independent_copy_of_input(db_session):
    data = {"po_number": "PO-2026-00043", "lines": [{"qty": 5}]}
    record = _capture(db_session, data=data)
    data["lines"][0]["qty"] = 999  # the source changes after capture
    assert record.snapshot["lines"][0]["qty"] == 5
    assert verify_snapshot(record) is True


def test_unknown_source_system_is_rejected(db_session):
    with pytest.raises(ValueError):
        _capture(db_session, source_system="procurment")  # typo on purpose


def test_empty_data_is_rejected(db_session):
    with pytest.raises(ValueError):
        _capture(db_session, data={})
