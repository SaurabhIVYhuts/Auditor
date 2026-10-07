"""Tests for linked documents in rule facts (invoice -> PO/GRN, payment -> invoice -> PO)."""
import uuid
from datetime import datetime, timedelta, timezone

from agents.audit.events.envelope import EventEnvelope
from agents.audit.events.procurement_event_consumer import handle_procurement_event
from agents.audit.services.batch_runner import primary_entity_types
from agents.audit.services.rule_engine import build_facts
from agents.audit.services.snapshot_service import capture_snapshot
from agents.audit.tests.test_rule_engine import add_rule, exceptions_for, hospital, runs_for


def save(db, tenant, entity_type, data, entity_id=None, days_ago=0):
    rec = capture_snapshot(db, tenant_id=tenant, source_system="procurement",
                           entity_type=entity_type, entity_id=entity_id or uuid.uuid4(), data=data)
    if days_ago:
        rec.captured_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
        db.flush()
    return rec


def test_invoice_sees_its_po_and_grn(db_session):
    t = uuid.uuid4()
    save(db_session, t, "purchase_order", {"po_number": "PO-L1", "grand_total": 100000})
    save(db_session, t, "grn", {"grn_number": "GRN-L1", "po_number": "PO-L1"})
    inv = save(db_session, t, "invoice", {"invoice_number": "INV-L1", "po_number": "PO-L1", "amount": 1})
    facts = build_facts(db_session, inv)
    assert facts["po"]["grand_total"] == 100000 and facts["grn"]["grn_number"] == "GRN-L1"


def test_invoice_rule_is_about_invoices_only():
    rule = {"trigger": {"type": "EVENT", "events": ["procurement.invoice.matched"]},
            "condition": {"field": "invoice.amount", "op": ">", "value_field": "po.grand_total"}}
    assert primary_entity_types(rule) == {"invoice"}


def test_payment_sees_invoice_and_its_po(db_session):
    t = uuid.uuid4()
    save(db_session, t, "purchase_order", {"po_number": "PO-L1", "grand_total": 100000})
    save(db_session, t, "invoice", {"invoice_number": "INV-L1", "po_number": "PO-L1", "amount": 90000})
    pay = save(db_session, t, "payment", {"invoice_number": "INV-L1", "amount": 90000})
    facts = build_facts(db_session, pay)
    assert {"payment", "invoice", "po"} <= set(facts) and facts["po"]["po_number"] == "PO-L1"


def test_other_hospitals_po_is_never_linked(db_session):
    hospital_a, hospital_b = uuid.uuid4(), uuid.uuid4()
    save(db_session, hospital_b, "purchase_order", {"po_number": "PO-L2", "grand_total": 100000})
    inv = save(db_session, hospital_a, "invoice", {"invoice_number": "INV-L2", "po_number": "PO-L2", "amount": 1})
    assert "po" not in build_facts(db_session, inv)


def test_latest_po_version_is_used(db_session):
    t, po_id = uuid.uuid4(), uuid.uuid4()
    save(db_session, t, "purchase_order", {"po_number": "PO-L3", "grand_total": 50000}, entity_id=po_id, days_ago=1)
    save(db_session, t, "purchase_order", {"po_number": "PO-L3", "grand_total": 80000}, entity_id=po_id)
    inv = save(db_session, t, "invoice", {"invoice_number": "INV-L3", "po_number": "PO-L3", "amount": 1})
    assert build_facts(db_session, inv)["po"]["grand_total"] == 80000


INVOICE_OVER_PO_RULE = {
    "trigger": {"type": "EVENT", "events": ["procurement.invoice.matched"]},
    "condition": {"field": "invoice.amount", "op": ">", "value_field": "po.grand_total"},
    "action": {"type": "CREATE_EXCEPTION"},
}


class InvoiceReader:
    """Mock procurement reader that returns an invoice we control."""

    def get_record(self, tenant_id, entity_type, entity_id):
        return {"id": str(entity_id), "invoice_number": "INV-E2E", "po_number": "PO-E2E", "amount": 120000}


def test_invoice_over_po_creates_exception_end_to_end(db_session):
    tenant = hospital(db_session)
    rule = add_rule(db_session, tenant, definition=INVOICE_OVER_PO_RULE)
    save(db_session, tenant, "purchase_order", {"po_number": "PO-E2E", "grand_total": 100000})
    event = EventEnvelope.model_validate({
        "event_id": str(uuid.uuid4()), "event_type": "procurement.invoice.matched", "version": 1,
        "occurred_at": "2026-10-08T10:00:00+05:30", "tenant_id": str(tenant),
        "actor": {"type": "system"}, "entity": {"type": "invoice", "id": str(uuid.uuid4())},
    })
    result = handle_procurement_event(db_session, event, InvoiceReader())
    [run] = runs_for(db_session, rule)
    assert result.exceptions_created == 1 and run.status == "SUCCEEDED"
    assert len(exceptions_for(db_session, rule)) == 1
