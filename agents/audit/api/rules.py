"""Rule API (module M2): list, create, edit (new version), activate/deactivate, run, run history.

Every endpoint checks a permission and only sees the logged-in user's hospital.
Invalid rule definitions are refused with every problem listed (422).
Every successful change or run is written to the audit log in the same transaction;
refused actions write nothing.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agents.audit.api.deps import require_permission
from agents.audit.models import AuditRule, AuditRuleRun, RuleStatus
from agents.audit.rules import dsl_spec as spec
from agents.audit.rules.validator import RuleValidationError
from agents.audit.schemas.rule import RuleCreate, RuleOut, RuleRunOut, RuleUpdate
from agents.audit.services.batch_runner import run_rule_batch
from agents.audit.services.rule_registry import (
    MakerCheckerError, activate_rule, create_rule, deactivate_rule, save_new_version,
)
from shared.audit_log import log_action
from shared.auth import CurrentUser
from shared.db import get_db

router = APIRouter(prefix="/audit", tags=["audit-rules"])
RULE_ENTITY = "audit_rule"


def _get_rule(db: Session, user: CurrentUser, rule_id: uuid.UUID) -> AuditRule:
    rule = db.get(AuditRule, rule_id)
    if rule is None or rule.tenant_id != user.tenant_id or rule.is_deleted:
        raise HTTPException(404, detail="Rule not found")   # other hospitals' rules look "not found"
    return rule


def _invalid(err: Exception) -> HTTPException:
    errors = err.errors if isinstance(err, RuleValidationError) else [str(err)]
    return HTTPException(422, detail={"errors": errors})


def _log(db: Session, user: CurrentUser, action: str, rule: AuditRule, **details) -> None:
    """Audit-log a successful rule action. Call before commit, so both are saved together."""
    log_action(db, user.tenant_id, user.user_id, action, RULE_ENTITY, rule.id, details)


@router.get("/rules", response_model=list[RuleOut])
def list_rules(
    domain: str | None = None,
    rule_status: str | None = Query(default=None, alias="status"),
    user: CurrentUser = Depends(require_permission("rule:read")),
    db: Session = Depends(get_db),
):
    stmt = select(AuditRule).where(AuditRule.tenant_id == user.tenant_id, AuditRule.is_deleted.is_(False))
    if domain:
        stmt = stmt.where(AuditRule.domain == domain)
    if rule_status:
        stmt = stmt.where(AuditRule.status == rule_status)
    return db.scalars(stmt.order_by(AuditRule.rule_code)).all()


@router.post("/rules", response_model=RuleOut, status_code=201)
def create(
    body: RuleCreate,
    user: CurrentUser = Depends(require_permission("rule:write")),
    db: Session = Depends(get_db),
):
    try:
        rule = create_rule(
            db, tenant_id=user.tenant_id, rule_code=body.rule_code, name=body.name,
            description=body.description, domain=body.domain, severity=body.severity,
            definition=body.definition, owner_id=user.user_id,
        )
        _log(db, user, "rule.created", rule, rule_code=rule.rule_code, version=1)
        db.commit()
    except ValueError as err:                      # includes RuleValidationError
        db.rollback()
        raise _invalid(err) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, detail="Rule code already exists") from None
    return rule


@router.get("/rules/{rule_id}", response_model=RuleOut)
def get_rule(
    rule_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission("rule:read")),
    db: Session = Depends(get_db),
):
    return _get_rule(db, user, rule_id)


@router.put("/rules/{rule_id}", response_model=RuleOut)
def edit_rule(
    rule_id: uuid.UUID,
    body: RuleUpdate,
    user: CurrentUser = Depends(require_permission("rule:write")),
    db: Session = Depends(get_db),
):
    rule = _get_rule(db, user, rule_id)
    try:
        save_new_version(db, rule, definition=body.definition, severity=body.severity,
                         changed_by=user.user_id, change_note=body.change_note)
        _log(db, user, "rule.version_saved", rule,
             version=rule.current_version, change_note=body.change_note)
        db.commit()
    except ValueError as err:
        db.rollback()
        raise _invalid(err) from None
    return rule


@router.post("/rules/{rule_id}/activate", response_model=RuleOut)
def activate(rule_id: uuid.UUID, user: CurrentUser = Depends(require_permission("rule:activate")),
             db: Session = Depends(get_db)):
    rule = _get_rule(db, user, rule_id)
    try:
        activate_rule(db, rule, approved_by=user.user_id)
        _log(db, user, "rule.activated", rule,
             version=rule.current_version, approved_by=str(rule.approved_by))
        db.commit()
    except MakerCheckerError:
        db.rollback()
        raise HTTPException(403, detail="MAKER_CHECKER") from None
    except ValueError as err:
        db.rollback()
        raise _invalid(err) from None
    return rule


@router.post("/rules/{rule_id}/deactivate", response_model=RuleOut)
def deactivate(rule_id: uuid.UUID, user: CurrentUser = Depends(require_permission("rule:activate")),
               db: Session = Depends(get_db)):
    rule = _get_rule(db, user, rule_id)
    deactivate_rule(db, rule)
    _log(db, user, "rule.deactivated", rule)
    db.commit()
    return rule


@router.post("/rules/{rule_id}/run", response_model=RuleRunOut)
def run_now(rule_id: uuid.UUID, user: CurrentUser = Depends(require_permission("rule:run")),
            db: Session = Depends(get_db)):
    rule = _get_rule(db, user, rule_id)
    if rule.status != RuleStatus.ACTIVE.value:
        raise HTTPException(409, detail="Only ACTIVE rules can run")
    run = run_rule_batch(db, rule)
    _log(db, user, "rule.run", rule, run_id=str(run.id), status=run.status,
         records_checked=run.records_checked, exceptions_created=run.exceptions_created)
    db.commit()
    return run


@router.get("/rules/{rule_id}/runs", response_model=list[RuleRunOut])
def list_runs(rule_id: uuid.UUID, user: CurrentUser = Depends(require_permission("rule:read")),
              db: Session = Depends(get_db)):
    rule = _get_rule(db, user, rule_id)
    return db.scalars(select(AuditRuleRun).where(AuditRuleRun.rule_id == rule.id)
                      .order_by(AuditRuleRun.started_at.desc()).limit(50)).all()


@router.get("/rule-functions")
def rule_functions(user: CurrentUser = Depends(require_permission("rule:read"))):
    return {"functions": spec.FUNCTIONS, "operators": sorted(spec.COMPARISON_OPS),
            "fields": {p: sorted(f) for p, f in spec.FIELDS.items()}, "events": sorted(spec.EVENT_TYPES)}
