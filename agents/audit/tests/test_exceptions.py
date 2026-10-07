"""Tests for exceptions with dedup and rule runs (AUD-013, architecture test T-02)."""
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from agents.audit.models import AuditException, AuditRuleRun
from agents.audit.services import exception_service
from agents.audit.services.exception_service import record_rule_exception
from agents.audit.services.rule_registry import create_rule, save_new_version
from agents.audit.services.snapshot_service import capture_snapshot

DEFINITION = {"trigger": {"type": "EVENT", "events": ["procurement.po.issued"]},
              "condition": {"field": "po.grand_total", "op": ">", "value_ref": "config.po_high_value_limit"},
              "action": {"type": "CREATE_EXCEPTION"}}
DETAILS = {"checks": [{"check": "po.grand_total", "op": ">", "value": 200000, "outcome": True}]}


def setup(db):
    tenant = uuid.uuid4()
    rule = create_rule(db, tenant_id=tenant, rule_code="PRC-APR-01", name="High-value PO",
                       domain="PROCUREMENT", severity="HIGH", definition=DEFINITION)
    snap = capture_snapshot(db, tenant_id=tenant, source_system="procurement",
                            entity_type="purchase_order", entity_id=uuid.uuid4(),
                            data={"grand_total": 200000})
    return rule, snap


def flag(db, rule, snap):
    return record_rule_exception(db, rule=rule, entity_type=snap.entity_type, entity_id=snap.entity_id,
                                 source_record_id=snap.id, details=DETAILS)


def count(db, rule):
    return db.scalar(select(func.count()).select_from(AuditException)
                     .where(AuditException.rule_id == rule.id))


def test_exception_remembers_rule_version_severity_and_details(db_session):
    rule, snap = setup(db_session)
    exc, created = flag(db_session, rule, snap)
    assert created is True
    assert (exc.rule_version, exc.severity, exc.status, exc.source) == (1, "HIGH", "NEW", "RULE")
    assert exc.details == DETAILS


def test_t02_same_rule_version_same_record_is_not_duplicated(db_session):
    rule, snap = setup(db_session)
    first, created_first = flag(db_session, rule, snap)
    second, created_second = flag(db_session, rule, snap)
    assert created_first is True and created_second is False
    assert first.id == second.id and count(db_session, rule) == 1


def test_new_rule_version_is_a_new_finding(db_session):
    rule, snap = setup(db_session)
    flag(db_session, rule, snap)
    save_new_version(db_session, rule, definition=DEFINITION, change_note="tightened")
    exc, created = flag(db_session, rule, snap)
    assert created is True and exc.rule_version == 2 and count(db_session, rule) == 2


def test_simultaneous_duplicate_is_reported_not_crashed(db_session, monkeypatch):
    rule, snap = setup(db_session)
    flag(db_session, rule, snap)                       # "another worker" saved it
    real_find, calls = exception_service._find, []

    def miss_first_check(db, key):                     # our first check ran before that save was visible
        calls.append(key)
        return None if len(calls) == 1 else real_find(db, key)

    monkeypatch.setattr(exception_service, "_find", miss_first_check)
    exc, created = flag(db_session, rule, snap)
    assert created is False and exc is not None and count(db_session, rule) == 1


def test_database_requires_a_rule_for_rule_exceptions(db_session):
    rule, snap = setup(db_session)
    db_session.add(AuditException(
        tenant_id=rule.tenant_id, source="RULE", rule_id=None, severity="HIGH",
        entity_type="purchase_order", entity_id=snap.entity_id, source_record_id=snap.id,
        details={}, dedup_key=f"manual-{uuid.uuid4()}"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_rule_run_defaults(db_session):
    rule, _ = setup(db_session)
    run = AuditRuleRun(tenant_id=rule.tenant_id, rule_id=rule.id, rule_version=1, trigger_type="EVENT")
    db_session.add(run)
    db_session.flush()
    db_session.refresh(run)
    assert (run.status, run.records_checked, run.warnings) == ("RUNNING", 0, [])
    assert run.started_at is not None
