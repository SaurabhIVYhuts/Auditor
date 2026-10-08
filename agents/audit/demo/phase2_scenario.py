"""Phase 2 exit scenario: "Rules produce exceptions from procurement events".

Sends a fixed sequence of procurement events through the real consumer. With the procurement
pack ACTIVE and po_high_value_limit = 100000, each step triggers the rules noted below.
Event and record IDs are derived from the hospital (uuid5), so running it again reports every
event as "duplicate" and creates nothing. Development/test data only. Does NOT commit.
"""
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.audit.events.envelope import EventEnvelope
from agents.audit.events.procurement_event_consumer import handle_procurement_event
from agents.audit.events.procurement_reader import PROCUREMENT_EVENTS
from agents.audit.models import AuditException, AuditRule
from agents.audit.rules.procurement_pack import PACK

_NAMESPACE = uuid.UUID("6f1d2c1e-0000-4000-8000-000000000002")   # for repeatable demo IDs

APPROVED = [{"level": 1, "approver_id": "U-DEMO-APPROVER"}]

# (step, event_type, document number, record data). Expected rule hits are in the comments.
# POs that are not part of the split-purchase demo use their own vendor, so PRC-SPL-01
# only sees the three V-DEMO orders.
STEPS: list[tuple[str, str, str, dict[str, Any]]] = [
    # a) high-value PO without the required approval -> PRC-APR-01
    ("a", "procurement.po.approved", "PO-DEMO-1",
     {"po_number": "PO-DEMO-1", "vendor_id": "V-DEMO-A", "grand_total": 150000, "status": "APPROVED",
      "required_approval_level": 2, "approvals": []}),
    # b) three 40000 POs to the same vendor -> PRC-SPL-01 on the third only (120000 > 100000)
    ("b1", "procurement.po.approved", "PO-DEMO-2",
     {"po_number": "PO-DEMO-2", "vendor_id": "V-DEMO", "grand_total": 40000, "status": "APPROVED",
      "required_approval_level": 1, "approvals": APPROVED}),
    ("b2", "procurement.po.approved", "PO-DEMO-3",
     {"po_number": "PO-DEMO-3", "vendor_id": "V-DEMO", "grand_total": 40000, "status": "APPROVED",
      "required_approval_level": 1, "approvals": APPROVED}),
    ("b3", "procurement.po.approved", "PO-DEMO-4",
     {"po_number": "PO-DEMO-4", "vendor_id": "V-DEMO", "grand_total": 40000, "status": "APPROVED",
      "required_approval_level": 1, "approvals": APPROVED}),
    # c) an issued (approved) PO and its goods receipt -> nothing
    ("c1", "procurement.po.issued", "PO-DEMO-5",
     {"po_number": "PO-DEMO-5", "vendor_id": "V-DEMO-B", "grand_total": 50000, "status": "ISSUED",
      "required_approval_level": 1, "approvals": APPROVED}),
    ("c2", "procurement.grn.posted", "GRN-DEMO-5",
     {"grn_number": "GRN-DEMO-5", "po_number": "PO-DEMO-5", "received_qty": 10, "posted_at": "2026-10-05"}),
    # d) invoice above the PO, dated before the GRN, not matched
    #    -> PRC-INVPO-01, PRC-INVGRN-01, PRC-MATCH-01
    ("d", "procurement.invoice.exception", "INV-DEMO-5",
     {"invoice_number": "INV-DEMO-5", "po_number": "PO-DEMO-5", "vendor_id": "V-DEMO-B", "amount": 60000,
      "invoice_date": "2026-10-01", "match_status": "PARTIAL"}),
    # e) payment above the invoice -> PRC-PAYINV-01
    ("e", "procurement.payment.status_changed", "PAY-DEMO-5",
     {"payment_ref": "PAY-DEMO-5", "invoice_number": "INV-DEMO-5", "amount": 70000, "status": "PAID"}),
    # f) vendor bank details changed -> PRC-VBANK-01
    ("f", "procurement.vendor.bank_changed", "V-DEMO",
     {"vendor_id": "V-DEMO", "status": "ACTIVE", "bank_changed": True}),
    # g) clean PO -> nothing
    ("g", "procurement.po.approved", "PO-DEMO-6",
     {"po_number": "PO-DEMO-6", "vendor_id": "V-DEMO-C", "grand_total": 20000, "status": "APPROVED",
      "required_approval_level": 1, "approvals": APPROVED}),
]


def _demo_id(tenant_id: uuid.UUID, name: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"{tenant_id}:{name}")


class ScenarioReader:
    """Procurement reader that returns the scenario's records (same interface as the other readers)."""

    def __init__(self, records: dict[tuple[str, uuid.UUID], dict[str, Any]]):
        self.records = records

    def get_record(self, tenant_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID) -> dict[str, Any]:
        record = self.records.get((entity_type, entity_id))
        if record is None:
            raise LookupError(f"No scenario record for {entity_type} {entity_id}")
        return {"id": str(entity_id), **record}


def run_phase2_scenario(db: Session, tenant_id: uuid.UUID) -> dict[str, int]:
    """Send the scenario events in order. Returns exceptions created in THIS run, per pack rule code."""
    records: dict[tuple[str, uuid.UUID], dict[str, Any]] = {}
    events: list[EventEnvelope] = []
    for step, event_type, number, data in STEPS:
        entity_type = PROCUREMENT_EVENTS[event_type]
        entity_id = _demo_id(tenant_id, f"{entity_type}:{number}")
        records[(entity_type, entity_id)] = data
        events.append(EventEnvelope.model_validate({
            "event_id": str(_demo_id(tenant_id, f"step:{step}")),
            "event_type": event_type,
            "version": 1,
            "occurred_at": "2026-10-08T10:00:00+05:30",
            "tenant_id": str(tenant_id),
            "actor": {"type": "system"},
            "entity": {"type": entity_type, "id": str(entity_id), "number": number},
        }))

    reader = ScenarioReader(records)
    new_snapshot_ids = []
    for event in events:
        result = handle_procurement_event(db, event, reader)
        if result.status == "processed":
            new_snapshot_ids.append(result.source_record_id)

    created = {rule["rule_code"]: 0 for rule in PACK}
    if new_snapshot_ids:
        rows = db.execute(
            select(AuditRule.rule_code)
            .join(AuditException, AuditException.rule_id == AuditRule.id)
            .where(AuditException.source_record_id.in_(new_snapshot_ids))
        ).scalars()
        for code in rows:
            created[code] = created.get(code, 0) + 1
    return created
