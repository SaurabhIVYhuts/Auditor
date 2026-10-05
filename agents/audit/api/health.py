"""Health check endpoints: is the server running, and can it reach the database?"""
from fastapi import APIRouter, Response, status

from shared.db import check_database

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict:
    return {"status": "ok", "service": "auditor-agent"}


@router.get("/health/db")
def database_health(response: Response) -> dict:
    if check_database():
        return {"database": "ok"}
    # Fail safe, never fail silent: report clearly, but never expose error details.
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"database": "unavailable"}
