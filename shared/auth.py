"""Placeholder for the platform Auth service (JWT + RBAC).

Until the real Konnective Tissue Auth service exists, a developer identifies
themselves with request headers: X-User-Id, X-Tenant-Id, X-Roles (comma
separated, e.g. "AUD,CO") and optionally X-Department-Id.

SAFETY: this only works when ENVIRONMENT is "development" or "test".
In every other environment all requests are rejected, so this placeholder
can never be used in production by mistake. Replace this file with the real
JWT validation when the platform Auth service is available.
"""
import uuid
from dataclasses import dataclass

from fastapi import Header, HTTPException, status

from shared.config import settings

DEV_AUTH_ENVIRONMENTS = frozenset({"development", "test"})


@dataclass(frozen=True)
class CurrentUser:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    roles: frozenset[str]
    department_id: uuid.UUID | None = None


def get_current_user(
    x_user_id: str | None = Header(default=None),
    x_tenant_id: str | None = Header(default=None),
    x_roles: str | None = Header(default=None),
    x_department_id: str | None = Header(default=None),
) -> CurrentUser:
    if settings.environment not in DEV_AUTH_ENVIRONMENTS:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Authentication service not configured")
    if not x_user_id or not x_tenant_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        user_id = uuid.UUID(x_user_id)
        tenant_id = uuid.UUID(x_tenant_id)
        department_id = uuid.UUID(x_department_id) if x_department_id else None
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials") from None
    roles = frozenset(r.strip().upper() for r in (x_roles or "").split(",") if r.strip())
    return CurrentUser(user_id=user_id, tenant_id=tenant_id, roles=roles, department_id=department_id)
