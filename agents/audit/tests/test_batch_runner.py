"""Tests for batch rule runs (AUD-012 part 2)."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from agents.audit.services.batch_runner import entity_types_used, run_due_batch_rules, run_rule_batch
from agents.audit.services.rule_registry import create_rule, set_config_value
from agents.audit.services.snapshot_service import capture_snapshot
from agents.audit.tests.test_rule_engine import PRC_APR_01

BAD_PO = {"grand_total": 200000, "required_approval_level": 2, "approvals": [{"level": 1}]}
GOOD_PO = {"grand_total": 200000, "required_approval_level": 2, "approvals": [{"level": 2}]}


def po(db, tenant, data, entity_id=None, days_ago=0):
    rec = capture_snapshot(db, tenant_id=tenant, source_system="procurement",
                           entity_type="purchase_order", entity_id=entity_id or uuid.uuid4(), data=data)
    if days_ago:
        rec.captured_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
        db.flush()
    return rec


def active_rule(db, tenant, definition=PRC_APR_01, code="PRC-APR-01", with_limit=True):
    if with_limit:
        set_config_value(db, tenant_id=tenant, key="po_high_value_limit", value=100000)
    rule = create_rule(db, tenant_id=tenant, rule_code=code, name="Batch test rule",
                       domain="PROCUREMENT", severity="HIGH", definition=definition)
    rule.status = "ACTIVE"
    db.flush()
    return rule


def test_entity_types_used_reads_the_rule():
    assert entity_types_used(PRC_APR_01["condition"]) == {"purchase_order"}
    days = {"fn": "days_between", "args": {"from": "grn.posted_at", "to": "invoice.invoice_date"},
            "op": ">", "value": 30}
    assert entity_types_used(days) == {"grn", "invoice"}


def test_batch_checks_existing_records(db_session):
    tenant = uuid.uuid4()
    rule = active_rule(db_session, tenant)
    po(db_session, tenant, BAD_PO)
    po(db_session, tenant, GOOD_PO)
    run = run_rule_batch(db_session, rule)
    assert (run.trigger_type, run.status, run.records_checked, run.exceptions_created) == (
        "MANUAL", "SUCCEEDED", 2, 1)


def test_second_batch_run_creates_no_duplicates(db_session):
    tenant = uuid.uuid4()
    rule = active_rule(db_session, tenant)
    po(db_session, tenant, BAD_PO)
    run_rule_batch(db_session, rule)
    second = run_rule_batch(db_session, rule)
    assert (second.exceptions_created, second.duplicates_skipped) == (0, 1)


def test_fixing_missing_config_then_rerunning_finds_the_problem(db_session):
    tenant = uuid.uuid4()
    rule = active_rule(db_session, tenant, with_limit=False)
    po(db_session, tenant, BAD_PO)
    assert run_rule_batch(db_session, rule).status == "FAILED"
    set_config_value(db_session, tenant_id=tenant, key="po_high_value_limit", value=100000)
    assert run_rule_batch(db_session, rule).exceptions_created == 1


def test_only_latest_version_of_a_record_is_checked(db_session):
    tenant, po_id = uuid.uuid4(), uuid.uuid4()
    rule = active_rule(db_session, tenant)
    po(db_session, tenant, BAD_PO, entity_id=po_id, days_ago=1)   # old version had a problem
    po(db_session, tenant, GOOD_PO, entity_id=po_id)              # corrected version
    run = run_rule_batch(db_session, rule)
    assert (run.records_checked, run.exceptions_created) == (1, 0)


def test_records_older_than_lookback_are_skipped(db_session):
    tenant = uuid.uuid4()
    rule = active_rule(db_session, tenant)
    po(db_session, tenant, BAD_PO, days_ago=45)
    assert run_rule_batch(db_session, rule).records_checked == 0


def test_draft_rule_cannot_batch_run(db_session):
    rule = active_rule(db_session, uuid.uuid4())
    rule.status = "DRAFT"
    with pytest.raises(ValueError):
        run_rule_batch(db_session, rule)


def test_nightly_job_runs_only_scheduled_rules(db_session):
    tenant = uuid.uuid4()
    scheduled = {**PRC_APR_01, "trigger": {**PRC_APR_01["trigger"], "batch_cron": "0 2 * * *"}}
    active_rule(db_session, tenant, definition=scheduled, code="PRC-APR-01")
    active_rule(db_session, tenant, code="PRC-APR-02")            # event-only, no schedule
    runs = run_due_batch_rules(db_session, tenant)
    assert [r.trigger_type for r in runs] == ["BATCH"]
