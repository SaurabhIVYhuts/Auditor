"""Audit Data Hub: frozen, read-only snapshots of records from source systems.

The Auditor never changes source data. It saves a copy (snapshot) of each record
it audits, with a SHA-256 checksum, so evidence stays reliable even if the
original record is edited later.
"""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agents.audit.models.base import AuditBase
from shared.models import CommonColumns


class AuditSourceRecord(CommonColumns, AuditBase):
    __tablename__ = "audit_source_records"
    __table_args__ = (
        # Fast lookup of every snapshot of one record, in time order (trail view).
        Index(
            "ix_audit_source_records_trail",
            "source_system",
            "entity_type",
            "entity_id",
            "captured_at",
        ),
    )

    source_system: Mapped[str] = mapped_column(String(40))   # e.g. procurement, insurance, erp, his
    entity_type: Mapped[str] = mapped_column(String(60))     # e.g. purchase_order, invoice, grn
    entity_id: Mapped[uuid.UUID]                              # the record's ID in the source system
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)   # full copy of the record at capture time
    checksum: Mapped[str] = mapped_column(String(64))         # SHA-256 of the snapshot (tamper check)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
