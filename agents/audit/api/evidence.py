"""Evidence API (module M8): list, upload, view, download, verify and supersede evidence.

Visibility: a user may see an evidence item only if it is linked to a case, a finding OR a
corrective action they can see (case_visibility / finding_visibility / action_visibility - the
same rules as those APIs). With only evidence:read_own (auditees) just the action route counts:
an action owner sees their own action's evidence and nothing else.
Otherwise 404. Errors go through api.errors.run_action: an integrity failure is COMMITTED first
(the alert and its log entry are kept); every other error rolls back.
"""
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session, aliased

from agents.audit.api.cases import _visible_case, case_visibility
from agents.audit.api.deps import require_permission
from agents.audit.api.errors import run_action
from agents.audit.api.visibility import action_visibility, finding_visibility
from agents.audit.models import (
    AuditCase, AuditEvidence, AuditEvidenceLink, AuditFinding, CorrectiveAction, EvidenceType, LinkTarget,
)
from agents.audit.permissions import has_permission
from agents.audit.schemas.case import EvidenceOut, SupersedeIn
from agents.audit.services.evidence_service import (
    evidence_for, link_evidence, read_evidence, supersede_evidence, upload_evidence, verify_evidence,
)
from shared.auth import CurrentUser
from shared.config import settings
from shared.db import get_db
from shared.documents import Document

router = APIRouter(prefix="/audit", tags=["audit-evidence"])


def _visible_evidence(db: Session, user: CurrentUser, evidence_id: uuid.UUID) -> AuditEvidence:
    """The evidence item if it is linked to a case, finding OR action this user may see; otherwise 404."""
    case_link, finding_link, action_link = (aliased(AuditEvidenceLink) for _ in range(3))
    via_case = exists(
        select(case_link.id)
        .join(AuditCase, AuditCase.id == case_link.target_id)
        .where(case_link.evidence_id == AuditEvidence.id, case_link.target_type == LinkTarget.CASE.value,
               AuditCase.tenant_id == user.tenant_id, AuditCase.is_deleted.is_(False), case_visibility(user))
    )
    via_finding = exists(
        select(finding_link.id)
        .join(AuditFinding, AuditFinding.id == finding_link.target_id)
        .join(AuditCase, AuditCase.id == AuditFinding.case_id)
        .where(finding_link.evidence_id == AuditEvidence.id, finding_link.target_type == LinkTarget.FINDING.value,
               finding_visibility(user))
    )
    via_action = exists(
        select(action_link.id)
        .join(CorrectiveAction, CorrectiveAction.id == action_link.target_id)
        .join(AuditFinding, AuditFinding.id == CorrectiveAction.finding_id)
        .join(AuditCase, AuditCase.id == AuditFinding.case_id)
        .where(action_link.evidence_id == AuditEvidence.id, action_link.target_type == LinkTarget.ACTION.value,
               action_visibility(user))
    )
    routes = [via_case, via_finding, via_action] if has_permission(user.roles, "evidence:read") else [via_action]
    evidence = db.scalar(select(AuditEvidence).where(
        AuditEvidence.id == evidence_id, AuditEvidence.tenant_id == user.tenant_id,
        AuditEvidence.is_deleted.is_(False), or_(*routes),
    ))
    if evidence is None:
        raise HTTPException(404, detail="Evidence not found")
    return evidence


def evidence_out(db: Session, evidence: AuditEvidence) -> EvidenceOut:
    document = db.get(Document, evidence.document_id) if evidence.document_id else None
    return EvidenceOut(
        id=evidence.id, title=evidence.title, evidence_type=evidence.evidence_type,
        source_system=evidence.source_system, sha256=evidence.sha256, status=evidence.status,
        superseded_reason=evidence.superseded_reason, contains_phi=evidence.contains_phi,
        captured_by=evidence.captured_by, captured_at=evidence.captured_at,
        filename=document.filename if document else None, is_snapshot=evidence.snapshot is not None,
    )


