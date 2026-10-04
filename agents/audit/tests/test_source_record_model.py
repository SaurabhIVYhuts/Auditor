"""Tests for the Audit Data Hub table (audit_source_records)."""
import uuid

from agents.audit.models import AuditSourceRecord
from shared.db import SessionLocal

COMMON_COLUMNS = {"id", "tenant_id", "created_at", "created_by", "updated_at", "updated_by", "is_deleted"}


def test_table_has_common_columns_and_audit_schema():
    columns = set(AuditSourceRecord.__table__.columns.keys())
    assert COMMON_COLUMNS <= columns
    assert AuditSourceRecord.__table__.schema == "audit"


def test_can_save_and_read_a_snapshot():
    # Needs the local PostgreSQL and the migration applied (alembic upgrade head).
    db = SessionLocal()
    try:
        record = AuditSourceRecord(
            tenant_id=uuid.uuid4(),
            source_system="procurement",
            entity_type="purchase_order",
            entity_id=uuid.uuid4(),
            snapshot={"po_number": "PO-2026-00001", "grand_total": 250000},
            checksum="0" * 64,
        )
        db.add(record)
        db.flush()           # send to the database (inside the open transaction)
        db.refresh(record)   # read back values the database filled in

        assert record.id is not None
        assert record.is_deleted is False
        assert record.created_at is not None
        assert record.captured_at is not None

        loaded = db.get(AuditSourceRecord, record.id)
        assert loaded.snapshot["grand_total"] == 250000
    finally:
        db.rollback()        # undo everything: no test data is left behind
        db.close()
