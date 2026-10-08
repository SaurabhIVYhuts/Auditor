"""Tests for comparing two fields (value_field), e.g. invoice amount vs PO total."""
from agents.audit.rules.evaluator import EvaluationContext, evaluate_condition
from agents.audit.rules.validator import validate_definition
from agents.audit.tests.test_rule_validator import VALID

INVOICE_OVER_PO = {"field": "invoice.amount", "op": ">", "value_field": "po.grand_total"}


def run(facts):
    return evaluate_condition(INVOICE_OVER_PO, EvaluationContext(facts=facts, get_config=lambda k: None))


def test_value_field_rule_is_valid():
    assert validate_definition({**VALID, "condition": INVOICE_OVER_PO}) == []


def test_value_field_must_be_whitelisted_and_alone():
    unknown = {"field": "invoice.amount", "op": ">", "value_field": "po.secret"}
    mixed = {**INVOICE_OVER_PO, "value": 5}
    for condition in (unknown, mixed):
        assert validate_definition({**VALID, "condition": condition})


def test_invoice_above_po_total_is_flagged():
    assert run({"invoice": {"amount": 120000}, "po": {"grand_total": 100000}}).matched is True


def test_invoice_within_po_total_is_not_flagged():
    assert run({"invoice": {"amount": 90000}, "po": {"grand_total": 100000}}).matched is False


def test_missing_linked_po_is_unknown_with_warning():
    result = run({"invoice": {"amount": 120000}})
    assert result.outcome is None and result.warnings
