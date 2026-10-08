"""Creates the Auditor Agent's FastAPI application."""
from fastapi import FastAPI

from agents.audit.api.cases import router as cases_router
from agents.audit.api.health import router as health_router
from agents.audit.api.me import router as me_router
from agents.audit.api.notifications import router as notifications_router
from agents.audit.api.rules import router as rules_router
from agents.audit.api.trail import router as trail_router
from shared.config import settings


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)
    # Every endpoint lives under /api/v1 (architecture section 8)
    app.include_router(health_router, prefix=settings.api_prefix)
    app.include_router(me_router, prefix=settings.api_prefix)
    app.include_router(trail_router, prefix=settings.api_prefix)
    app.include_router(rules_router, prefix=settings.api_prefix)
    app.include_router(cases_router, prefix=settings.api_prefix)
    app.include_router(notifications_router, prefix=settings.api_prefix)
    return app


app = create_app()
