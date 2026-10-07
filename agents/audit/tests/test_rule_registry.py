"""Tests for the rule registry and config values (AUD-010)."""
import uuid

import pytest

from agents.audit.models import AuditRule
from agents.audit.services.rule_registry import (
    ConfigMissingError, create_rule, get_config_value, get_rule_version,
    save_new_version, set_config_value,
)

V1 = {"condition": {"field": "po.grand_total", "op": ">", "value_ref": "config.po_high_value_limit"}}
V2 = {"condition": {"field": "po.grand_total", "op": ">=", "value_ref": "config.po_high_value_limit"}}


def new_rule(db, **overrides):
    args = dict(tenant_id=uuid.uuid4(), rule_code="PRC-APR-01", name="High-value PO",
                domain="PROCUREMENT", severity="HIGH", definition=V1)
    args.update(overrides)
    return create_rule(db, **args)


def test_unique_constraint_names_include_all_columns():
    names = {c.name for c in AuditRule.__table__.constraints}
    assert "uq_audit_rules_tenant_id_rule_code" in names


def test_create_rule_is_draft_v1_with_history(db_session):
    rule = new_rule(db_session)
    assert (rule.status, rule.current_version) == ("DRAFT", 1)
    assert get_rule_version(db_session, rule.id, 1).definition == V1


def test_edit_creates_new_version_and_keeps_old_one(db_session):
    rule = new_rule(db_session)
    save_new_version(db_session, rule, definition=V2, change_note="use >=")
    assert rule.current_version == 2 and rule.definition == V2
    assert get_rule_version(db_session, rule.id, 1).definition == V1
    assert get_rule_version(db_session, rule.id, 2).definition == V2


@pytest.mark.parametrize("field,value", [("domain", "SPACE"), ("severity", "EXTREME")])
def test_unknown_domain_or_severity_is_rejected(db_session, field, value):
    with pytest.raises(ValueError):
        new_rule(db_session, **{field: value})


def test_config_value_set_get_and_update(db_session):
    h = uuid.uuid4()
    set_config_value(db_session, tenant_id=h, key="po_high_value_limit", value=100000)
    assert get_config_value(db_session, h, "po_high_value_limit") == 100000
    set_config_value(db_session, tenant_id=h, key="po_high_value_limit", value=150000)
    assert get_config_value(db_session, h, "po_high_value_limit") == 150000


def test_missing_config_is_an_error_not_a_silent_pass(db_session):
    with pytest.raises(ConfigMissingError):
        get_config_value(db_session, uuid.uuid4(), "po_high_value_limit")


def test_config_is_per_hospital(db_session):
    set_config_value(db_session, tenant_id=uuid.uuid4(), key="po_high_value_limit", value=1)
    with pytest.raises(ConfigMissingError):
        get_config_value(db_session, uuid.uuid4(), "po_high_value_limit")
