"""Creates the Auditor Agent's FastAPI application."""
from fastapi import FastAPI

from agents.audit.api.health import router as health_router
from shared.config import settings


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)
    # Every endpoint lives under /api/v1 (architecture section 8)
    app.include_router(health_router, prefix=settings.api_prefix)
    return app


app = create_app()