def upload_and_link(
    db: Session, user: CurrentUser, file: UploadFile, title: str, evidence_type: str, contains_phi: bool,
    targets: list[tuple[str, uuid.UUID]],
) -> EvidenceOut:
    """Store an uploaded file as evidence and link it to every target, in one transaction."""
    data = file.file.read(settings.document_max_bytes + 1)     # never read more than one byte past the limit

    def action() -> AuditEvidence:
        evidence = upload_evidence(
            db, user.tenant_id, title=title, filename=file.filename or "upload",
            content_type=file.content_type or "application/octet-stream", data=data,
            actor_id=user.user_id, evidence_type=evidence_type, contains_phi=contains_phi,
        )
        for target_type, target_id in targets:
            link_evidence(db, evidence, target_type, target_id, user.user_id)
        return evidence

    return evidence_out(db, run_action(db, action))


@router.get("/cases/{case_id}/evidence", response_model=list[EvidenceOut])
def list_case_evidence(case_id: uuid.UUID, user: CurrentUser = Depends(require_permission("evidence:read")),
                       db: Session = Depends(get_db)):
    case = _visible_case(db, user, case_id)
    return [evidence_out(db, e) for e in evidence_for(db, user.tenant_id, LinkTarget.CASE.value, case.id)]


@router.post("/cases/{case_id}/evidence", response_model=EvidenceOut, status_code=201)
def upload_case_evidence(
    case_id: uuid.UUID,
    title: str = Form(...),
    file: UploadFile = File(...),
    evidence_type: str = Form(EvidenceType.DOCUMENT.value),
    contains_phi: bool = Form(False),
    user: CurrentUser = Depends(require_permission("evidence:write")),
    db: Session = Depends(get_db),
):
    case = _visible_case(db, user, case_id)
    return upload_and_link(db, user, file, title, evidence_type, contains_phi, [(LinkTarget.CASE.value, case.id)])


READ = ("evidence:read", "evidence:read_own")      # read_own: _visible_evidence limits it to own actions


@router.get("/evidence/{evidence_id}", response_model=EvidenceOut)
def get_evidence(evidence_id: uuid.UUID, user: CurrentUser = Depends(require_permission(*READ)),
                 db: Session = Depends(get_db)):
    return evidence_out(db, _visible_evidence(db, user, evidence_id))


@router.get("/evidence/{evidence_id}/download")
def download_evidence(evidence_id: uuid.UUID, user: CurrentUser = Depends(require_permission(*READ)),
                      db: Session = Depends(get_db)):
    evidence = _visible_evidence(db, user, evidence_id)
    content = run_action(db, lambda: read_evidence(db, evidence, user.user_id))   # re-checks the fingerprint
    if isinstance(content, dict):
        return content                                   # a snapshot: the frozen record as JSON
    document = db.get(Document, evidence.document_id)
    return Response(content=content, media_type=document.content_type, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(document.filename)}"})


@router.post("/evidence/{evidence_id}/verify")
def verify(evidence_id: uuid.UUID, user: CurrentUser = Depends(require_permission("evidence:read")),
           db: Session = Depends(get_db)):
    evidence = _visible_evidence(db, user, evidence_id)
    return {"ok": run_action(db, lambda: verify_evidence(db, evidence, user.user_id))}


@router.post("/evidence/{evidence_id}/supersede", response_model=EvidenceOut)
def supersede(evidence_id: uuid.UUID, body: SupersedeIn,
              user: CurrentUser = Depends(require_permission("evidence:supersede")), db: Session = Depends(get_db)):
    evidence = _visible_evidence(db, user, evidence_id)
    replacement = _visible_evidence(db, user, body.replaced_by) if body.replaced_by else None
    return evidence_out(db, run_action(db, lambda: supersede_evidence(
        db, evidence, body.reason, user.user_id, user.roles, replacement)))
