"""'Who am I?' endpoint: shows the current user's roles and permissions."""
from fastapi import APIRouter, Depends

from agents.audit.permissions import permissions_for
from shared.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/me")
def who_am_i(user: CurrentUser = Depends(get_current_user)) -> dict:
    return {
        "user_id": str(user.user_id),
        "tenant_id": str(user.tenant_id),
        "roles": sorted(user.roles),
        "permissions": sorted(permissions_for(user.roles)),
    }
