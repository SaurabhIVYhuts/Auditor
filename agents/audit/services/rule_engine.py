"""Rule engine (AUD-012): runs ACTIVE rules on records and saves what they find.

For each record: build facts from its snapshot, evaluate the rule (read-only), and if the
answer is definitely True, save an exception (deduplicated). Every run is logged in
audit_rule_runs. If a rule cannot run (e.g. a config value is missing) the run is marked
FAILED with the reason and its partial results are undone: nothing fails silently.
Does NOT commit: the caller does.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.audit.models import (
    AuditRule, AuditRuleRun, AuditSourceRecord, RuleStatus, RunStatus, RunTrigger,
)
from agents.audit.rules import dsl_spec as spec
from agents.audit.rules.db_functions import make_db_functions
from agents.audit.rules.evaluator import (
    EvaluationContext, EvaluationResult, RuleEvaluationError, evaluate_condition,
)
from agents.audit.services.exception_service import record_rule_exception
from agents.audit.services.rule_registry import ConfigMissingError, get_config_value

PREFIX_FOR_ENTITY = {entity: prefix for prefix, entity in spec.ENTITY_TYPES.items()}
CREATES_EXCEPTION = frozenset({"CREATE_EXCEPTION", "CREATE_CASE"})   # NOTIFY_ONLY never does
MAX_WARNINGS_PER_RUN = 100


def build_facts(record: AuditSourceRecord) -> dict[str, dict]:
    """Facts for the evaluator, e.g. a purchase_order snapshot becomes {"po": {...}}."""
    prefix = PREFIX_FOR_ENTITY.get(record.entity_type)
    return {prefix: record.snapshot} if prefix else {}


def in_department_scope(rule: AuditRule, record: AuditSourceRecord) -> bool:
    if not rule.department_scope:
        return True                                   # empty = all departments
    allowed = {str(d) for d in rule.department_scope}
    return str(record.snapshot.get("department_id")) in allowed


def evaluate_rule_on_record(db: Session, rule: AuditRule, record: AuditSourceRecord) -> EvaluationResult:
    ctx = EvaluationContext(
        facts=build_facts(record),
        get_config=lambda key: get_config_value(db, rule.tenant_id, key),
        functions=make_db_functions(db, tenant_id=rule.tenant_id, current_entity_id=record.entity_id),
    )
    return evaluate_condition(rule.definition["condition"], ctx)


def active_rules_for_event(db: Session, tenant_id: uuid.UUID, event_type: str) -> list[AuditRule]:
    """ACTIVE, non-deleted rules of this hospital that listen to this event."""
    return list(db.scalars(
        select(AuditRule).where(
            AuditRule.tenant_id == tenant_id,
            AuditRule.status == RuleStatus.ACTIVE.value,
            AuditRule.is_deleted.is_(False),
            AuditRule.definition.contains({"trigger": {"type": "EVENT", "events": [event_type]}}),
        ).order_by(AuditRule.rule_code)
    ))


def run_rule(
    db: Session, rule: AuditRule, records: list[AuditSourceRecord], *, trigger_type: str,
) -> AuditRuleRun:
    """Run one rule on some records, save new exceptions, and log the run."""
    run = AuditRuleRun(tenant_id=rule.tenant_id, rule_id=rule.id,
                       rule_version=rule.current_version, trigger_type=trigger_type)
    db.add(run)
    db.flush()                                        # the run log is kept even if the run fails

    warnings: list[str] = []
    checked = created = skipped = 0
    try:
        with db.begin_nested():                       # a failed run leaves no partial exceptions behind
            for record in records:
                if record.tenant_id != rule.tenant_id or not in_department_scope(rule, record):
                    continue
                checked += 1
                result = evaluate_rule_on_record(db, rule, record)
                warnings += [f"{record.entity_type} {record.entity_id}: {w}" for w in result.warnings]
                if result.matched and rule.definition["action"]["type"] in CREATES_EXCEPTION:
                    _, is_new = record_rule_exception(
                        db, rule=rule, entity_type=record.entity_type, entity_id=record.entity_id,
                        source_record_id=record.id,
                        details={"checks": result.details, "warnings": result.warnings},
                    )
                    if is_new:
                        created += 1
                    else:
                        skipped += 1
    except (ConfigMissingError, RuleEvaluationError) as err:
        run.status, run.error = RunStatus.FAILED.value, str(err)
        created = skipped = 0                         # everything inside the savepoint was undone
    else:
        run.status = RunStatus.SUCCEEDED.value

    run.records_checked = checked
    run.exceptions_created = created
    run.duplicates_skipped = skipped
    run.warnings = warnings[:MAX_WARNINGS_PER_RUN]
    run.finished_at = datetime.now(timezone.utc)
    db.flush()
    return run


def run_rules_for_event(
    db: Session, *, tenant_id: uuid.UUID, event_type: str, record: AuditSourceRecord,
) -> list[AuditRuleRun]:
    """Run every ACTIVE rule that listens to this event on the record's new snapshot."""
    return [run_rule(db, rule, [record], trigger_type=RunTrigger.EVENT.value)
            for rule in active_rules_for_event(db, tenant_id, event_type)]
