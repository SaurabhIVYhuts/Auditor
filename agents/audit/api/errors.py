"""One way to run a write action in the API: commit on success, clear error responses on failure.

Used by the case, evidence and finding APIs, so the same problem always gives the same answer:
  409 INTEGRITY_FAILED (the alert is COMMITTED first), 409 {message, allowed_next}, 409 {message},
  403 MAKER_CHECKER, 403 MANAGER_APPROVAL, 422 {message[, missing]}.
"""
from collections.abc import Callable
from typing import TypeVar

from fastapi import HTTPException
from sqlalchemy.orm import Session

from agents.audit.services.case_service import CaseClosed, FindingsStillOpen, ManagerApprovalRequired
from agents.audit.services.evidence_service import EvidenceIntegrityError
from agents.audit.services.finding_service import FieldsRequired
from agents.audit.services.rule_registry import MakerCheckerError
from agents.audit.workflow import InvalidTransition

T = TypeVar("T")


def run_action(db: Session, action: Callable[[], T]) -> T:
    try:
        result = action()
        db.commit()
        return result
    except EvidenceIntegrityError as err:
        db.commit()                                   # keep the integrity alert and its log entry
        raise HTTPException(409, detail={"code": "INTEGRITY_FAILED", "message": str(err)}) from None
    except InvalidTransition as err:
        db.rollback()
        raise HTTPException(409, detail={"message": str(err), "allowed_next": err.allowed}) from None
    except (CaseClosed, FindingsStillOpen) as err:     # before ValueError: both are ValueErrors
        db.rollback()
        raise HTTPException(409, detail={"message": str(err)}) from None
    except MakerCheckerError as err:
        db.rollback()
        raise HTTPException(403, detail={"code": "MAKER_CHECKER", "message": str(err)}) from None
    except ManagerApprovalRequired as err:
        db.rollback()
        raise HTTPException(403, detail={"code": "MANAGER_APPROVAL", "message": str(err)}) from None
    except FieldsRequired as err:
        db.rollback()
        raise HTTPException(422, detail={"message": str(err), "missing": err.missing}) from None
    except (ValueError, NotImplementedError) as err:   # ReasonRequired, EvidenceRequired, DocumentRejected, ...
        db.rollback()
        raise HTTPException(422, detail={"message": str(err)}) from None
