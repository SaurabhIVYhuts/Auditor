"""Batch rule runs (AUD-012 part 2): re-check recent records with an ACTIVE rule.

Used by the "run now" button (MANUAL) and the nightly scheduler (BATCH). Only each record's
LATEST snapshot is checked; dedup stops already-found problems being saved twice.
Does NOT commit: the caller does.
"""
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.audit.models import AuditRule, AuditRuleRun, AuditSourceRecord, RuleStatus, RunTrigger
from agents.audit.rules import dsl_spec as spec
from agents.audit.services.rule_engine import run_rule

DEFAULT_LOOKBACK_DAYS = 30


def entity_types_used(node: Any) -> set[str]:
    """Hub entity types a rule reads, e.g. a rule using po.* reads 'purchase_order'."""
    if isinstance(node, str):
        prefix, _, name = node.partition(".")
        return {spec.ENTITY_TYPES[prefix]} if name in spec.FIELDS.get(prefix, frozenset()) else set()
    if isinstance(node, list):
        return set().union(*(entity_types_used(item) for item in node))
    if isinstance(node, dict):
        found: set[str] = set()
        for key, value in node.items():
            if key in ("value", "value_ref"):
                continue
            if key == "entity" and value in spec.ENTITY_TYPES:
                found.add(spec.ENTITY_TYPES[value])
            else:
                found |= entity_types_used(value)
        return found
    return set()


def latest_snapshots(
    db: Session, *, tenant_id, entity_types: set[str], since: datetime,
) -> list[AuditSourceRecord]:
    """Latest snapshot of each procurement record of these types captured since `since`."""
    if not entity_types:
        return []
    return list(db.scalars(
        select(AuditSourceRecord).where(
            AuditSourceRecord.tenant_id == tenant_id,
            AuditSourceRecord.source_system == "procurement",
            AuditSourceRecord.entity_type.in_(sorted(entity_types)),
            AuditSourceRecord.is_deleted.is_(False),
            AuditSourceRecord.captured_at >= since,
        )
        .distinct(AuditSourceRecord.entity_id)                       # one row per record...
        .order_by(AuditSourceRecord.entity_id, AuditSourceRecord.captured_at.desc())  # ...the newest
    ))


def run_rule_batch(
    db: Session, rule: AuditRule, *, trigger_type: str = RunTrigger.MANUAL.value,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS, as_of: datetime | None = None,
) -> AuditRuleRun:
    """Run one ACTIVE rule on the latest snapshot of every relevant record in the window."""
    if rule.status != RuleStatus.ACTIVE.value:
        raise ValueError(f"Rule {rule.rule_code} is {rule.status}; only ACTIVE rules can run")
    as_of = as_of or datetime.now(timezone.utc)
    records = latest_snapshots(
        db, tenant_id=rule.tenant_id,
        entity_types=entity_types_used(rule.definition["condition"]),
        since=as_of - timedelta(days=lookback_days),
    )
    return run_rule(db, rule, records, trigger_type=trigger_type)


def run_due_batch_rules(db: Session, tenant_id) -> list[AuditRuleRun]:
    """Nightly job: run every ACTIVE rule of this hospital that has a batch schedule."""
    rules = db.scalars(select(AuditRule).where(
        AuditRule.tenant_id == tenant_id,
        AuditRule.status == RuleStatus.ACTIVE.value,
        AuditRule.is_deleted.is_(False),
    ).order_by(AuditRule.rule_code)).all()
    due = [r for r in rules
           if r.definition["trigger"]["type"] == "BATCH" or r.definition["trigger"].get("batch_cron")]
    return [run_rule_batch(db, r, trigger_type=RunTrigger.BATCH.value) for r in due]
