"""Trail endpoints: let auditors view procurement trails from the Audit Data Hub.

Read-only. The tenant always comes from the logged-in user, never from the URL,
so nobody can read another hospital's data by changing a parameter.
"""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from agents.audit.api.deps import require_permission
from agents.audit.schemas.trail import TrailEntryOut
from agents.audit.services.trail_service import get_po_chain, get_record_history
from shared.auth import CurrentUser
from shared.db import get_db

router = APIRouter(prefix="/audit", tags=["audit-trail"])


@router.get("/trail/po/{po_number}", response_model=list[TrailEntryOut])
def po_trail(
    po_number: str,
    user: CurrentUser = Depends(require_permission("source_record:read")),
    db: Session = Depends(get_db),
):
    entries = get_po_chain(db, tenant_id=user.tenant_id, po_number=po_number)
    return [TrailEntryOut.model_validate(entry) for entry in entries]


@router.get("/source-records/{entity_type}/{entity_id}/history", response_model=list[TrailEntryOut])
def record_history(
    entity_type: str,
    entity_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission("source_record:read")),
    db: Session = Depends(get_db),
):
    entries = get_record_history(
        db, tenant_id=user.tenant_id, entity_type=entity_type, entity_id=entity_id
    )
    return [TrailEntryOut.model_validate(entry) for entry in entries]
