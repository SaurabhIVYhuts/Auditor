"""Behaviour tests for every procurement pack rule (AUD-014): one flagged and one clean case each.

Runs the real engine path: snapshots saved in the database, linked documents found by
build_facts, database functions from make_db_functions, limit read from audit_config.
The answer must be a definite True or False, never "unknown".
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from agents.audit.rules.procurement_pack import PACK
from agents.audit.services.rule_engine import evaluate_rule_on_record
from agents.audit.services.rule_registry import create_rule, set_config_value
from agents.audit.services.snapshot_service import capture_snapshot

RULES = {rule["rule_code"]: rule for rule in PACK}


def save(db, tenant, entity_type, data, entity_id=None, days_ago=0):
    rec = capture_snapshot(db, tenant_id=tenant, source_system="procurement",
                           entity_type=entity_type, entity_id=entity_id or uuid.uuid4(), data=data)
    if days_ago:
        rec.captured_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
        db.flush()
    return rec


# Each case: (rule_code, expected answer, earlier snapshots [(type, data, days_ago)], record checked (type, data))
CASES = [
    ("PRC-APR-01", True, [],
     ("purchase_order", {"po_number": "PO-1", "grand_total": 150000, "required_approval_level": 2,
                         "approvals": []})),
    ("PRC-APR-01", False, [],
     ("purchase_order", {"po_number": "PO-1", "grand_total": 150000, "required_approval_level": 2,
                         "approvals": [{"level": 1}, {"level": 2}]})),

    ("PRC-SPL-01", True,
     [("purchase_order", {"po_number": "PO-A", "vendor_id": "V-1", "grand_total": 40000}, 5),
      ("purchase_order", {"po_number": "PO-B", "vendor_id": "V-1", "grand_total": 40000}, 10)],
     ("purchase_order", {"po_number": "PO-C", "vendor_id": "V-1", "grand_total": 40000})),
    ("PRC-SPL-01", False, [],
     ("purchase_order", {"po_number": "PO-C", "vendor_id": "V-1", "grand_total": 40000})),

    ("PRC-DUPINV-01", True,
     [("invoice", {"invoice_number": "INV-1", "vendor_id": "V-1", "amount": 75000}, 10)],
     ("invoice", {"invoice_number": "INV-2", "vendor_id": "V-1", "amount": 75000})),
    ("PRC-DUPINV-01", False,
     [("invoice", {"invoice_number": "INV-1", "vendor_id": "V-1", "amount": 60000}, 10)],
     ("invoice", {"invoice_number": "INV-2", "vendor_id": "V-1", "amount": 75000})),

    ("PRC-INVNO-01", True,
     [("invoice", {"invoice_number": "INV-7", "vendor_id": "V-1", "amount": 10000}, 30)],
     ("invoice", {"invoice_number": "INV-7", "vendor_id": "V-1", "amount": 20000})),
    ("PRC-INVNO-01", False,
     [("invoice", {"invoice_number": "INV-7", "vendor_id": "V-1", "amount": 10000}, 30)],
     ("invoice", {"invoice_number": "INV-8", "vendor_id": "V-1", "amount": 20000})),

    ("PRC-INVPO-01", True,
     [("purchase_order", {"po_number": "PO-9", "grand_total": 100000}, 1)],
     ("invoice", {"invoice_number": "INV-9", "po_number": "PO-9", "amount": 120000})),
    ("PRC-INVPO-01", False,
     [("purchase_order", {"po_number": "PO-9", "grand_total": 100000}, 1)],
     ("invoice", {"invoice_number": "INV-9", "po_number": "PO-9", "amount": 90000})),

    ("PRC-PAYINV-01", True,
     [("invoice", {"invoice_number": "INV-5", "amount": 50000}, 1)],
     ("payment", {"payment_ref": "PAY-5", "invoice_number": "INV-5", "amount": 60000})),
    ("PRC-PAYINV-01", False,
     [("invoice", {"invoice_number": "INV-5", "amount": 50000}, 1)],
     ("payment", {"payment_ref": "PAY-5", "invoice_number": "INV-5", "amount": 50000})),

    ("PRC-DUPPAY-01", True,
     [("payment", {"payment_ref": "PAY-1", "invoice_number": "INV-3", "amount": 30000}, 3)],
     ("payment", {"payment_ref": "PAY-2", "invoice_number": "INV-3", "amount": 30000})),
    ("PRC-DUPPAY-01", False, [],
     ("payment", {"payment_ref": "PAY-2", "invoice_number": "INV-3", "amount": 30000})),

    ("PRC-INVGRN-01", True,
     [("grn", {"grn_number": "GRN-4", "po_number": "PO-4", "posted_at": "2026-10-05"}, 1)],
     ("invoice", {"invoice_number": "INV-4", "po_number": "PO-4", "invoice_date": "2026-10-01"})),
    ("PRC-INVGRN-01", False,
     [("grn", {"grn_number": "GRN-4", "po_number": "PO-4", "posted_at": "2026-10-05"}, 1)],
     ("invoice", {"invoice_number": "INV-4", "po_number": "PO-4", "invoice_date": "2026-10-10"})),

    ("PRC-MATCH-01", True, [],
     ("invoice", {"invoice_number": "INV-6", "match_status": "PARTIAL"})),
    ("PRC-MATCH-01", False, [],
     ("invoice", {"invoice_number": "INV-6", "match_status": "MATCHED"})),

    ("PRC-VBANK-01", True, [],
     ("vendor", {"vendor_id": "V-1", "status": "ACTIVE", "bank_changed": True})),
    ("PRC-VBANK-01", False, [],
     ("vendor", {"vendor_id": "V-1", "status": "ACTIVE", "bank_changed": False})),

    ("PRC-PAYPO-01", True,
     [("purchase_order", {"po_number": "PO-8", "status": "DRAFT"}, 2),
      ("invoice", {"invoice_number": "INV-8", "po_number": "PO-8", "amount": 1000}, 1)],
     ("payment", {"payment_ref": "PAY-8", "invoice_number": "INV-8", "amount": 1000})),
    ("PRC-PAYPO-01", False,
     [("purchase_order", {"po_number": "PO-8", "status": "ISSUED"}, 2),
      ("invoice", {"invoice_number": "INV-8", "po_number": "PO-8", "amount": 1000}, 1)],
     ("payment", {"payment_ref": "PAY-8", "invoice_number": "INV-8", "amount": 1000})),
]


@pytest.mark.parametrize(
    "code,expected,earlier,current", CASES,
    ids=[f"{c[0]}-{'flag' if c[1] else 'clean'}" for c in CASES],
)
def test_pack_rule_behaviour(db_session, code, expected, earlier, current):
    tenant = uuid.uuid4()
    set_config_value(db_session, tenant_id=tenant, key="po_high_value_limit", value=100000)
    pack_rule = RULES[code]
    rule = create_rule(db_session, tenant_id=tenant, rule_code=code, name=pack_rule["name"],
                       domain=pack_rule["domain"], severity=pack_rule["severity"],
                       definition=pack_rule["definition"])
    for entity_type, data, days_ago in earlier:
        save(db_session, tenant, entity_type, data, days_ago=days_ago)
    record = save(db_session, tenant, *current)

    result = evaluate_rule_on_record(db_session, rule, record)

    assert result.outcome is expected, f"{code}: outcome={result.outcome} warnings={result.warnings}"
    assert result.matched is expected
