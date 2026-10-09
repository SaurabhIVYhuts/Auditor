"""Finding API (module M11): create, register, detail, edit, submit, review, evidence, timeline.

Who sees which finding is decided by finding_visibility() (api.visibility) - used by the list,
the detail and every action. Hidden findings are 404. The service enforces the rules (evidence
before submit, Audit Manager + maker-checker to confirm); api.errors.run_action maps its errors.
"""
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.audit.api.cases import _visible_case
from agents.audit.api.deps import require_permission
from agents.audit.api.errors import run_action
from agents.audit.api.evidence import _visible_evidence, evidence_out, upload_and_link
from agents.audit.api.visibility import visible_findings
from agents.audit.models import AuditEvidenceLink, AuditFinding, EvidenceType, LinkTarget
from agents.audit.permissions import has_permission
from agents.audit.schemas.case import EvidenceOut, TimelineEntryOut
from agents.audit.schemas.finding import (
    ConfirmIn, EvidenceLinkIn, FindingCreate, FindingDetailOut, FindingOut, FindingUpdate, NoteIn, ReasonIn,
)
from agents.audit.services.evidence_service import evidence_for, link_evidence
from agents.audit.services.finding_service import (
    FINDING_ENTITY, confirm_finding, create_finding, dismiss_finding, return_finding, submit_finding,
    update_finding,
)
from shared.audit_log import list_for_entity
from shared.auth import CurrentUser
from shared.db import get_db

router = APIRouter(prefix="/audit", tags=["audit-findings"])
READ = ("finding:read", "finding:read_own")


def _visible_finding(db: Session, user: CurrentUser, finding_id: uuid.UUID) -> AuditFinding:
    finding = db.scalar(visible_findings(user).where(AuditFinding.id == finding_id))
    if finding is None:
        raise HTTPException(404, detail="Finding not found")
    return finding


@router.post("/cases/{case_id}/findings", response_model=FindingOut, status_code=201)
def create(case_id: uuid.UUID, body: FindingCreate,
           user: CurrentUser = Depends(require_permission("finding:write")), db: Session = Depends(get_db)):
    case = _visible_case(db, user, case_id)
    fields = body.model_dump(include=body.model_fields_set - {"title"})
    return run_action(db, lambda: create_finding(db, case, body.title, user.user_id, **fields))


@router.get("/findings", response_model=list[FindingOut])
def register(status: str | None = None, case_id: uuid.UUID | None = None, owner_user_id: uuid.UUID | None = None,
             risk_level: str | None = None,
             user: CurrentUser = Depends(require_permission(*READ)), db: Session = Depends(get_db)):
    stmt = visible_findings(user)
    for column, value in ((AuditFinding.status, status), (AuditFinding.case_id, case_id),
                          (AuditFinding.owner_user_id, owner_user_id), (AuditFinding.risk_level, risk_level)):
        if value is not None:
            stmt = stmt.where(column == value)
    return db.scalars(stmt.order_by(AuditFinding.created_at.desc(), AuditFinding.finding_number.desc())).all()


@router.get("/findings/{finding_id}", response_model=FindingDetailOut)
def detail(finding_id: uuid.UUID, user: CurrentUser = Depends(require_permission(*READ)),
           db: Session = Depends(get_db)):
    finding = _visible_finding(db, user, finding_id)
    evidence = (evidence_for(db, user.tenant_id, LinkTarget.FINDING.value, finding.id)
                if has_permission(user.roles, "evidence:read") else [])
    return FindingDetailOut(**FindingOut.model_validate(finding).model_dump(exclude={"allowed_next"}),
                            evidence=[evidence_out(db, e) for e in evidence])


@router.put("/findings/{finding_id}", response_model=FindingOut)
def edit(finding_id: uuid.UUID, body: FindingUpdate,
         user: CurrentUser = Depends(require_permission("finding:write")), db: Session = Depends(get_db)):
    finding = _visible_finding(db, user, finding_id)
    fields = body.model_dump(include=body.model_fields_set)
    return run_action(db, lambda: update_finding(db, finding, user.user_id, **fields))


