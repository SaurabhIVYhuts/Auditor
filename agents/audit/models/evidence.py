"""Evidence (module M8, AUD-030): tamper-evident items linked to cases, findings and actions.

An evidence item is EITHER an uploaded document (document_id) OR a frozen copy of a system
record (snapshot) - never both, never neither. sha256 is the fingerprint taken at capture.
Evidence is never deleted: it can only be marked SUPERSEDED, with a reason.

Chain of custody (upload, view, download, link, supersede, verify) is written to the shared
append-only audit log with entity_type "audit_evidence" - there is no separate access-log table.
"""
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CHAR, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, false, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agents.audit.models.base import AuditBase
from agents.audit.models.rule import _allowed
from shared.documents import Document
from shared.models import CommonColumns


class EvidenceType(StrEnum):
    DOCUMENT = "DOCUMENT"
    TRANSACTION = "TRANSACTION"
    EMAIL = "EMAIL"
    APPROVAL = "APPROVAL"
    LOG = "LOG"
    ATTACHMENT = "ATTACHMENT"
    CHECKLIST = "CHECKLIST"


class EvidenceSource(StrEnum):
    PROCUREMENT = "procurement"
    INSURANCE = "insurance"
    ERP = "erp"
    HIS = "his"
    MANUAL = "manual"


class EvidenceStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class LinkTarget(StrEnum):
    CASE = "CASE"
    FINDING = "FINDING"
    ACTION = "ACTION"


class AuditEvidence(CommonColumns, AuditBase):
    __tablename__ = "audit_evidence"
    __table_args__ = (
        CheckConstraint(_allowed("evidence_type", EvidenceType), name="evidence_type"),
        CheckConstraint(_allowed("source_system", EvidenceSource), name="source_system"),
        CheckConstraint(_allowed("status", EvidenceStatus), name="status"),
        CheckConstraint("(document_id IS NULL) <> (snapshot IS NULL)", name="one_source"),
        Index("ix_audit_evidence_tenant_status", "tenant_id", "status"),
    )

    title: Mapped[str] = mapped_column(String(200))
    evidence_type: Mapped[str] = mapped_column(String(15))
    source_system: Mapped[str] = mapped_column(String(15))
    source_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONB)   # {entity_type, entity_id, url}
    # Points at the documents table of the shared store (a different model base, so the column itself).
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(Document.__table__.c.id))
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)     # record content at capture
    sha256: Mapped[str] = mapped_column(CHAR(64))
    captured_by: Mapped[uuid.UUID | None]
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    contains_phi: Mapped[bool] = mapped_column(default=False, server_default=false())   # mask previews
    status: Mapped[str] = mapped_column(String(10), default=EvidenceStatus.ACTIVE.value,
                                        server_default=EvidenceStatus.ACTIVE.value)
    superseded_reason: Mapped[str | None] = mapped_column(Text)
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("audit.audit_evidence.id"))
    ai_summary: Mapped[str | None] = mapped_column(Text)              # labelled AI; never replaces the original


class AuditEvidenceLink(CommonColumns, AuditBase):
    """Links one evidence item to a case, finding or corrective action."""

    __tablename__ = "audit_evidence_links"
    __table_args__ = (
        UniqueConstraint("evidence_id", "target_type", "target_id"),
        CheckConstraint(_allowed("target_type", LinkTarget), name="target_type"),
        Index("ix_audit_evidence_links_target", "tenant_id", "target_type", "target_id"),
    )

    evidence_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audit.audit_evidence.id"), index=True)
    target_type: Mapped[str] = mapped_column(String(10))
    target_id: Mapped[uuid.UUID]
    linked_by: Mapped[uuid.UUID | None]
