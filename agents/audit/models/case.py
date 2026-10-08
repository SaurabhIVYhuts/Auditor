"""Audit cases (module M1, AUD-020): a case groups exceptions for one auditor to investigate.

Status values come from the case state machine (agents.audit.cases.state_machine), so the
list exists in one place only. Case numbers (AUD-YYYY-NNNNN) are unique per hospital and
come from audit_case_counters (see agents.audit.cases.numbering).
"""
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, false, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from agents.audit.cases.state_machine import CaseStatus
from agents.audit.models.base import AuditBase
from agents.audit.models.rule import RuleDomain, Severity, _allowed
from shared.models import CommonColumns


class CaseSource(StrEnum):
    RULE = "RULE"
    ANOMALY = "ANOMALY"
    MANUAL = "MANUAL"


# Every rule domain, plus OTHER for manual cases that fit no rule domain (architecture 4.1).
CaseDomain = StrEnum("CaseDomain", {**{d.name: d.value for d in RuleDomain}, "OTHER": "OTHER"})


class AuditCase(CommonColumns, AuditBase):
    __tablename__ = "audit_cases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "case_number"),           # unique per hospital
        CheckConstraint(_allowed("domain", CaseDomain), name="domain"),
        CheckConstraint(_allowed("source", CaseSource), name="source"),
        CheckConstraint(_allowed("status", CaseStatus), name="status"),
        CheckConstraint(_allowed("priority", Severity), name="priority"),
        Index("ix_audit_cases_tenant_status", "tenant_id", "status"),
        Index("ix_audit_cases_tenant_assigned", "tenant_id", "assigned_to"),
    )

    case_number: Mapped[str] = mapped_column(String(20))         # e.g. AUD-2026-00031
    domain: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(10))
    primary_entity_type: Mapped[str] = mapped_column(String(60))
    primary_entity_id: Mapped[uuid.UUID]
    department_id: Mapped[uuid.UUID | None]                      # the auditee department
    status: Mapped[str] = mapped_column(String(20), default=CaseStatus.OPEN.value,
                                        server_default=CaseStatus.OPEN.value)
    priority: Mapped[str] = mapped_column(String(10))            # LOW | MEDIUM | HIGH | CRITICAL
    assigned_to: Mapped[uuid.UUID | None]
    is_restricted: Mapped[bool] = mapped_column(default=False, server_default=false())  # personnel-sensitive
    ai_summary: Mapped[str | None] = mapped_column(Text)         # labelled AI in the UI; never changes status
    closure_reason: Mapped[str | None] = mapped_column(Text)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # risk_score_id: added in Phase 6 (risk engine)


class AuditCaseException(CommonColumns, AuditBase):
    """Links an exception to its case. exception_id is UNIQUE: one case per exception."""

    __tablename__ = "audit_case_exceptions"

    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audit.audit_cases.id"), index=True)
    exception_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audit.audit_exceptions.id"), unique=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditCaseComment(CommonColumns, AuditBase):
    """An internal comment on a case (auditors and audit managers only)."""

    __tablename__ = "audit_case_comments"
    __table_args__ = (CheckConstraint("length(trim(body)) > 0", name="body_not_empty"),)

    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audit.audit_cases.id"), index=True)
    author_id: Mapped[uuid.UUID]
    body: Mapped[str] = mapped_column(Text)


class AuditCaseCounter(CommonColumns, AuditBase):
    """Last case number used per hospital and year. Only changed by cases.numbering."""

    __tablename__ = "audit_case_counters"
    __table_args__ = (UniqueConstraint("tenant_id", "year"),)

    year: Mapped[int]
    last_number: Mapped[int] = mapped_column(default=0, server_default="0")