@router.post("/findings/{finding_id}/submit", response_model=FindingOut)
def submit(finding_id: uuid.UUID, user: CurrentUser = Depends(require_permission("finding:write")),
           db: Session = Depends(get_db)):
    finding = _visible_finding(db, user, finding_id)
    return run_action(db, lambda: submit_finding(db, finding, user.user_id))


@router.post("/findings/{finding_id}/confirm", response_model=FindingOut)
def confirm(finding_id: uuid.UUID, body: ConfirmIn,
            user: CurrentUser = Depends(require_permission("finding:write")), db: Session = Depends(get_db)):
    finding = _visible_finding(db, user, finding_id)
    return run_action(db, lambda: confirm_finding(db, finding, user.user_id, user.roles,
                                                  owner_user_id=body.owner_user_id, due_date=body.due_date))


@router.post("/findings/{finding_id}/return", response_model=FindingOut)
def return_for_changes(finding_id: uuid.UUID, body: NoteIn,
                       user: CurrentUser = Depends(require_permission("finding:write")), db: Session = Depends(get_db)):
    finding = _visible_finding(db, user, finding_id)
    return run_action(db, lambda: return_finding(db, finding, user.user_id, user.roles, body.note))


@router.post("/findings/{finding_id}/dismiss", response_model=FindingOut)
def dismiss(finding_id: uuid.UUID, body: ReasonIn,
            user: CurrentUser = Depends(require_permission("finding:write")), db: Session = Depends(get_db)):
    finding = _visible_finding(db, user, finding_id)
    return run_action(db, lambda: dismiss_finding(db, finding, user.user_id, user.roles, body.reason))


@router.post("/findings/{finding_id}/evidence", response_model=EvidenceOut, status_code=201)
def upload_finding_evidence(
    finding_id: uuid.UUID,
    title: str = Form(...),
    file: UploadFile = File(...),
    evidence_type: str = Form(EvidenceType.DOCUMENT.value),
    contains_phi: bool = Form(False),
    user: CurrentUser = Depends(require_permission("evidence:write")),
    db: Session = Depends(get_db),
):
    """Upload evidence for a finding; it is linked to the finding AND to the finding's case."""
    finding = _visible_finding(db, user, finding_id)
    return upload_and_link(db, user, file, title, evidence_type, contains_phi,
                           [(LinkTarget.FINDING.value, finding.id), (LinkTarget.CASE.value, finding.case_id)])


@router.post("/findings/{finding_id}/evidence-links", response_model=EvidenceOut)
def link_case_evidence(finding_id: uuid.UUID, body: EvidenceLinkIn,
                       user: CurrentUser = Depends(require_permission("evidence:write")),
                       db: Session = Depends(get_db)):
    """Link evidence that is already on the finding's case."""
    finding = _visible_finding(db, user, finding_id)
    evidence = _visible_evidence(db, user, body.evidence_id)
    on_case = db.scalar(select(AuditEvidenceLink.id).where(
        AuditEvidenceLink.evidence_id == evidence.id, AuditEvidenceLink.target_type == LinkTarget.CASE.value,
        AuditEvidenceLink.target_id == finding.case_id))
    if on_case is None:
        raise HTTPException(422, detail={"message": "Only evidence of this finding's case can be linked"})
    run_action(db, lambda: link_evidence(db, evidence, LinkTarget.FINDING.value, finding.id, user.user_id))
    return evidence_out(db, evidence)


@router.get("/findings/{finding_id}/timeline", response_model=list[TimelineEntryOut])
def timeline(finding_id: uuid.UUID, user: CurrentUser = Depends(require_permission(*READ)),
             db: Session = Depends(get_db)):
    finding = _visible_finding(db, user, finding_id)
    return list_for_entity(db, finding.tenant_id, FINDING_ENTITY, finding.id)
