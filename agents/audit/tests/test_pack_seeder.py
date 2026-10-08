"""Tests for seeding the procurement rule pack into a hospital (AUD-014)."""
import uuid

from sqlalchemy import select

from agents.audit.models import AuditRule
from agents.audit.rules.procurement_pack import PACK
from agents.audit.services.pack_seeder import seed_procurement_pack
from agents.audit.services.rule_registry import get_config_value, save_new_version, set_config_value


def rules_of(db, tenant):
    return db.scalars(select(AuditRule).where(AuditRule.tenant_id == tenant)).all()


def test_seed_creates_11_draft_rules_and_default_limit(db_session):
    tenant = uuid.uuid4()
    result = seed_procurement_pack(db_session, tenant, created_by=uuid.uuid4())
    rules = rules_of(db_session, tenant)
    assert result == {"created": 11, "skipped": 0, "config_set": True}
    assert len(rules) == 11 and all(r.status == "DRAFT" for r in rules)
    assert get_config_value(db_session, tenant, "po_high_value_limit") == 100000


def test_seed_twice_creates_nothing_new(db_session):
    tenant = uuid.uuid4()
    seed_procurement_pack(db_session, tenant, created_by=None)
    second = seed_procurement_pack(db_session, tenant, created_by=None)
    assert second == {"created": 0, "skipped": 11, "config_set": False}
    assert len(rules_of(db_session, tenant)) == 11


def test_seed_keeps_hospital_edits(db_session):
    tenant = uuid.uuid4()
    seed_procurement_pack(db_session, tenant, created_by=None)
    rule = next(r for r in rules_of(db_session, tenant) if r.rule_code == "PRC-APR-01")
    save_new_version(db_session, rule, definition=PACK[0]["definition"], change_note="hospital edit")
    seed_procurement_pack(db_session, tenant, created_by=None)
    assert rule.current_version == 2


def test_seed_keeps_existing_limit(db_session):
    tenant = uuid.uuid4()
    set_config_value(db_session, tenant_id=tenant, key="po_high_value_limit", value=500000)
    result = seed_procurement_pack(db_session, tenant, created_by=None)
    assert result["config_set"] is False
    assert get_config_value(db_session, tenant, "po_high_value_limit") == 500000


def test_seed_does_not_touch_other_hospital(db_session):
    hospital_a, hospital_b = uuid.uuid4(), uuid.uuid4()
    seed_procurement_pack(db_session, hospital_a, created_by=None)
    assert rules_of(db_session, hospital_b) == []
