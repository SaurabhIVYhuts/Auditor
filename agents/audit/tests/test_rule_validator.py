"""Tests for the rule DSL validator (AUD-011, architecture test T-04)."""
import pytest

from agents.audit.rules.validator import RuleValidationError, ensure_valid, validate_definition

# The example rule from the architecture document (PRC-APR-01).
VALID = {
    "trigger": {"type": "EVENT", "events": ["procurement.po.issued"], "batch_cron": "0 2 * * *"},
    "condition": {"all": [
        {"field": "po.grand_total", "op": ">", "value_ref": "config.po_high_value_limit"},
        {"fn": "approval_missing", "args": {"entity": "po", "min_level": "po.required_approval_level"}},
    ]},
    "action": {"type": "CREATE_EXCEPTION", "group_by": ["vendor_id"], "group_window_days": 7},
    "evidence_capture": ["po", "approvals", "audit_trail"],
}


def with_condition(condition):
    return {**VALID, "condition": condition}


BAD_RULES = [
    ("unknown_field", with_condition({"field": "po.secret_salary", "op": ">", "value": 1}), "unknown field"),
    ("unknown_function", with_condition({"fn": "run_sql", "args": {}}), "unknown function"),
    ("unknown_operator", with_condition({"field": "po.grand_total", "op": "~~", "value": 1}), "unknown operator"),
    ("hidden_extra_key", with_condition({"field": "po.grand_total", "op": ">", "value": 1, "sql": "DROP"}), "not allowed"),
    ("value_ref_not_config", with_condition({"field": "po.grand_total", "op": ">", "value_ref": "os.environ"}), "value_ref"),
    ("number_function_without_operator",
     with_condition({"fn": "days_between", "args": {"from": "grn.posted_at", "to": "invoice.invoice_date"}}), "operator"),
    ("unknown_event", {**VALID, "trigger": {"type": "EVENT", "events": ["procurement.po.deleted"]}}, "unknown event"),
    ("unsafe_action", {**VALID, "action": {"type": "DELETE_PO"}}, "action.type"),
]


def test_architecture_example_rule_is_valid():
    assert validate_definition(VALID) == []


@pytest.mark.parametrize("name,definition,expected", BAD_RULES, ids=[b[0] for b in BAD_RULES])
def test_bad_rules_are_rejected_with_a_clear_reason(name, definition, expected):
    errors = validate_definition(definition)
    assert errors, f"{name} should be rejected"
    assert expected in " ".join(errors)


def test_number_function_with_operator_is_valid():
    rule = with_condition({"fn": "days_between",
                           "args": {"from": "grn.posted_at", "to": "invoice.invoice_date"},
                           "op": ">", "value": 30})
    assert validate_definition(rule) == []


def test_too_deeply_nested_condition_is_rejected():
    condition = {"field": "po.grand_total", "op": ">", "value": 1}
    for _ in range(15):
        condition = {"not": condition}
    assert "too deep" in " ".join(validate_definition(with_condition(condition)))


def test_ensure_valid_reports_every_problem_at_once():
    bad = {**VALID, "trigger": {"type": "SOMETIMES"}, "action": {"type": "DELETE_PO"}}
    with pytest.raises(RuleValidationError) as caught:
        ensure_valid(bad)
    assert len(caught.value.errors) == 2
