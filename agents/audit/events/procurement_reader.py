"""Reading procurement records for audit (read-only).

PROCUREMENT_EVENTS lists the procurement events the Auditor listens to
(architecture section 7, "Consumed event") and which record each is about.

ProcurementReader is the interface. Today we use MockProcurementReader, because
the Procurement Agent's read API is not live yet. Later a real reader will call
GET /procurement/... with a read-only service token. Readers only READ —
the Auditor never writes to source systems.
"""
import uuid
from typing import Any, Protocol

PROCUREMENT_EVENTS: dict[str, str] = {
    "procurement.po.approved": "purchase_order",
    "procurement.po.issued": "purchase_order",
    "procurement.po.amended": "purchase_order",
    "procurement.grn.posted": "grn",
    "procurement.invoice.matched": "invoice",
    "procurement.invoice.exception": "invoice",
    "procurement.payment.status_changed": "payment",
    "procurement.vendor.bank_changed": "vendor",
}


class ProcurementReader(Protocol):
    def get_record(self, tenant_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID) -> dict[str, Any]:
        """Return the full current record. Raise LookupError if it does not exist."""
        ...


class MockProcurementReader:
    """Returns fake but realistic records. For development and tests only."""

    def get_record(self, tenant_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID) -> dict[str, Any]:
        base = {"id": str(entity_id), "tenant_id": str(tenant_id), "mock": True}
        if entity_type == "purchase_order":
            return {**base, "po_number": "PO-MOCK-00001", "vendor_id": "V-MOCK-001",
                    "grand_total": 150000, "status": "APPROVED",
                    "approvals": [{"level": 1, "approver_id": "U-MOCK-7"}]}
        if entity_type == "grn":
            return {**base, "grn_number": "GRN-MOCK-00001", "po_number": "PO-MOCK-00001",
                    "received_qty": 10, "posted_by": "U-MOCK-9"}
        if entity_type == "invoice":
            return {**base, "invoice_number": "INV-MOCK-00001", "po_number": "PO-MOCK-00001",
                    "amount": 150000, "match_status": "MATCHED"}
        if entity_type == "payment":
            return {**base, "payment_ref": "PAY-MOCK-00001", "invoice_number": "INV-MOCK-00001",
                    "amount": 150000, "status": "PAID"}
        if entity_type == "vendor":
            return {**base, "vendor_id": "V-MOCK-001", "status": "ACTIVE", "bank_changed": True}
        raise LookupError(f"Unknown procurement entity type: {entity_type!r}")
