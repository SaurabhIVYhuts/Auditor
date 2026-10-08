"""Tests for the rule DSL evaluator (AUD-011, architecture test T-01)."""
import pytest

from agents.audit.rules.evaluator import EvaluationContext, RuleEvaluationError, evaluate_condition
from agents.audit.services.rule_registry import ConfigMissingError

PRC_APR_01 = {"all": [
    {"field": "po.grand_total", "op": ">", "value_ref": "config.po_high_value_limit"},
    {"fn": "approval_missing", "args": {"entity": "po", "min_level": "po.required_approval_level"}},
]}


def config(**values):
    def get(key):
        if key not in values:
            raise ConfigMissingError(key)
        return values[key]
    return get


def run(condition, facts):
    ctx = EvaluationContext(facts=facts, get_config=config(po_high_value_limit=100000))
    return evaluate_condition(condition, ctx)


def po(**overrides):
    record = {"grand_total": 200000, "required_approval_level": 2, "approvals": [{"level": 1}]}
    record.update(overrides)
    return {"po": record}


def test_t01_high_value_po_without_required_approval_is_flagged():
    result = run(PRC_APR_01, po())
    assert result.matched is True
    assert {"check": "po.grand_total", "op": ">", "value": 200000, "outcome": True} in result.details


def test_po_with_required_approval_is_not_flagged():
    assert run(PRC_APR_01, po(approvals=[{"level": 1}, {"level": 2}])).matched is False


def test_po_below_limit_is_not_flagged():
    assert run(PRC_APR_01, po(grand_total=50000)).matched is False


def test_missing_data_is_unknown_with_warning_not_a_silent_pass():
    result = run(PRC_APR_01, po(grand_total=None))
    assert result.outcome is None and result.matched is False and result.warnings


def test_not_of_unknown_stays_unknown():
    result = run({"not": {"field": "po.grand_total", "op": ">", "value": 1}}, {"po": {}})
    assert result.outcome is None and result.matched is False


def test_days_between_with_operator():
    facts = {"grn": {"posted_at": "2026-09-01"}, "invoice": {"invoice_date": "2026-10-15"}}
    cond = {"fn": "days_between", "args": {"from": "grn.posted_at", "to": "invoice.invoice_date"},
            "op": ">", "value": 30}
    assert run(cond, facts).matched is True


@pytest.mark.parametrize("condition", [
    {"field": "po.status", "op": "in", "value": ["APPROVED", "ISSUED"]},
    {"field": "po.grand_total", "op": "between", "value": [100000, 300000]},
    {"field": "po.po_number", "op": "matches", "value": "^PO-2026-"},
    {"field": "po.grand_total", "op": "=", "value": "200000"},
], ids=["in", "between", "matches", "numeric_text"])
def test_operators(condition):
    assert run(condition, po(status="APPROVED", po_number="PO-2026-00042")).matched is True


def test_wrong_type_is_unknown_with_warning():
    result = run({"field": "po.po_number", "op": ">", "value": 5}, po(po_number="PO-1"))
    assert result.outcome is None and result.warnings


def test_missing_config_value_fails_loudly():
    ctx = EvaluationContext(facts=po(), get_config=config())
    with pytest.raises(ConfigMissingError):
        evaluate_condition(PRC_APR_01, ctx)


def test_database_function_not_ready_fails_loudly():
    cond = {"fn": "duplicate_of", "args": {"entity": "po", "match_fields": ["po.vendor_id"], "window_days": 30}}
    with pytest.raises(RuleEvaluationError):
        run(cond, po())
