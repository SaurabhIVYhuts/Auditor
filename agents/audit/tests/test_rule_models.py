"""Tests for the rule tables (AUD-010)."""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from agents.audit.models import AuditConfig, AuditRule, AuditRuleVersion

COMMON = {"id", "tenant_id", "created_at", "created_by", "updated_at", "updated_by", "is_deleted"}


def make_rule(tenant_id, code="PRC-TEST-01", severity="HIGH"):
    return AuditRule(
        tenant_id=tenant_id, rule_code=code, name="Test rule", domain="PROCUREMENT",
        severity=severity, definition={"condition": {"all": []}},
    )


def test_rule_tables_are_in_audit_schema_with_common_columns():
    for model in (AuditRule, AuditRuleVersion, AuditConfig):
        assert model.__table__.schema == "audit"
        assert COMMON <= set(model.__table__.columns.keys())


def test_new_rule_starts_as_draft_version_1(db_session):
    rule = make_rule(uuid.uuid4())
    db_session.add(rule)
    db_session.flush()
    db_session.refresh(rule)
    assert rule.status == "DRAFT"
    assert rule.current_version == 1


def test_database_rejects_unknown_severity(db_session):
    db_session.add(make_rule(uuid.uuid4(), severity="EXTREME"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_rule_code_is_unique_per_hospital_only(db_session):
    hospital_a, hospital_b = uuid.uuid4(), uuid.uuid4()
    db_session.add_all([make_rule(hospital_a), make_rule(hospital_b)])  # same code, different hospitals: OK
    db_session.flush()
    db_session.add(make_rule(hospital_a))                               # same code, same hospital: rejected
    with pytest.raises(IntegrityError):
        db_session.flush()
