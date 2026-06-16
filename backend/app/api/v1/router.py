"""API v1 router aggregating all domain routers."""

from fastapi import APIRouter

from backend.app.api.v1.auth import router as auth_router
from backend.app.api.v1.users import router as users_router
from backend.app.api.v1.connectors import router as connectors_router
from backend.app.api.v1.pipelines import router as pipelines_router
from backend.app.api.v1.schedules import router as schedules_router
from backend.app.api.v1.monitoring import router as monitoring_router
from backend.app.api.v1.lineage import router as lineage_router
from backend.app.api.v1.audit import router as audit_router
from backend.app.api.v1.notifications import router as notifications_router
from backend.app.api.v1.health import router as health_router
from backend.app.api.v1.settings import router as settings_router

api_v1_router = APIRouter(prefix="/api/v1")

api_v1_router.include_router(auth_router)
api_v1_router.include_router(users_router)
api_v1_router.include_router(connectors_router)
api_v1_router.include_router(pipelines_router)
api_v1_router.include_router(schedules_router)
api_v1_router.include_router(monitoring_router)
api_v1_router.include_router(lineage_router)
api_v1_router.include_router(audit_router)
api_v1_router.include_router(notifications_router)
api_v1_router.include_router(health_router)
api_v1_router.include_router(settings_router)
