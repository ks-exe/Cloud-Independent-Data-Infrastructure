"""Health check endpoints for the data platform.

Provides a detailed health check at /api/v1/health that aggregates
the status of all service components (PostgreSQL, Redis, RabbitMQ,
Elasticsearch, Dagster).

The root /health endpoint in main.py remains as a simple liveness probe.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.app.core.config import settings
from backend.app.core.health import (
    SystemStatus,
    create_health_aggregator_from_settings,
)

router = APIRouter(prefix="/health", tags=["Health"])


@router.get(
    "",
    summary="Detailed system health check",
    description=(
        "Checks all service components and returns aggregate health status. "
        "Returns HTTP 200 when all services are healthy or degraded, "
        "HTTP 503 when any critical service is unhealthy."
    ),
    operation_id="health_detailed_check",
)
async def detailed_health_check() -> JSONResponse:
    """Aggregate health check for all platform components.

    Returns:
        200: All components healthy or only non-critical degraded.
        503: One or more critical components unhealthy.
    """
    aggregator = create_health_aggregator_from_settings()
    system_status, component_results = await aggregator.check_all()

    components = {
        result.name: {
            "name": result.name,
            "status": result.status.value,
            "latency_ms": result.latency_ms,
        }
        for result in component_results
    }

    body = {
        "service_name": settings.app_name,
        "status": system_status.value,
        "components": components,
    }

    if system_status == SystemStatus.UNHEALTHY:
        return JSONResponse(content=body, status_code=503)

    return JSONResponse(content=body, status_code=200)
