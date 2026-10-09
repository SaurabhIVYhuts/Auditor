"""Reusable FastAPI dependencies for the Auditor API."""
from fastapi import Depends, HTTPException, status

from agents.audit.permissions import has_permission
from shared.auth import CurrentUser, get_current_user


def require_permission(*permissions: str):
    """Use on an endpoint: Depends(require_permission("finding:confirm")).

    With several permissions, having ANY one of them is enough,
    e.g. require_permission("finding:read", "finding:read_own").
    401 if not logged in (raised by get_current_user), 403 if logged in but not allowed.
    """

    def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not any(has_permission(user.roles, permission) for permission in permissions):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not allowed")
        return user

    return checker
