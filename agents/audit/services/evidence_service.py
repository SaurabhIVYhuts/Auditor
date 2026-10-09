"""Evidence service (AUD-030): capture, link, read, verify and supersede evidence.

Every item carries the SHA-256 taken at capture and is re-checked before anyone reads it.
Every step is written to the audit log (entity_type "audit_evidence") - that is the chain of
custody. Evidence is never deleted, only SUPERSEDED with a reason. Each function checks that
evidence, documents and targets all belong to the same hospital. Flushes, never commits.
"""
import hashlib
import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.audit.findings.state_machine import CONFIRMED_STATUSES
from agents.audit.models import (
    AuditCase, AuditEvidence, AuditEvidenceLink, AuditFinding, AuditSourceRecord, EvidenceSource,
    EvidenceStatus, EvidenceType, LinkTarget,
)
from agents.audit.permissions import AuditRole, has_permission
from agents.audit.services.case_service import ManagerApprovalRequired
from agents.audit.services.snapshot_service import compute_checksum
from shared.audit_log import log_action
from shared.documents import read_document, store_document
from shared.notifications import notify_role

EVIDENCE_ENTITY = "audit_evidence"
REVIEW_PERMISSION = "finding:confirm"          # held by the Audit Manager role only

# Which snapshot field holds the human-readable number, per record type (for titles).
NUMBER_FIELDS = {"purchase_order": "po_number", "grn": "grn_number", "invoice": "invoice_number",
                 "payment": "payment_ref", "vendor": "vendor_id"}


class EvidenceIntegrityError(Exception):
    """The evidence no longer matches the fingerprint taken at capture."""


def _log(db: Session, evidence: AuditEvidence, actor_id: uuid.UUID | None, action: str, **details) -> None:
    log_action(db, evidence.tenant_id, actor_id, action, EVIDENCE_ENTITY, evidence.id, details)


def _same_hospital(evidence: AuditEvidence, tenant_id: uuid.UUID, what: str) -> None:
    if evidence.tenant_id != tenant_id:
        raise ValueError(f"The {what} belongs to another hospital")


def upload_evidence(
    db: Session, tenant_id: uuid.UUID, *, title: str, filename: str, content_type: str, data: bytes,
    actor_id: uuid.UUID | None, evidence_type: str = EvidenceType.DOCUMENT.value,
    source_system: str = EvidenceSource.MANUAL.value, contains_phi: bool = False,
) -> AuditEvidence:
    """Store an uploaded file (checked, fingerprinted, written once) as evidence."""
    title = (title or "").strip()
    if not title:
        raise ValueError("Evidence needs a title")
    EvidenceType(evidence_type)
    EvidenceSource(source_system)
    document = store_document(db, tenant_id, filename, content_type, data, uploaded_by=actor_id)
    evidence = AuditEvidence(
        tenant_id=tenant_id, title=title[:200], evidence_type=evidence_type, source_system=source_system,
        document_id=document.id, sha256=document.sha256, captured_by=actor_id, contains_phi=contains_phi,
        created_by=actor_id,
    )
    db.add(evidence)
    db.flush()
    _log(db, evidence, actor_id, "evidence.uploaded", document_id=str(document.id),
         filename=document.filename, sha256=document.sha256)
    return evidence


def snapshot_evidence(
    db: Session, source_record: AuditSourceRecord, title: str, actor_id: uuid.UUID | None = None,
) -> AuditEvidence:
    """Evidence from a hub snapshot: the same frozen content and the same checksum."""
    if compute_checksum(source_record.snapshot) != source_record.checksum:
        raise EvidenceIntegrityError("The source record no longer matches its checksum; it cannot be used")
    evidence = AuditEvidence(
        tenant_id=source_record.tenant_id, title=title[:200], evidence_type=EvidenceType.TRANSACTION.value,
        source_system=source_record.source_system,
        source_ref={"entity_type": source_record.entity_type, "entity_id": str(source_record.entity_id),
                    "source_record_id": str(source_record.id)},
        snapshot=dict(source_record.snapshot), sha256=source_record.checksum, captured_by=actor_id,
        created_by=actor_id,
    )
    db.add(evidence)
    db.flush()
    _log(db, evidence, actor_id, "evidence.snapshot_captured", source_record_id=str(source_record.id),
         sha256=evidence.sha256)
    return evidence


