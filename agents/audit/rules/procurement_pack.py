"""Seed procurement rule pack (AUD-014): 11 starter rules for the first audit domain.

Rules are data in the safe DSL. Money limits come from audit_config (po_high_value_limit),
never from the rule itself; day windows are part of the rule. Wording is neutral: these
rules raise exceptions for an auditor to review, they do not conclude anything.
"""
from typing import Any

PO_EVENTS = ["procurement.po.approved", "procurement.po.issued", "procurement.po.amended"]
INVOICE_EVENTS = ["procurement.invoice.matched", "procurement.invoice.exception"]
PAYMENT_EVENTS = ["procurement.payment.status_changed"]
VENDOR_EVENTS = ["procurement.vendor.bank_changed"]

ABOVE_LIMIT = {"op": ">", "value_ref": "config.po_high_value_limit"}
CREATE_EXCEPTION = {"type": "CREATE_EXCEPTION"}


def _rule(code: str, name: str, severity: str, events: list[str], condition: dict[str, Any],
          evidence: list[str]) -> dict[str, Any]:
    return {
        "rule_code": code,
        "name": name,
        "domain": "PROCUREMENT",
        "severity": severity,
        "definition": {
            "trigger": {"type": "EVENT", "events": events},
            "condition": condition,
            "action": CREATE_EXCEPTION,
            "evidence_capture": evidence,
        },
    }


PACK: list[dict[str, Any]] = [
    _rule("PRC-APR-01", "High-value PO without required approval", "HIGH", PO_EVENTS,
          {"all": [
              {"field": "po.grand_total", **ABOVE_LIMIT},
              {"fn": "approval_missing", "args": {"entity": "po", "min_level": "po.required_approval_level"}},
          ]},
          ["po", "approvals"]),
    _rule("PRC-SPL-01", "Possible split purchase: same vendor over the limit within 30 days", "HIGH", PO_EVENTS,
          {"all": [
              {"fn": "sum_over_window",
               "args": {"field": "po.grand_total", "group_by": "po.vendor_id", "window_days": 30},
               **ABOVE_LIMIT},
              {"field": "po.grand_total", "op": "<=", "value_ref": "config.po_high_value_limit"},
          ]},
          ["po"]),
    _rule("PRC-DUPINV-01", "Invoice with same vendor and amount within 90 days", "HIGH", INVOICE_EVENTS,
          {"fn": "duplicate_of",
           "args": {"entity": "invoice", "match_fields": ["invoice.vendor_id", "invoice.amount"],
                    "window_days": 90}},
          ["invoice"]),
    _rule("PRC-INVNO-01", "Invoice number repeated for the same vendor within a year", "CRITICAL", INVOICE_EVENTS,
          {"fn": "duplicate_of",
           "args": {"entity": "invoice", "match_fields": ["invoice.vendor_id", "invoice.invoice_number"],
                    "window_days": 365}},
          ["invoice"]),
    _rule("PRC-INVPO-01", "Invoice amount above PO total", "HIGH", INVOICE_EVENTS,
          {"field": "invoice.amount", "op": ">", "value_field": "po.grand_total"},
          ["invoice", "po"]),
    _rule("PRC-PAYINV-01", "Payment amount above invoice amount", "CRITICAL", PAYMENT_EVENTS,
          {"field": "payment.amount", "op": ">", "value_field": "invoice.amount"},
          ["payment", "invoice"]),
    _rule("PRC-DUPPAY-01", "Repeat payment for the same invoice and amount within a year", "CRITICAL", PAYMENT_EVENTS,
          {"fn": "duplicate_of",
           "args": {"entity": "payment", "match_fields": ["payment.invoice_number", "payment.amount"],
                    "window_days": 365}},
          ["payment", "invoice"]),
    _rule("PRC-INVGRN-01", "Invoice dated before goods were received", "MEDIUM", INVOICE_EVENTS,
          {"fn": "days_between", "args": {"from": "grn.posted_at", "to": "invoice.invoice_date"},
           "op": "<", "value": 0},
          ["invoice", "grn"]),
    _rule("PRC-MATCH-01", "Invoice not matched to PO and GRN", "MEDIUM", INVOICE_EVENTS,
          {"field": "invoice.match_status", "op": "!=", "value": "MATCHED"},
          ["invoice", "po", "grn"]),
    _rule("PRC-VBANK-01", "Vendor bank details changed", "HIGH", VENDOR_EVENTS,
          {"field": "vendor.bank_changed", "op": "=", "value": True},
          ["vendor"]),
    _rule("PRC-PAYPO-01", "Payment against a PO that was never approved", "HIGH", PAYMENT_EVENTS,
          {"all": [
              {"field": "po.status", "op": "!=", "value": "APPROVED"},
              {"field": "po.status", "op": "!=", "value": "ISSUED"},     # issued and closed POs
              {"field": "po.status", "op": "!=", "value": "CLOSED"},     # were approved earlier
          ]},
          ["payment", "invoice", "po"]),
]
