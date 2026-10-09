"""Corrective actions (module M12, AUD-032): the fixes that confirmed findings lead to.

Each action has one owner (usually in the audited department) and a due date. The owner
works on it and submits evidence; an auditor who is NOT the owner verifies it.
Numbers are ACT-YYYY-NNNNN per hospital (cases.numbering, prefix ACT).
"""
import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint, Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, select, text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, column_property, mapped_column

from agents.audit.actions.state_machine import ActionStatus
from agents.audit.models.base import AuditBase
from agents.audit.models.case import AuditCase
from agents.audit.models.finding import AuditFinding
from agents.audit.models.rule import _allowed
from shared.models import CommonColumns

ACTION_ENTITY = "corrective_action"     # entity_type in the audit log

_finding = AuditFinding.__table__.alias("action_finding")
_case = AuditCase.__table__.alias("action_case")


class CorrectiveAction(CommonColumns, AuditBase):
    __tablename__ = "corrective_actions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "action_number"),          # unique per hospital
        CheckConstraint(_allowed("status", ActionStatus), name="status"),
        CheckConstraint("extension_count >= 0", name="extension_count"),
        Index("ix_corrective_actions_tenant_status", "tenant_id", "status"),
        Index("ix_corrective_actions_tenant_owner", "tenant_id", "owner_user_id"),
        Index("ix_corrective_actions_tenant_due", "tenant_id", "due_date"),
        Index("ix_corrective_actions_tenant_finding", "tenant_id", "finding_id"),
    )

    action_number: Mapped[str] = mapped_column(String(20))      # e.g. ACT-2026-00004
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audit.audit_findings.id"))
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audit.audit_cases.id"))
    # read-only, for screens: the finding's and case's numbers (loaded with the action, not stored).
    # Aliases, so queries that already join these tables do not swallow the subqueries.
    finding_number: Mapped[str] = column_property(
        select(_finding.c.finding_number).where(_finding.c.id == finding_id).scalar_subquery())
    case_number: Mapped[str] = column_property(
        select(_case.c.case_number).where(_case.c.id == case_id).scalar_subquery())
    description: Mapped[str] = mapped_column(Text)
    owner_user_id: Mapped[uuid.UUID]
    owner_department_id: Mapped[uuid.UUID | None]
    due_date: Mapped[date] = mapped_column(Date)
    required_evidence_type: Mapped[str | None] = mapped_column(String(15))
    status: Mapped[str] = mapped_column(String(12), default=ActionStatus.OPEN.value,
                                        server_default=ActionStatus.OPEN.value)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[uuid.UUID | None]
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_note: Mapped[str | None] = mapped_column(Text)
    return_note: Mapped[str | None] = mapped_column(Text)
    extension_count: Mapped[int] = mapped_column(default=0, server_default="0")
    reminders_sent: Mapped[list[str]] = mapped_column(ARRAY(String(20)), default=list,
                                                      server_default=text("'{}'"))   # e.g. "due-7", "overdue"
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