TARGET_MODELS = {LinkTarget.CASE: AuditCase, LinkTarget.FINDING: AuditFinding}


def _check_target(db: Session, tenant_id: uuid.UUID, target_type: str, target_id: uuid.UUID) -> None:
    target_type = LinkTarget(target_type)
    model = TARGET_MODELS.get(target_type)
    if model is None:
        raise NotImplementedError("Corrective actions: the table arrives in Step 25")
    target = db.get(model, target_id)
    if target is None or target.tenant_id != tenant_id or target.is_deleted:
        raise ValueError(f"{target_type.value.capitalize()} not found for this hospital")


def link_evidence(
    db: Session, evidence: AuditEvidence, target_type: str, target_id: uuid.UUID, actor_id: uuid.UUID | None,
) -> AuditEvidenceLink:
    """Link evidence to a case (findings/actions later). Linking twice returns the existing link."""
    if evidence.status == EvidenceStatus.SUPERSEDED.value:
        raise ValueError("Superseded evidence cannot be linked")
    _check_target(db, evidence.tenant_id, target_type, target_id)
    existing = db.scalar(select(AuditEvidenceLink).where(
        AuditEvidenceLink.evidence_id == evidence.id, AuditEvidenceLink.target_type == target_type,
        AuditEvidenceLink.target_id == target_id,
    ))
    if existing is not None:
        return existing
    link = AuditEvidenceLink(tenant_id=evidence.tenant_id, evidence_id=evidence.id, target_type=target_type,
                             target_id=target_id, linked_by=actor_id, created_by=actor_id)
    db.add(link)
    db.flush()
    _log(db, evidence, actor_id, "evidence.linked", target_type=target_type, target_id=str(target_id))
    return link


def evidence_for(db: Session, tenant_id: uuid.UUID, target_type: str, target_id: uuid.UUID) -> list[AuditEvidence]:
    """Evidence linked to one case/finding/action of this hospital, newest first (superseded included)."""
    return list(db.scalars(
        select(AuditEvidence)
        .join(AuditEvidenceLink, AuditEvidenceLink.evidence_id == AuditEvidence.id)
        .where(AuditEvidenceLink.tenant_id == tenant_id, AuditEvidenceLink.target_type == target_type,
               AuditEvidenceLink.target_id == target_id, AuditEvidence.is_deleted.is_(False))
        .order_by(AuditEvidence.captured_at.desc(), AuditEvidenceLink.created_at.desc())
    ))


def _content_if_intact(db: Session, evidence: AuditEvidence) -> tuple[bool, bytes | dict | None]:
    """(matches fingerprint, content). A missing file counts as not intact."""
    if evidence.document_id is not None:
        try:
            found = read_document(db, evidence.tenant_id, evidence.document_id)
        except FileNotFoundError:
            return False, None
        if found is None:
            return False, None
        _, data = found
        return hashlib.sha256(data).hexdigest() == evidence.sha256, data
    return compute_checksum(evidence.snapshot) == evidence.sha256, evidence.snapshot


def _integrity_alert(db: Session, evidence: AuditEvidence, actor_id: uuid.UUID | None) -> None:
    _log(db, evidence, actor_id, "evidence.integrity_failed", sha256=evidence.sha256)
    notify_role(db, evidence.tenant_id, AuditRole.AUDIT_MANAGER.value, "evidence.integrity_failed",
                "Evidence integrity check failed", evidence.title, EVIDENCE_ENTITY, evidence.id)


