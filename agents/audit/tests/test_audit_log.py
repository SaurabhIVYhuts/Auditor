"""Tests for the append-only audit log placeholder (shared/audit_log.py)."""
import uuid

import shared.audit_log as audit_log
from shared.audit_log import list_for_entity, log_action


def test_log_action_writes_a_row(db_session):
    tenant, actor, rule_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    row = log_action(db_session, tenant, actor, "rule.activated", "audit_rule", rule_id, {"version": 1})
    db_session.refresh(row)
    assert (row.tenant_id, row.actor_id, row.action) == (tenant, actor, "rule.activated")
    assert row.details == {"version": 1} and row.created_at is not None


def test_list_for_entity_is_oldest_first(db_session):
    tenant, case_id = uuid.uuid4(), uuid.uuid4()
    for action in ("case.opened", "case.assigned", "case.closed"):
        log_action(db_session, tenant, None, action, "audit_case", case_id)
    actions = [row.action for row in list_for_entity(db_session, tenant, "audit_case", case_id)]
    assert actions == ["case.opened", "case.assigned", "case.closed"]


def test_other_hospitals_logs_are_never_returned(db_session):
    mine, other, record = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    log_action(db_session, mine, None, "case.opened", "audit_case", record)
    log_action(db_session, other, None, "case.opened", "audit_case", record)
    rows = list_for_entity(db_session, mine, "audit_case", record)
    assert [row.tenant_id for row in rows] == [mine]


def test_module_offers_no_update_or_delete():
    public = {name for name in dir(audit_log) if not name.startswith("_")}
    assert not {n for n in public if n.startswith(("update", "delete", "remove", "edit"))}
