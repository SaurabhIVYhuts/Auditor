"""End-to-end: procurement event -> snapshot -> ACTIVE rules -> exceptions (AUD-012)."""
import uuid

from sqlalchemy import select

from agents.audit.events.envelope import EventEnvelope
from agents.audit.events.procurement_event_consumer import handle_procurement_event
from agents.audit.models import AuditException, AuditRuleRun, AuditSourceRecord
from agents.audit.services.rule_registry import create_rule, set_config_value

PRC_APR_01 = {
    "trigger": {"type": "EVENT", "events": ["procurement.po.approved"]},
    "condition": {"all": [
        {"field": "po.grand_total", "op": ">", "value_ref": "config.po_high_value_limit"},
        {"fn": "approval_missing", "args": {"entity": "po", "min_level": "po.required_approval_level"}},
    ]},
    "action": {"type": "CREATE_EXCEPTION"},
}


class PoReader:
    """Mock procurement reader that returns a PO we control."""

    def __init__(self, **overrides):
        self.data = {"po_number": "PO-T-1", "vendor_id": "V-T-1", "grand_total": 200000,
                     "required_approval_level": 2, "approvals": [{"level": 1}]}
        self.data.update(overrides)

    def get_record(self, tenant_id, entity_type, entity_id):
        return {"id": str(entity_id), **self.data}


def make_event(tenant, event_type="procurement.po.approved", event_id=None):
    return EventEnvelope.model_validate({
        "event_id": str(event_id or uuid.uuid4()), "event_type": event_type, "version": 1,
        "occurred_at": "2026-10-08T10:00:00+05:30", "tenant_id": str(tenant),
        "actor": {"type": "system"}, "entity": {"type": "purchase_order", "id": str(uuid.uuid4())},
    })


def hospital(db, with_limit=True):
    tenant = uuid.uuid4()
    if with_limit:
        set_config_value(db, tenant_id=tenant, key="po_high_value_limit", value=100000)
    return tenant


def add_rule(db, tenant, definition=PRC_APR_01, status="ACTIVE", scope=None):
    rule = create_rule(db, tenant_id=tenant, rule_code="PRC-APR-01", name="High-value PO without approval",
                       domain="PROCUREMENT", severity="HIGH", definition=definition)
    rule.status, rule.department_scope = status, scope
    db.flush()
    return rule


def exceptions_for(db, rule):
    return db.scalars(select(AuditException).where(AuditException.rule_id == rule.id)).all()


def runs_for(db, rule):
    return db.scalars(select(AuditRuleRun).where(AuditRuleRun.rule_id == rule.id)).all()


def test_event_creates_exception_and_logs_run(db_session):
    tenant = hospital(db_session)
    rule = add_rule(db_session, tenant)
    result = handle_procurement_event(db_session, make_event(tenant), PoReader())

    assert result.status == "processed" and result.exceptions_created == 1
    [exc] = exceptions_for(db_session, rule)
    assert exc.source_record_id == result.source_record_id and exc.severity == "HIGH"
    [run] = runs_for(db_session, rule)
    assert (run.trigger_type, run.status, run.records_checked, run.exceptions_created) == (
        "EVENT", "SUCCEEDED", 1, 1)


def test_properly_approved_po_creates_no_exception(db_session):
    tenant = hospital(db_session)
    rule = add_rule(db_session, tenant)
    result = handle_procurement_event(db_session, make_event(tenant), PoReader(approvals=[{"level": 2}]))
    assert result.exceptions_created == 0 and exceptions_for(db_session, rule) == []


def test_same_event_twice_gives_one_exception(db_session):
    tenant = hospital(db_session)
    rule = add_rule(db_session, tenant)
    event = make_event(tenant)
    handle_procurement_event(db_session, event, PoReader())
    second = handle_procurement_event(db_session, event, PoReader())
    assert second.status == "duplicate"
    assert len(exceptions_for(db_session, rule)) == 1 and len(runs_for(db_session, rule)) == 1


def test_draft_rule_never_runs(db_session):
    tenant = hospital(db_session)
    rule = add_rule(db_session, tenant, status="DRAFT")
    handle_procurement_event(db_session, make_event(tenant), PoReader())
    assert runs_for(db_session, rule) == [] and exceptions_for(db_session, rule) == []


def test_rule_for_another_event_does_not_run(db_session):
    tenant = hospital(db_session)
    rule = add_rule(db_session, tenant)
    handle_procurement_event(db_session, make_event(tenant, "procurement.po.issued"), PoReader())
    assert runs_for(db_session, rule) == []


def test_missing_config_fails_the_run_but_keeps_the_snapshot(db_session):
    tenant = hospital(db_session, with_limit=False)
    rule = add_rule(db_session, tenant)
    result = handle_procurement_event(db_session, make_event(tenant), PoReader())
    [run] = runs_for(db_session, rule)
    assert run.status == "FAILED" and "po_high_value_limit" in run.error
    assert exceptions_for(db_session, rule) == []
    assert db_session.get(AuditSourceRecord, result.source_record_id) is not None


def test_missing_field_is_a_warning_not_an_exception(db_session):
    tenant = hospital(db_session)
    rule = add_rule(db_session, tenant)
    handle_procurement_event(db_session, make_event(tenant), PoReader(grand_total=None))
    [run] = runs_for(db_session, rule)
    assert run.status == "SUCCEEDED" and run.warnings and exceptions_for(db_session, rule) == []


def test_rule_skips_other_departments(db_session):
    tenant = hospital(db_session)
    rule = add_rule(db_session, tenant, scope=[uuid.uuid4()])
    handle_procurement_event(db_session, make_event(tenant), PoReader(department_id=str(uuid.uuid4())))
    [run] = runs_for(db_session, rule)
    assert run.records_checked == 0 and exceptions_for(db_session, rule) == []


def test_notify_only_rule_saves_no_exception(db_session):
    tenant = hospital(db_session)
    rule = add_rule(db_session, tenant, definition={**PRC_APR_01, "action": {"type": "NOTIFY_ONLY"}})
    handle_procurement_event(db_session, make_event(tenant), PoReader())
    [run] = runs_for(db_session, rule)
    assert run.records_checked == 1 and exceptions_for(db_session, rule) == []
