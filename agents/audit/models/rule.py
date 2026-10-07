"""Audit rules (module M2): rule registry, version history and per-hospital config values.

Rules are data (JSON DSL), not code. Every edit creates a new version, and
thresholds live in audit_config, never hard-coded.
"""
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from agents.audit.models.base import AuditBase
from shared.models import CommonColumns


class RuleDomain(StrEnum):
    PROCUREMENT = "PROCUREMENT"
    INSURANCE = "INSURANCE"
    BILLING = "BILLING"
    FINANCIAL = "FINANCIAL"
    COMPLIANCE = "COMPLIANCE"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RuleStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


def _allowed(column: str, values: type[StrEnum]) -> str:
    return f"{column} IN ({', '.join(repr(v.value) for v in values)})"


class AuditRule(CommonColumns, AuditBase):
    __tablename__ = "audit_rules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "rule_code"),  # unique per hospital
        CheckConstraint(_allowed("domain", RuleDomain), name="domain"),
        CheckConstraint(_allowed("severity", Severity), name="severity"),
        CheckConstraint(_allowed("status", RuleStatus), name="status"),
    )

    rule_code: Mapped[str] = mapped_column(String(30))          # e.g. PRC-APR-01
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String(30), index=True)
    department_scope: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True))
    )                                                            # null = all departments
    severity: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(
        String(10), index=True, default=RuleStatus.DRAFT.value, server_default=RuleStatus.DRAFT.value
    )
    current_version: Mapped[int] = mapped_column(default=1, server_default="1")
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB)    # trigger, condition, action
    owner_id: Mapped[uuid.UUID | None]
    approved_by: Mapped[uuid.UUID | None]
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditRuleVersion(CommonColumns, AuditBase):
    """Every saved version of a rule. Never edited after it is written."""

    __tablename__ = "audit_rule_versions"
    __table_args__ = (UniqueConstraint("rule_id", "version"),)

    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audit.audit_rules.id"))
    version: Mapped[int]
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB)
    severity: Mapped[str] = mapped_column(String(10))
    change_note: Mapped[str | None] = mapped_column(Text)


class AuditConfig(CommonColumns, AuditBase):
    """Configurable values used by rules, per hospital (e.g. po_high_value_limit)."""

    __tablename__ = "audit_config"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)

    key: Mapped[str] = mapped_column(String(100))
    value: Mapped[Any] = mapped_column(JSONB)
    description: Mapped[str | None] = mapped_column(Text)
