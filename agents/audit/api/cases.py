"""Case API (module M1): list, detail, timeline, comments, and manual cases.

Who sees which case is decided in ONE place, case_visibility(), used by the list and by every
single-case endpoint. A case the user may not see looks exactly like one that does not exist (404).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import ColumnElement, and_, false, or_, select, true
from sqlalchemy.orm import Session

from agents.audit.api.deps import require_permission
from agents.audit.models import AuditCase, AuditCaseException, AuditException, AuditRule, CaseSource, Severity
from agents.audit.permissions import permissions_for
from agents.audit.schemas.case import (
    CaseDetailOut, CaseExceptionOut, CaseOut, CommentOut, ManualCaseCreate, TimelineEntryOut,
)
from agents.audit.services.case_service import case_comments, case_timeline, list_cases, open_case
from shared.auth import CurrentUser
from shared.db import get_db

router = APIRouter(prefix="/audit", tags=["audit-cases"])
HIGH_RISK = (Severity.HIGH.value, Severity.CRITICAL.value)


def case_visibility(user: CurrentUser) -> ColumnElement[bool]:
    """Which of the hospital's cases this user may see, as a database condition.

    Audit Manager: all. Auditor: cases assigned to them. Management: HIGH/CRITICAL only.
    Restricted (personnel-sensitive) cases: only for roles with case:read_restricted.
    Several roles combine (a user who is Auditor and Management sees both sets).
    """
    perms = permissions_for(user.roles)
    if "case:read_all" in perms:
        scope = true()
    else:
        parts = []
        if "case:read_assigned" in perms:
            parts.append(AuditCase.assigned_to == user.user_id)
        if "case:read_high_risk" in perms:
            parts.append(AuditCase.priority.in_(HIGH_RISK))
        scope = or_(*parts) if parts else false()
    if "case:read_restricted" not in perms:
        scope = and_(scope, AuditCase.is_restricted.is_(False))
    return scope


def _visible_case(db: Session, user: CurrentUser, case_id: uuid.UUID) -> AuditCase:
    case = db.scalar(select(AuditCase).where(
        AuditCase.id == case_id, AuditCase.tenant_id == user.tenant_id,
        AuditCase.is_deleted.is_(False), case_visibility(user),
    ))
    if case is None:
        raise HTTPException(404, detail="Case not found")
    return case


@router.get("/cases", response_model=list[CaseOut])
def list_visible_cases(
    status: str | None = None, domain: str | None = None, priority: str | None = None,
    assigned_to: uuid.UUID | None = None, open_only: bool = False,
    user: CurrentUser = Depends(require_permission("case:read")),
    db: Session = Depends(get_db),
):
    return list_cases(db, user.tenant_id, status=status, domain=domain, priority=priority,
                      assigned_to=assigned_to, open_only=open_only, visibility=case_visibility(user))


@router.get("/cases/{case_id}", response_model=CaseDetailOut)
def get_case_detail(
    case_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission("case:read")),
    db: Session = Depends(get_db),
):
    case = _visible_case(db, user, case_id)
    rows = db.execute(
        select(AuditException, AuditRule.rule_code)
        .join(AuditCaseException, AuditCaseException.exception_id == AuditException.id)
        .outerjoin(AuditRule, AuditRule.id == AuditException.rule_id)
        .where(AuditCaseException.case_id == case.id, AuditCaseException.tenant_id == case.tenant_id)
        .order_by(AuditCaseException.added_at)
    ).all()
    exceptions = [
        CaseExceptionOut(id=exc.id, rule_code=code, severity=exc.severity, entity_type=exc.entity_type,
                         entity_id=exc.entity_id, created_at=exc.created_at)
        for exc, code in rows
    ]
    return CaseDetailOut(**CaseOut.model_validate(case).model_dump(exclude={"allowed_next"}),
                         ai_summary=case.ai_summary, exceptions=exceptions)


@router.get("/cases/{case_id}/timeline", response_model=list[TimelineEntryOut])
def get_case_timeline(
    case_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission("case:read")),
    db: Session = Depends(get_db),
):
    return case_timeline(db, _visible_case(db, user, case_id))


@router.get("/cases/{case_id}/comments", response_model=list[CommentOut])
def get_case_comments(
    case_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission("case:read")),
    db: Session = Depends(get_db),
):
    return case_comments(db, _visible_case(db, user, case_id))


@router.post("/cases", response_model=CaseOut, status_code=201)
def create_manual_case(
    body: ManualCaseCreate,
    user: CurrentUser = Depends(require_permission("case:create")),
    db: Session = Depends(get_db),
):
    try:
        case = open_case(
            db, user.tenant_id, domain=body.domain, title=body.title, source=CaseSource.MANUAL.value,
            primary_entity_type=body.primary_entity_type, primary_entity_id=body.primary_entity_id,
            priority=body.priority, actor_id=user.user_id, department_id=body.department_id,
        )
        db.commit()
    except ValueError as err:
        db.rollback()
        raise HTTPException(422, detail=str(err)) from None
    return case