def read_evidence(db: Session, evidence: AuditEvidence, actor_id: uuid.UUID | None) -> bytes | dict:
    """The evidence content (file bytes or snapshot), after re-checking its fingerprint.

    On a mismatch the alert (log + Audit Manager notification) is flushed BEFORE the error is
    raised: the caller must commit it, not roll it back, before reporting the error.
    """
    intact, content = _content_if_intact(db, evidence)
    if not intact:
        _integrity_alert(db, evidence, actor_id)
        raise EvidenceIntegrityError(f"Evidence '{evidence.title}' does not match its fingerprint")
    _log(db, evidence, actor_id, "evidence.viewed")
    return content


def verify_evidence(db: Session, evidence: AuditEvidence, actor_id: uuid.UUID | None) -> bool:
    """Re-check the fingerprint. A failed check also raises the integrity alert."""
    intact, _ = _content_if_intact(db, evidence)
    _log(db, evidence, actor_id, "evidence.verified", ok=intact)
    if not intact:
        _integrity_alert(db, evidence, actor_id)
    return intact


def _supports_confirmed_finding(db: Session, evidence: AuditEvidence) -> bool:
    """True if a confirmed finding (CONFIRMED or later) rests on this evidence."""
    return db.scalar(
        select(AuditFinding.id)
        .join(AuditEvidenceLink, AuditEvidenceLink.target_id == AuditFinding.id)
        .where(AuditEvidenceLink.evidence_id == evidence.id,
               AuditEvidenceLink.target_type == LinkTarget.FINDING.value,
               AuditFinding.status.in_(sorted(CONFIRMED_STATUSES)))
        .limit(1)
    ) is not None


def supersede_evidence(
    db: Session, evidence: AuditEvidence, reason: str, actor_id: uuid.UUID | None,
    actor_roles: Iterable[str], replaced_by: AuditEvidence | None = None,
) -> AuditEvidence:
    """Mark evidence SUPERSEDED (never deleted). A reason is required.

    Evidence behind a confirmed finding can only be superseded by an Audit Manager.
    """
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("A reason is required to supersede evidence")
    if evidence.status == EvidenceStatus.SUPERSEDED.value:
        raise ValueError("This evidence is already superseded")
    if _supports_confirmed_finding(db, evidence) and not has_permission(actor_roles, REVIEW_PERMISSION):
        raise ManagerApprovalRequired("Only an Audit Manager can supersede evidence of a confirmed finding")
    if replaced_by is not None:
        _same_hospital(replaced_by, evidence.tenant_id, "replacement evidence")
        if replaced_by.id == evidence.id or replaced_by.status != EvidenceStatus.ACTIVE.value:
            raise ValueError("The replacement must be a different, ACTIVE evidence item")
    evidence.status = EvidenceStatus.SUPERSEDED.value
    evidence.superseded_reason = reason
    evidence.superseded_by = replaced_by.id if replaced_by else None
    evidence.updated_by = actor_id
    db.flush()
    _log(db, evidence, actor_id, "evidence.superseded", reason=reason,
         replaced_by=str(replaced_by.id) if replaced_by else None)
    return evidence


def snapshot_title(source_record: AuditSourceRecord) -> str:
    """e.g. "Purchase order PO-DEMO-1 (system snapshot)"."""
    number = source_record.snapshot.get(NUMBER_FIELDS.get(source_record.entity_type, ""), "")
    kind = source_record.entity_type.replace("_", " ").capitalize()
    return f"{kind} {number} (system snapshot)".replace("  ", " ")


def capture_for_case(db: Session, source_record: AuditSourceRecord, case: AuditCase) -> AuditEvidence:
    """System step: snapshot evidence of a record, linked to a case. One evidence item per record."""
    evidence = db.scalar(select(AuditEvidence).where(
        AuditEvidence.tenant_id == source_record.tenant_id,
        AuditEvidence.source_ref.contains({"source_record_id": str(source_record.id)}),
        AuditEvidence.status == EvidenceStatus.ACTIVE.value,
    ).limit(1))
    if evidence is None:
        evidence = snapshot_evidence(db, source_record, snapshot_title(source_record))
    link_evidence(db, evidence, LinkTarget.CASE.value, case.id, actor_id=None)
    return evidence
