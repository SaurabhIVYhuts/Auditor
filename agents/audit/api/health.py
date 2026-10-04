"""Health check endpoint: answers 'is the server running?'."""
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict:
    return {"status": "ok", "service": "auditor-agent"}
