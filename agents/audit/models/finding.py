"""Audit findings (module M11, AUD-031): human-confirmed observations with evidence and an owner.

Structured like an audit report entry: Condition (what was found), Criteria (rule/policy),
Cause, Effect (impact), Recommendation. Status values come from the finding state machine.
Numbers are FND-YYYY-NNNNN per hospital (cases.numbering, prefix FND).
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from agents.audit.findings.state_machine import FindingStatus
from agents.audit.models.base import AuditBase
from agents.audit.models.rule import Severity, _allowed
from shared.models import CommonColumns


class AuditFinding(CommonColumns, AuditBase):
    __tablename__ = "audit_findings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "finding_number"),         # unique per hospital
        CheckConstraint(_allowed("status", FindingStatus), name="status"),
        CheckConstraint(_allowed("risk_level", Severity), name="risk_level"),   # NULL is allowed
        Index("ix_audit_findings_tenant_status", "tenant_id", "status"),
        Index("ix_audit_findings_tenant_case", "tenant_id", "case_id"),
        Index("ix_audit_findings_tenant_owner", "tenant_id", "owner_user_id"),
        Index("ix_audit_findings_tenant_due", "tenant_id", "due_date"),
    )

    finding_number: Mapped[str] = mapped_column(String(20))      # e.g. FND-2026-00007
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audit.audit_cases.id"))
    title: Mapped[str] = mapped_column(String(200))
    # The structured finding. May be incomplete while DRAFT; required before submit (finding service).
    condition: Mapped[str | None] = mapped_column(Text)          # what was found
    criteria: Mapped[str | None] = mapped_column(Text)           # the rule / policy it breaks
    cause: Mapped[str | None] = mapped_column(Text)
    effect: Mapped[str | None] = mapped_column(Text)
    recommendation: Mapped[str | None] = mapped_column(Text)
    financial_impact: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))   # in rupees, if known
    risk_level: Mapped[str | None] = mapped_column(String(10))
    owner_user_id: Mapped[uuid.UUID | None]
    owner_department_id: Mapped[uuid.UUID | None]
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default=FindingStatus.DRAFT.value,
                                        server_default=FindingStatus.DRAFT.value)
    management_response: Mapped[str | None] = mapped_column(Text)
    ai_drafted_fields: Mapped[list[str]] = mapped_column(ARRAY(String(30)), default=list,
                                                         server_default=text("'{}'"))   # which fields began as AI drafts
    dismiss_reason: Mapped[str | None] = mapped_column(Text)
    submitted_by: Mapped[uuid.UUID | None]
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[uuid.UUID | None]
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    previous_finding_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("audit.audit_findings.id"))  # repeat finding
