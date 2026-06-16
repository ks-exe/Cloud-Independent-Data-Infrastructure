"""Monitoring API routes.

Provides read-only access to platform monitoring data:
- GET /api/v1/monitoring/dashboard - platform metrics (monitoring.read)
- GET /api/v1/monitoring/health - system health (monitoring.read)
- GET /api/v1/monitoring/logs/{execution_id} - execution logs (monitoring.read)
- GET /api/v1/monitoring/metrics - Prometheus-compatible metrics (no auth)
- GET /api/v1/monitoring/metrics/summary - JSON metrics summary (monitoring.read)

Permission matrix:
- Admin: full access
- Operator: full access
- Viewer: read access
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.security import TokenClaims, require_permissions
from backend.app.schemas.monitoring import (
    DashboardMetrics,
    LogQueryResponse,
    PrometheusMetrics,
    SystemHealth,
)
from backend.app.services.monitoring_service import MonitoringService, get_monitoring_service

router = APIRouter(prefix="/monitoring", tags=["Monitoring"])


def _get_service(db: AsyncSession = Depends(get_db)) -> MonitoringService:
    """Dependency injection for MonitoringService."""
    return get_monitoring_service(db=db)


@router.get("/dashboard", response_model=DashboardMetrics, operation_id="monitoring_get_dashboard")
async def get_dashboard_metrics(
    current_user: TokenClaims = Depends(require_permissions("monitoring.read")),
    service: MonitoringService = Depends(_get_service),
) -> DashboardMetrics:
    """Get platform dashboard metrics.

    Returns running count, failed in 24h, succeeded in 24h,
    average execution time, queue size, retry count, and system health.
    Dashboard updates failed pipeline count within 10 seconds.
    """
    return await service.get_dashboard_metrics()


@router.get("/health", response_model=SystemHealth, operation_id="monitoring_get_system_health")
async def get_system_health(
    current_user: TokenClaims = Depends(require_permissions("monitoring.read")),
    service: MonitoringService = Depends(_get_service),
) -> SystemHealth:
    """Get overall system health status.

    Aggregates health from all service components:
    - healthy: all services responding
    - degraded: one or more non-critical services unresponsive
    - unhealthy: any critical service unresponsive
    """
    return await service.get_system_health()


@router.get("/logs/{execution_id}", response_model=LogQueryResponse, operation_id="monitoring_get_execution_logs")
async def get_execution_logs(
    execution_id: UUID,
    page: int = 1,
    current_user: TokenClaims = Depends(require_permissions("monitoring.read")),
    service: MonitoringService = Depends(_get_service),
) -> LogQueryResponse:
    """Get execution logs with pagination.

    Queries Elasticsearch and returns chronologically ordered,
    timestamped log entries paginated at 100 per page within 5 seconds.
    Captures stdout/stderr, Dagster events, and worker activities.
    """
    return await service.query_logs(execution_id=execution_id, page=page)


@router.get("/metrics", operation_id="monitoring_get_prometheus_metrics")
async def get_prometheus_metrics() -> Response:
    """Expose Prometheus-compatible metrics.

    Returns metrics in Prometheus text exposition format.
    This endpoint does not require authentication to allow
    Prometheus scraping.

    Metrics exposed:
    - pipeline_executions_total
    - pipeline_execution_duration_seconds
    - pipeline_failures_total
    - pipeline_queue_size
    - pipeline_retries_total
    """
    from backend.app.core.metrics import get_metrics_output

    metrics_output = get_metrics_output()
    return Response(
        content=metrics_output,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@router.get("/metrics/summary", response_model=PrometheusMetrics, operation_id="monitoring_get_metrics_summary")
async def get_metrics_summary(
    current_user: TokenClaims = Depends(require_permissions("monitoring.read")),
    service: MonitoringService = Depends(_get_service),
) -> PrometheusMetrics:
    """Get a JSON summary of current metrics.

    Provides execution count, duration, failure count, queue size,
    and retry count as structured JSON data.
    """
    return await service.get_prometheus_metrics_summary()
