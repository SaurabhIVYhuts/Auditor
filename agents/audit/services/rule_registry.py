"""Rule registry (AUD-010): create rules, save new versions, read and write config values.

Every edit creates a new, permanent version row (older versions are never changed).
Thresholds come from audit_config, never from code. Does NOT commit: the caller does.
"""
import copy
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.audit.models import AuditConfig, AuditRule, AuditRuleVersion, RuleDomain, RuleStatus, Severity
from agents.audit.rules.validator import ensure_valid


class ConfigMissingError(LookupError):
    """A rule needs a config value that this hospital has not set."""


def create_rule(
    db: Session, *, tenant_id: uuid.UUID, rule_code: str, name: str, domain: str,
    severity: str, definition: dict[str, Any], owner_id: uuid.UUID | None = None,
    description: str | None = None,
) -> AuditRule:
    """Create a rule as DRAFT, version 1, and record version 1 in the history."""
    ensure_valid(definition)   # invalid rules are never saved, not even as drafts
    RuleDomain(domain)   # raises ValueError for an unknown domain
    Severity(severity)   # raises ValueError for an unknown severity
    rule = AuditRule(
        tenant_id=tenant_id, rule_code=rule_code, name=name, description=description,
        domain=domain, severity=severity, definition=copy.deepcopy(definition),
        current_version=1, owner_id=owner_id, created_by=owner_id,
    )
    db.add(rule)
    db.flush()
    db.add(AuditRuleVersion(
        tenant_id=tenant_id, rule_id=rule.id, version=1, definition=copy.deepcopy(definition),
        severity=severity, change_note="Created", created_by=owner_id,
    ))
    db.flush()
    return rule


def save_new_version(
    db: Session, rule: AuditRule, *, definition: dict[str, Any], severity: str | None = None,
    changed_by: uuid.UUID | None = None, change_note: str | None = None,
) -> AuditRule:
    """Every edit becomes a new version; older versions stay exactly as they were."""
    ensure_valid(definition)
    severity = severity or rule.severity
    Severity(severity)
    new_version = rule.current_version + 1
    db.add(AuditRuleVersion(
        tenant_id=rule.tenant_id, rule_id=rule.id, version=new_version,
        definition=copy.deepcopy(definition), severity=severity,
        change_note=change_note, created_by=changed_by,
    ))
    rule.current_version = new_version
    rule.definition = copy.deepcopy(definition)
    rule.severity = severity
    rule.updated_by = changed_by
    rule.status = RuleStatus.DRAFT.value         # any change must be activated (approved) again
    rule.approved_by = None
    rule.approved_at = None
    db.flush()
    return rule


def get_rule_version(db: Session, rule_id: uuid.UUID, version: int) -> AuditRuleVersion | None:
    return db.scalar(
        select(AuditRuleVersion).where(
            AuditRuleVersion.rule_id == rule_id, AuditRuleVersion.version == version
        )
    )


def _config_row(db: Session, tenant_id: uuid.UUID, key: str) -> AuditConfig | None:
    return db.scalar(
        select(AuditConfig).where(
            AuditConfig.tenant_id == tenant_id,
            AuditConfig.key == key,
            AuditConfig.is_deleted.is_(False),
        )
    )


def set_config_value(
    db: Session, *, tenant_id: uuid.UUID, key: str, value: Any,
    description: str | None = None, changed_by: uuid.UUID | None = None,
) -> AuditConfig:
    row = _config_row(db, tenant_id, key)
    if row is None:
        row = AuditConfig(tenant_id=tenant_id, key=key, created_by=changed_by)
        db.add(row)
    row.value = value
    row.updated_by = changed_by
    if description is not None:
        row.description = description
    db.flush()
    return row


def get_config_value(db: Session, tenant_id: uuid.UUID, key: str) -> Any:
    """Return the hospital's value for key. Missing value -> ConfigMissingError (never a silent pass)."""
    row = _config_row(db, tenant_id, key)
    if row is None:
        raise ConfigMissingError(f"Config value {key!r} is not set for this hospital")
    return row.value


class MakerCheckerError(PermissionError):
    """The person who wrote or changed a HIGH/CRITICAL rule cannot also approve it."""


NEEDS_SECOND_PERSON = frozenset({"HIGH", "CRITICAL"})


def activate_rule(db: Session, rule: AuditRule, *, approved_by: uuid.UUID) -> AuditRule:
    """Make a rule ACTIVE. HIGH/CRITICAL rules need someone other than their author (maker-checker)."""
    ensure_valid(rule.definition)
    makers = {rule.created_by, rule.owner_id, rule.updated_by} - {None}
    if rule.severity in NEEDS_SECOND_PERSON and approved_by in makers:
        raise MakerCheckerError("MAKER_CHECKER: the author of a HIGH/CRITICAL rule cannot approve it")
    rule.status = RuleStatus.ACTIVE.value
    rule.approved_by = approved_by
    rule.approved_at = datetime.now(timezone.utc)
    db.flush()
    return rule


def deactivate_rule(db: Session, rule: AuditRule) -> AuditRule:
    """Stop a rule from running. Its versions, runs and exceptions are all kept."""
    rule.status = RuleStatus.INACTIVE.value
    db.flush()
    return rule
