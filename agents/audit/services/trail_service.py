"""Procurement trail builder (task AUD-005).

Builds READ-ONLY views from snapshots in the Audit Data Hub:
- Record history: every snapshot of one record (e.g. a PO before and after amendment).
- PO chain: the PO plus its GRNs and invoices (linked by po_number) and the
  payments for those invoices (linked by invoice_number), in P2P order.

Always filtered by tenant, so one hospital never sees another's data.
Each entry reports whether its checksum still matches (tamper check).
"""
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from agents.audit.models import AuditSourceRecord
from agents.audit.services.snapshot_service import verify_snapshot

# Procure-to-Pay order used to sort the chain.
CHAIN_ORDER = ("purchase_order", "grn", "invoice", "payment")


@dataclass(frozen=True)
class TrailEntry:
    source_record_id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    captured_at: datetime
    checksum_ok: bool
    snapshot: dict[str, Any]


def _to_entry(record: AuditSourceRecord) -> TrailEntry:
    return TrailEntry(
        source_record_id=record.id,
        entity_type=record.entity_type,
        entity_id=record.entity_id,
        captured_at=record.captured_at,
        checksum_ok=verify_snapshot(record),
        snapshot=record.snapshot,
    )


def _procurement_snapshots(tenant_id: uuid.UUID) -> Select:
    return select(AuditSourceRecord).where(
        AuditSourceRecord.tenant_id == tenant_id,
        AuditSourceRecord.source_system == "procurement",
        AuditSourceRecord.is_deleted.is_(False),
    )


def get_record_history(
    db: Session, *, tenant_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID
) -> list[TrailEntry]:
    """Every snapshot of one procurement record, oldest first."""
    stmt = (
        _procurement_snapshots(tenant_id)
        .where(
            AuditSourceRecord.entity_type == entity_type,
            AuditSourceRecord.entity_id == entity_id,
        )
        .order_by(AuditSourceRecord.captured_at, AuditSourceRecord.created_at)
    )
    return [_to_entry(record) for record in db.scalars(stmt)]


def get_po_chain(db: Session, *, tenant_id: uuid.UUID, po_number: str) -> list[TrailEntry]:
    """The PO and its linked GRNs, invoices and payments, in P2P order."""
    snapshot = AuditSourceRecord.snapshot

    linked = db.scalars(
        _procurement_snapshots(tenant_id).where(
            AuditSourceRecord.entity_type.in_(("purchase_order", "grn", "invoice")),
            snapshot["po_number"].astext == po_number,
        )
    ).all()

    invoice_numbers = sorted(
        {r.snapshot.get("invoice_number") for r in linked if r.entity_type == "invoice"} - {None}
    )
    payments = []
    if invoice_numbers:
        payments = db.scalars(
            _procurement_snapshots(tenant_id).where(
                AuditSourceRecord.entity_type == "payment",
                snapshot["invoice_number"].astext.in_(invoice_numbers),
            )
        ).all()

    records = [*linked, *payments]
    records.sort(key=lambda r: (CHAIN_ORDER.index(r.entity_type), r.captured_at))
    return [_to_entry(record) for record in records]
