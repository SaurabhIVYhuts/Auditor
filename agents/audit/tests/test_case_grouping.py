"""Tests for automatic case grouping (AUD-021): new exception -> new or existing case."""
import uuid
from datetime import timedelta

from agents.audit.events.procurement_event_consumer import handle_procurement_event
from agents.audit.services.case_grouping_service import backfill_cases, case_for_new_exception
from agents.audit.services.case_service import _now, case_exceptions, list_cases
from agents.audit.services.exception_service import record_rule_exception
from agents.audit.services.rule_registry import create_rule, save_new_version
from agents.audit.services.snapshot_service import capture_snapshot
from agents.audit.tests.test_rule_engine import PRC_APR_01, PoReader, add_rule, hospital, make_event


def rule_for(db, tenant, code="PRC-APR-01", severity="HIGH"):
    return create_rule(db, tenant_id=tenant, rule_code=code, name=f"Rule {code}",
                       domain="PROCUREMENT", severity=severity, definition=PRC_APR_01)


def snapshot_for(db, tenant, entity_id, data=None):
    return capture_snapshot(db, tenant_id=tenant, source_system="procurement", entity_type="purchase_order",
                            entity_id=entity_id, data=data or {"po_number": "PO-G1", "grand_total": 200000})


def old_exception(db, rule, entity_id):
    """A NEW exception that was never grouped (like those made before grouping existed)."""
    snap = snapshot_for(db, rule.tenant_id, entity_id)
    exception, created = record_rule_exception(db, rule=rule, entity_type="purchase_order", entity_id=entity_id,
                                               source_record_id=snap.id, details={})
    assert created
    return exception


def flag(db, rule, entity_id):
    """Record a NEW exception for this rule version on this record, then group it."""
    exception = old_exception(db, rule, entity_id)
    return exception, case_for_new_exception(db, exception, rule)


def test_new_exception_opens_a_case(db_session):
    rule = rule_for(db_session, uuid.uuid4(), severity="CRITICAL")
    exception, (case, created) = flag(db_session, rule, uuid.uuid4())
    assert created is True
    assert (case.status, case.priority, case.source, case.title) == ("OPEN", "CRITICAL", "RULE", rule.name)
    assert (case.primary_entity_id, exception.status) == (exception.entity_id, "IN_CASE")


def test_same_rule_same_record_within_window_joins_the_same_case(db_session):
    rule, po = rule_for(db_session, uuid.uuid4()), uuid.uuid4()
    _, (first, _) = flag(db_session, rule, po)
    save_new_version(db_session, rule, definition=PRC_APR_01)        # new version -> new exception
    _, (second, created) = flag(db_session, rule, po)
    assert created is False and second.id == first.id
    assert len(case_exceptions(db_session, first)) == 2


def test_outside_the_window_opens_a_new_case(db_session):
    rule, po = rule_for(db_session, uuid.uuid4()), uuid.uuid4()
    _, (first, _) = flag(db_session, rule, po)
    first.opened_at = _now() - timedelta(days=10)                     # default window is 7 days
    db_session.flush()
    save_new_version(db_session, rule, definition=PRC_APR_01)
    _, (second, created) = flag(db_session, rule, po)
    assert created is True and second.id != first.id


def test_different_rule_on_same_record_gets_its_own_case(db_session):
    tenant, po = uuid.uuid4(), uuid.uuid4()
    _, (first, _) = flag(db_session, rule_for(db_session, tenant, "PRC-APR-01"), po)
    _, (second, created) = flag(db_session, rule_for(db_session, tenant, "PRC-SPL-01"), po)
    assert created is True and second.id != first.id


def test_closed_case_is_never_reused(db_session):
    rule, po = rule_for(db_session, uuid.uuid4()), uuid.uuid4()
    _, (first, _) = flag(db_session, rule, po)
    first.status = "CLOSED"
    db_session.flush()
    save_new_version(db_session, rule, definition=PRC_APR_01)
    _, (second, created) = flag(db_session, rule, po)
    assert created is True and second.id != first.id


def test_other_hospital_is_never_grouped(db_session):
    po = uuid.uuid4()
    _, (case_a, _) = flag(db_session, rule_for(db_session, uuid.uuid4()), po)
    _, (case_b, created) = flag(db_session, rule_for(db_session, uuid.uuid4()), po)
    assert created is True and case_b.tenant_id != case_a.tenant_id
    assert len(case_exceptions(db_session, case_a)) == 1


def test_procurement_event_creates_exception_and_case_end_to_end(db_session):
    tenant, department = hospital(db_session), uuid.uuid4()
    rule = add_rule(db_session, tenant)
    result = handle_procurement_event(db_session, make_event(tenant), PoReader(department_id=str(department)))
    assert result.exceptions_created == 1
    [case] = list_cases(db_session, tenant)
    [exception] = case_exceptions(db_session, case)
    assert (case.title, case.priority, case.department_id) == (rule.name, "HIGH", department)
    assert (exception.rule_id, exception.status) == (rule.id, "IN_CASE")


def test_notify_only_rule_opens_no_case(db_session):
    tenant = hospital(db_session)
    add_rule(db_session, tenant, definition={**PRC_APR_01, "action": {"type": "NOTIFY_ONLY"}})
    handle_procurement_event(db_session, make_event(tenant), PoReader())
    assert list_cases(db_session, tenant) == []


# --- Backfill: exceptions made before grouping existed ---

def test_backfill_groups_old_exceptions_then_finds_nothing(db_session):
    tenant, po = uuid.uuid4(), uuid.uuid4()
    rule = rule_for(db_session, tenant)
    old_exception(db_session, rule, po)
    save_new_version(db_session, rule, definition=PRC_APR_01)
    old_exception(db_session, rule, po)                      # same rule + record -> joins the first case
    old_exception(db_session, rule, uuid.uuid4())            # other record -> its own case

    first = backfill_cases(db_session, tenant)
    assert first == {"exceptions": 3, "cases_created": 2, "joined": 1, "skipped": 0}
    assert len(list_cases(db_session, tenant)) == 2

    second = backfill_cases(db_session, tenant)
    assert second == {"exceptions": 0, "cases_created": 0, "joined": 0, "skipped": 0}


def test_backfill_leaves_other_hospitals_alone(db_session):
    mine, other = uuid.uuid4(), uuid.uuid4()
    old_exception(db_session, rule_for(db_session, mine), uuid.uuid4())
    theirs = old_exception(db_session, rule_for(db_session, other), uuid.uuid4())
    backfill_cases(db_session, mine)
    assert theirs.status == "NEW" and list_cases(db_session, other) == []
