"""Exceptions (AUD-013): problems found by rules (later also by anomaly models), and rule-run history.

An exception remembers the rule version and severity used when it was found, so it stays
explainable even after the rule changes. dedup_key (rule + record + version) is UNIQUE,
so re-running the same rule version on the same record never creates a duplicate.
"""
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agents.audit.models.base import AuditBase
from agents.audit.models.rule import Severity, _allowed
from shared.models import CommonColumns


class ExceptionSource(StrEnum):
    RULE = "RULE"
    ANOMALY = "ANOMALY"


class ExceptionStatus(StrEnum):
    NEW = "NEW"
    IN_CASE = "IN_CASE"
    SUPPRESSED = "SUPPRESSED"


class AuditException(CommonColumns, AuditBase):
    __tablename__ = "audit_exceptions"
    __table_args__ = (
        CheckConstraint(_allowed("source", ExceptionSource), name="source"),
        CheckConstraint(_allowed("status", ExceptionStatus), name="status"),
        CheckConstraint(_allowed("severity", Severity), name="severity"),
        # A RULE exception must point to its rule; an ANOMALY exception must not.
        CheckConstraint("(source = 'RULE') = (rule_id IS NOT NULL)", name="rule_link"),
        Index("ix_audit_exceptions_entity", "entity_type", "entity_id"),
    )

    source: Mapped[str] = mapped_column(String(10), default=ExceptionSource.RULE.value,
                                        server_default=ExceptionSource.RULE.value)
    rule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("audit.audit_rules.id"), index=True)
    rule_version: Mapped[int | None]
    anomaly_model: Mapped[str | None] = mapped_column(String(60))
    severity: Mapped[str] = mapped_column(String(10))           # copied when found (input to risk)
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[uuid.UUID]
    source_record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audit.audit_source_records.id"))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB)      # the values that triggered it
    dedup_key: Mapped[str] = mapped_column(String(200), unique=True)
    # The case an exception belongs to is in audit_case_exceptions (the only source of truth).
    status: Mapped[str] = mapped_column(String(12), index=True, default=ExceptionStatus.NEW.value,
                                        server_default=ExceptionStatus.NEW.value)


class RunTrigger(StrEnum):
    EVENT = "EVENT"
    BATCH = "BATCH"
    MANUAL = "MANUAL"


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class AuditRuleRun(CommonColumns, AuditBase):
    """One run of one rule: when, why, how many records checked, hits, warnings, errors."""

    __tablename__ = "audit_rule_runs"
    __table_args__ = (
        CheckConstraint(_allowed("trigger_type", RunTrigger), name="trigger_type"),
        CheckConstraint(_allowed("status", RunStatus), name="status"),
    )

    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audit.audit_rules.id"), index=True)
    rule_version: Mapped[int]
    trigger_type: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10), default=RunStatus.RUNNING.value,
                                        server_default=RunStatus.RUNNING.value)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records_checked: Mapped[int] = mapped_column(default=0, server_default="0")
    exceptions_created: Mapped[int] = mapped_column(default=0, server_default="0")
    duplicates_skipped: Mapped[int] = mapped_column(default=0, server_default="0")
    warnings: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    error: Mapped[str | None] = mapped_column(Text)
