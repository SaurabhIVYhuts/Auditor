"""Evidence API (module M8): list, upload, view, download, verify and supersede evidence.

Visibility: a user may see an evidence item only if it is linked to a case they can see
(case_visibility from the case API - one rule for both). Otherwise 404.
An integrity failure is COMMITTED before the error is returned, so the alert and its log
entry are kept; every other error rolls back.
"""
import uuid
from collections.abc import Callable
from typing import TypeVar
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.audit.api.cases import _visible_case, case_visibility
from agents.audit.api.deps import require_permission
from agents.audit.models import AuditCase, AuditEvidence, AuditEvidenceLink, EvidenceType, LinkTarget
from agents.audit.schemas.case import EvidenceOut, SupersedeIn
from agents.audit.services.evidence_service import (
    EvidenceIntegrityError, evidence_for, link_evidence, read_evidence, supersede_evidence, upload_evidence,
    verify_evidence,
)
from shared.auth import CurrentUser
from shared.config import settings
from shared.db import get_db
from shared.documents import Document

router = APIRouter(prefix="/audit", tags=["audit-evidence"])
T = TypeVar("T")


def _visible_evidence(db: Session, user: CurrentUser, evidence_id: uuid.UUID) -> AuditEvidence:
    """The evidence item if it is linked to at least one case this user may see; otherwise 404."""
    evidence = db.scalar(
        select(AuditEvidence)
        .join(AuditEvidenceLink, AuditEvidenceLink.evidence_id == AuditEvidence.id)
        .join(AuditCase, AuditCase.id == AuditEvidenceLink.target_id)
        .where(
            AuditEvidence.id == evidence_id, AuditEvidence.tenant_id == user.tenant_id,
            AuditEvidence.is_deleted.is_(False),
            AuditEvidenceLink.target_type == LinkTarget.CASE.value,
            AuditCase.tenant_id == user.tenant_id, AuditCase.is_deleted.is_(False),
            case_visibility(user),
        )
        .limit(1)
    )
    if evidence is None:
        raise HTTPException(404, detail="Evidence not found")
    return evidence


def _out(db: Session, evidence: AuditEvidence) -> EvidenceOut:
    document = db.get(Document, evidence.document_id) if evidence.document_id else None
    return EvidenceOut(
        id=evidence.id, title=evidence.title, evidence_type=evidence.evidence_type,
        source_system=evidence.source_system, sha256=evidence.sha256, status=evidence.status,
        superseded_reason=evidence.superseded_reason, contains_phi=evidence.contains_phi,
        captured_by=evidence.captured_by, captured_at=evidence.captured_at,
        filename=document.filename if document else None, is_snapshot=evidence.snapshot is not None,
    )


def _run(db: Session, action: Callable[[], T]) -> T:
    """Commit on success. Integrity failure: commit (keep the alert) then 409. Other errors: roll back."""
    try:
        result = action()
        db.commit()
        return result
    except EvidenceIntegrityError as err:
        db.commit()                                    # the alert and its log entry must survive
        raise HTTPException(409, detail={"code": "INTEGRITY_FAILED", "message": str(err)}) from None
    except NotImplementedError as err:
        db.rollback()
        raise HTTPException(422, detail={"message": str(err)}) from None
    except ValueError as err:                          # includes DocumentRejected (size, type, empty)
        db.rollback()
        raise HTTPException(422, detail={"message": str(err)}) from None


@router.get("/cases/{case_id}/evidence", response_model=list[EvidenceOut])
def list_case_evidence(case_id: uuid.UUID, user: CurrentUser = Depends(require_permission("evidence:read")),
                       db: Session = Depends(get_db)):
    case = _visible_case(db, user, case_id)
    return [_out(db, e) for e in evidence_for(db, user.tenant_id, LinkTarget.CASE.value, case.id)]


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
    data = file.file.read(settings.document_max_bytes + 1)      # never read more than one byte past the limit

    def action() -> AuditEvidence:
        evidence = upload_evidence(
            db, user.tenant_id, title=title, filename=file.filename or "upload",
            content_type=file.content_type or "application/octet-stream", data=data,
            actor_id=user.user_id, evidence_type=evidence_type, contains_phi=contains_phi,
        )
        link_evidence(db, evidence, LinkTarget.CASE.value, case.id, user.user_id)
        return evidence

    return _out(db, _run(db, action))


@router.get("/evidence/{evidence_id}", response_model=EvidenceOut)
def get_evidence(evidence_id: uuid.UUID, user: CurrentUser = Depends(require_permission("evidence:read")),
                 db: Session = Depends(get_db)):
    return _out(db, _visible_evidence(db, user, evidence_id))


@router.get("/evidence/{evidence_id}/download")
def download_evidence(evidence_id: uuid.UUID, user: CurrentUser = Depends(require_permission("evidence:read")),
                      db: Session = Depends(get_db)):
    evidence = _visible_evidence(db, user, evidence_id)
    content = _run(db, lambda: read_evidence(db, evidence, user.user_id))   # re-checks the fingerprint
    if isinstance(content, dict):
        return content                                   # a snapshot: the frozen record as JSON
    document = db.get(Document, evidence.document_id)
    return Response(content=content, media_type=document.content_type, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(document.filename)}"})


@router.post("/evidence/{evidence_id}/verify")
def verify(evidence_id: uuid.UUID, user: CurrentUser = Depends(require_permission("evidence:read")),
           db: Session = Depends(get_db)):
    evidence = _visible_evidence(db, user, evidence_id)
    return {"ok": _run(db, lambda: verify_evidence(db, evidence, user.user_id))}


@router.post("/evidence/{evidence_id}/supersede", response_model=EvidenceOut)
def supersede(evidence_id: uuid.UUID, body: SupersedeIn,
              user: CurrentUser = Depends(require_permission("evidence:supersede")), db: Session = Depends(get_db)):
    evidence = _visible_evidence(db, user, evidence_id)
    replacement = _visible_evidence(db, user, body.replaced_by) if body.replaced_by else None
    return _out(db, _run(db, lambda: supersede_evidence(db, evidence, body.reason, user.user_id, replacement)))
