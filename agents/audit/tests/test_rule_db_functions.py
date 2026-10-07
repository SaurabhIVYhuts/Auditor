"""Tests for the database rule functions duplicate_of and sum_over_window (AUD-011)."""
import uuid
from datetime import datetime, timedelta, timezone

from agents.audit.rules.db_functions import make_db_functions
from agents.audit.rules.evaluator import EvaluationContext, evaluate_condition
from agents.audit.services.snapshot_service import capture_snapshot

DUPLICATE_INVOICE = {"fn": "duplicate_of", "args": {
    "entity": "invoice", "match_fields": ["invoice.vendor_id", "invoice.amount"], "window_days": 30}}
SPLIT_PURCHASE = {"fn": "sum_over_window", "op": ">", "value_ref": "config.po_high_value_limit",
                  "args": {"field": "po.grand_total", "group_by": "po.vendor_id", "window_days": 30}}


def save(db, tenant, entity_type, data, entity_id=None, days_ago=0):
    record = capture_snapshot(db, tenant_id=tenant, source_system="procurement",
                              entity_type=entity_type, entity_id=entity_id or uuid.uuid4(), data=data)
    if days_ago:
        record.captured_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
        db.flush()
    return record


def check(db, tenant, current, prefix, condition):
    ctx = EvaluationContext(
        facts={prefix: current.snapshot},
        get_config=lambda key: 100000,
        functions=make_db_functions(db, tenant_id=tenant, current_entity_id=current.entity_id),
    )
    return evaluate_condition(condition, ctx)


def invoice(vendor, amount=150000):
    return {"invoice_number": f"INV-{uuid.uuid4().hex[:6]}", "vendor_id": vendor, "amount": amount}


def ids():
    return uuid.uuid4(), f"V-{uuid.uuid4().hex[:6]}"


def test_duplicate_invoice_is_flagged(db_session):
    tenant, vendor = ids()
    save(db_session, tenant, "invoice", invoice(vendor))
    current = save(db_session, tenant, "invoice", invoice(vendor))
    assert check(db_session, tenant, current, "invoice", DUPLICATE_INVOICE).matched is True


def test_different_amount_is_not_a_duplicate(db_session):
    tenant, vendor = ids()
    save(db_session, tenant, "invoice", invoice(vendor, 99000))
    current = save(db_session, tenant, "invoice", invoice(vendor))
    assert check(db_session, tenant, current, "invoice", DUPLICATE_INVOICE).matched is False


def test_other_hospitals_invoice_is_never_a_duplicate(db_session):
    tenant, vendor = ids()
    save(db_session, uuid.uuid4(), "invoice", invoice(vendor))
    current = save(db_session, tenant, "invoice", invoice(vendor))
    assert check(db_session, tenant, current, "invoice", DUPLICATE_INVOICE).matched is False


def test_duplicate_outside_the_window_is_not_flagged(db_session):
    tenant, vendor = ids()
    save(db_session, tenant, "invoice", invoice(vendor), days_ago=60)
    current = save(db_session, tenant, "invoice", invoice(vendor))
    assert check(db_session, tenant, current, "invoice", DUPLICATE_INVOICE).matched is False


def test_corrected_invoice_uses_its_latest_version(db_session):
    tenant, vendor = ids()
    other_id = uuid.uuid4()
    save(db_session, tenant, "invoice", invoice(vendor), entity_id=other_id, days_ago=1)  # old version
    save(db_session, tenant, "invoice", invoice(vendor, 999), entity_id=other_id)         # corrected
    current = save(db_session, tenant, "invoice", invoice(vendor))
    assert check(db_session, tenant, current, "invoice", DUPLICATE_INVOICE).matched is False


def test_split_purchase_over_limit_is_flagged(db_session):
    tenant, vendor = ids()
    for _ in range(2):
        save(db_session, tenant, "purchase_order", {"vendor_id": vendor, "grand_total": 40000})
    save(db_session, tenant, "purchase_order", {"vendor_id": "OTHER-VENDOR", "grand_total": 90000})
    current = save(db_session, tenant, "purchase_order", {"vendor_id": vendor, "grand_total": 40000})
    result = check(db_session, tenant, current, "po", SPLIT_PURCHASE)
    assert result.matched is True
    assert {"check": "sum_over_window()", "op": ">", "value": 120000, "outcome": True} in result.details


def test_missing_match_field_is_unknown_with_warning(db_session):
    tenant, _ = ids()
    current = save(db_session, tenant, "invoice", {"invoice_number": "INV-X", "amount": 1})
    result = check(db_session, tenant, current, "invoice", DUPLICATE_INVOICE)
    assert result.outcome is None and result.warnings
