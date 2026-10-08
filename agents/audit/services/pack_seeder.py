"""Seed the procurement rule pack into one hospital (AUD-014).

Rules are created as DRAFT through the rule registry, so every definition is validated and
nothing runs until someone activates it. Rules the hospital already has (same rule_code) are
never overwritten, and an existing po_high_value_limit is left alone.
Does NOT commit: the caller does.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.audit.models import AuditRule
from agents.audit.rules.procurement_pack import PACK
from agents.audit.services.rule_registry import (
    ConfigMissingError, create_rule, get_config_value, set_config_value,
)

DEFAULT_PO_HIGH_VALUE_LIMIT = 100000   # starting value only; each hospital can change it in audit_config


def seed_procurement_pack(db: Session, tenant_id: uuid.UUID, created_by: uuid.UUID | None) -> dict:
    """Add the missing pack rules (as DRAFT) and the default limit if not set."""
    # Includes soft-deleted rules: the rule_code stays taken, and a deleted rule is a hospital decision.
    existing = set(db.scalars(select(AuditRule.rule_code).where(AuditRule.tenant_id == tenant_id)))
    created = skipped = 0
    for rule in PACK:
        if rule["rule_code"] in existing:
            skipped += 1
            continue
        create_rule(
            db, tenant_id=tenant_id, rule_code=rule["rule_code"], name=rule["name"],
            domain=rule["domain"], severity=rule["severity"], definition=rule["definition"],
            owner_id=created_by,
        )
        created += 1

    config_set = False
    try:
        get_config_value(db, tenant_id, "po_high_value_limit")
    except ConfigMissingError:
        set_config_value(
            db, tenant_id=tenant_id, key="po_high_value_limit", value=DEFAULT_PO_HIGH_VALUE_LIMIT,
            description="PO amount above which extra approval is required (default, please review)",
            changed_by=created_by,
        )
        config_set = True
    return {"created": created, "skipped": skipped, "config_set": config_set}
