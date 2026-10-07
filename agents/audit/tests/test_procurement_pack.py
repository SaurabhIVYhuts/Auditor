"""Tests for the seed procurement rule pack (AUD-014)."""
import re

import pytest

from agents.audit.rules.procurement_pack import PACK
from agents.audit.rules.validator import validate_definition
from agents.audit.schemas.rule import RULE_CODE_PATTERN

MONEY_FIELDS = {"po.grand_total", "invoice.amount", "payment.amount"}


def _nodes(node):
    """Every condition node in a rule, including nested all / any / not."""
    yield node
    for key in ("all", "any"):
        for child in node.get(key, []):
            yield from _nodes(child)
    if "not" in node:
        yield from _nodes(node["not"])


@pytest.mark.parametrize("rule", PACK, ids=[r["rule_code"] for r in PACK])
def test_every_pack_rule_is_valid(rule):
    assert validate_definition(rule["definition"]) == []


def test_pack_has_11_rules_with_unique_codes():
    codes = [r["rule_code"] for r in PACK]
    assert len(codes) == 11 and len(set(codes)) == 11


def test_codes_match_the_api_pattern():
    assert all(re.match(RULE_CODE_PATTERN, r["rule_code"]) for r in PACK)


def test_money_limits_come_from_config_or_another_field():
    for rule in PACK:
        for node in _nodes(rule["definition"]["condition"]):
            is_money = node.get("field") in MONEY_FIELDS or node.get("fn") == "sum_over_window"
            assert not (is_money and "value" in node), f"{rule['rule_code']} hard-codes a money value"
