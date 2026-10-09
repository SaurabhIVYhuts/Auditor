"""Corrective action API (module M12, AUD-032): create, list, detail, owner steps, verify, evidence.

Who sees which action is decided by action_visibility() (api.visibility): the audit team sees
actions of findings they can see; an auditee sees only their own. Hidden actions are 404.
The service enforces the rules (only the owner starts/submits, evidence before submit, the
verifier is not the owner); api.errors.run_action maps its errors.
"""
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from agents.audit.api.deps import require_permission
from agents.audit.api.errors import run_action
from agents.audit.api.evidence import evidence_out, upload_and_link
from agents.audit.api.findings import _visible_finding
from agents.audit.api.visibility import visible_actions
from agents.audit.models import CorrectiveAction, EvidenceType, LinkTarget
from agents.audit.permissions import has_permission
from agents.audit.schemas.action import ActionCreate, ActionDetailOut, ActionOut, VerifyIn
from agents.audit.schemas.case import EvidenceOut
from agents.audit.schemas.finding import FindingOut, NoteIn
from agents.audit.services.action_service import (
    WITH_OWNER_VALUES, create_action, return_action, start_action, submit_action, verify_action,
)
from agents.audit.services.case_service import _hospital_today
from agents.audit.services.evidence_service import evidence_for
from agents.audit.services.finding_service import close_finding
from shared.auth import CurrentUser
from shared.db import get_db

router = APIRouter(prefix="/audit", tags=["audit-actions"])
READ = ("action:read", "action:read_own")


def _visible_action(db: Session, user: CurrentUser, action_id: uuid.UUID) -> CorrectiveAction:
    action = db.scalar(visible_actions(user).where(CorrectiveAction.id == action_id))
    if action is None:
        raise HTTPException(404, detail="Action not found")
    return action


@router.post("/findings/{finding_id}/actions", response_model=ActionOut, status_code=201)
def create(finding_id: uuid.UUID, body: ActionCreate,
           user: CurrentUser = Depends(require_permission("action:write")), db: Session = Depends(get_db)):
    finding = _visible_finding(db, user, finding_id)
    return run_action(db, lambda: create_action(
        db, finding, body.description, body.owner_user_id, body.due_date, user.user_id, user.roles,
        owner_department_id=body.owner_department_id, required_evidence_type=body.required_evidence_type))


@router.get("/actions", response_model=list[ActionOut])
def register(status: str | None = None, finding_id: uuid.UUID | None = None, mine: bool = False,
             overdue_only: bool = False,
             user: CurrentUser = Depends(require_permission(*READ)), db: Session = Depends(get_db)):
    stmt = visible_actions(user)
    if status is not None:
        stmt = stmt.where(CorrectiveAction.status == status)
    if finding_id is not None:
        stmt = stmt.where(CorrectiveAction.finding_id == finding_id)
    if mine:
        stmt = stmt.where(CorrectiveAction.owner_user_id == user.user_id)
    if overdue_only:                                       # past due and still with the owner
        stmt = stmt.where(CorrectiveAction.due_date < _hospital_today(),
                          CorrectiveAction.status.in_(WITH_OWNER_VALUES))
    return db.scalars(stmt.order_by(CorrectiveAction.due_date, CorrectiveAction.action_number)).all()


@router.get("/actions/{action_id}", response_model=ActionDetailOut)
def detail(action_id: uuid.UUID, user: CurrentUser = Depends(require_permission(*READ)),
           db: Session = Depends(get_db)):
    action = _visible_action(db, user, action_id)
    evidence = evidence_for(db, user.tenant_id, LinkTarget.ACTION.value, action.id)
    return ActionDetailOut(**ActionOut.model_validate(action).model_dump(exclude={"allowed_next"}),
                           evidence=[evidence_out(db, e) for e in evidence])


@router.post("/actions/{action_id}/start", response_model=ActionOut)
def start(action_id: uuid.UUID, user: CurrentUser = Depends(require_permission("action:work")),
          db: Session = Depends(get_db)):
    action = _visible_action(db, user, action_id)
    return run_action(db, lambda: start_action(db, action, user.user_id))


@router.post("/actions/{action_id}/submit", response_model=ActionOut)
def submit(action_id: uuid.UUID, user: CurrentUser = Depends(require_permission("action:work")),
           db: Session = Depends(get_db)):
    action = _visible_action(db, user, action_id)
    return run_action(db, lambda: submit_action(db, action, user.user_id))


@router.post("/actions/{action_id}/verify", response_model=ActionOut)
def verify(action_id: uuid.UUID, body: VerifyIn | None = None,
           user: CurrentUser = Depends(require_permission("action:verify")), db: Session = Depends(get_db)):
    action = _visible_action(db, user, action_id)
    note = body.note if body else None
    return run_action(db, lambda: verify_action(db, action, user.user_id, user.roles, note))


@router.post("/actions/{action_id}/return", response_model=ActionOut)
def return_for_work(action_id: uuid.UUID, body: NoteIn,
                    user: CurrentUser = Depends(require_permission("action:verify")), db: Session = Depends(get_db)):
    action = _visible_action(db, user, action_id)
    return run_action(db, lambda: return_action(db, action, user.user_id, user.roles, body.note))


@router.post("/actions/{action_id}/evidence", response_model=EvidenceOut, status_code=201)
def upload_action_evidence(
    action_id: uuid.UUID,
    title: str = Form(...),
    file: UploadFile = File(...),
    evidence_type: str = Form(EvidenceType.DOCUMENT.value),
    contains_phi: bool = Form(False),
    user: CurrentUser = Depends(require_permission("evidence:write", "evidence:upload_own")),
    db: Session = Depends(get_db),
):
    """Upload evidence for an action; linked to the action AND its case.
    evidence:write may upload to any visible action; evidence:upload_own only to actions I own."""
    action = _visible_action(db, user, action_id)
    if not has_permission(user.roles, "evidence:write") and action.owner_user_id != user.user_id:
        raise HTTPException(404, detail="Action not found")
    return upload_and_link(db, user, file, title, evidence_type, contains_phi,
                           [(LinkTarget.ACTION.value, action.id), (LinkTarget.CASE.value, action.case_id)])


@router.post("/findings/{finding_id}/close", response_model=FindingOut)
def close(finding_id: uuid.UUID, user: CurrentUser = Depends(require_permission("action:verify")),
          db: Session = Depends(get_db)):
    finding = _visible_finding(db, user, finding_id)
    return run_action(db, lambda: close_finding(db, finding, user.user_id, user.roles))
