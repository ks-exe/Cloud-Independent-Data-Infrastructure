"""Monitoring Service — metrics aggregation, dashboard data, Prometheus export, system health.

This service integrates with:
- PostgreSQL: Pipeline execution records for metrics aggregation
- Elasticsearch v8.13: Structured log storage and retrieval
- Prometheus: Metrics exposition for Grafana dashboards
- Health check system: Aggregated component health status

Dependencies: Elasticsearch (logs), Prometheus (metrics), PostgreSQL (execution records).
"""

import math
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.health import (
    HealthCheckAggregator,
    SystemStatus,
    create_health_aggregator_from_settings,
)
from backend.app.core.metrics import get_metrics_output, pipeline_queue_size
from backend.app.models.pipelines import PipelineRun
from backend.app.schemas.monitoring import (
    ComponentHealthInfo,
    DashboardMetrics,
    HealthStatus,
    LogEntry,
    LogQueryResponse,
    PrometheusMetrics,
    SystemHealth,
)


class MonitoringService:
    """Service for platform monitoring, metrics aggregation, and log querying.

    Provides:
    - get_dashboard_metrics: Running count, failed/succeeded in 24h, avg time, queue, retries, health
    - get_system_health: Aggregated health status from all service components
    - query_logs: Query Elasticsearch for execution logs with pagination (100/page)
    - expose_prometheus_metrics: Return Prometheus-compatible metrics
    """

    def __init__(
        self,
        db: AsyncSession,
        es_client=None,
        health_aggregator: HealthCheckAggregator | None = None,
    ) -> None:
        self.db = db
        self._es_client = es_client
        self._health_aggregator = (
            health_aggregator or create_health_aggregator_from_settings()
        )

    async def get_dashboard_metrics(self) -> DashboardMetrics:
        """Return dashboard metrics for the monitoring panel.

        Metrics include:
        - Running pipeline count
        - Failed pipelines in last 24 hours
        - Succeeded pipelines in last 24 hours
        - Average execution time over last 24 hours
        - Current task queue size
        - Retry count in last 24 hours
        - System health status (healthy/degraded/unhealthy)

        Returns:
            DashboardMetrics with all current operational indicators.
        """
        now = datetime.now(timezone.utc)
        twenty_four_hours_ago = now - timedelta(hours=24)

        # Running pipelines
        running_result = await self.db.execute(
            select(func.count(PipelineRun.id)).where(
                PipelineRun.status == "running"
            )
        )
        running_count = running_result.scalar() or 0

        # Failed in last 24h
        failed_result = await self.db.execute(
            select(func.count(PipelineRun.id)).where(
                PipelineRun.status == "failed",
                PipelineRun.completed_at >= twenty_four_hours_ago,
            )
        )
        failed_24h = failed_result.scalar() or 0

        # Succeeded in last 24h
        succeeded_result = await self.db.execute(
            select(func.count(PipelineRun.id)).where(
                PipelineRun.status == "succeeded",
                PipelineRun.completed_at >= twenty_four_hours_ago,
            )
        )
        succeeded_24h = succeeded_result.scalar() or 0

        # Average execution time in last 24h (duration_ms field)
        avg_result = await self.db.execute(
            select(func.avg(PipelineRun.duration_ms)).where(
                PipelineRun.completed_at >= twenty_four_hours_ago,
                PipelineRun.duration_ms.is_not(None),
            )
        )
        avg_execution_time_ms = avg_result.scalar() or 0.0

        # Queue size (pipelines in 'queued' state)
        queue_result = await self.db.execute(
            select(func.count(PipelineRun.id)).where(
                PipelineRun.status == "queued"
            )
        )
        queue_size = queue_result.scalar() or 0

        # Retry count in last 24h
        retry_result = await self.db.execute(
            select(func.coalesce(func.sum(PipelineRun.retry_count), 0)).where(
                PipelineRun.started_at >= twenty_four_hours_ago,
                PipelineRun.retry_count > 0,
            )
        )
        retry_count_24h = int(retry_result.scalar() or 0)

        # System health
        system_status, _ = await self._health_aggregator.check_all()
        health_status = HealthStatus(system_status.value)

        # Update Prometheus queue gauge
        pipeline_queue_size.set(queue_size)

        return DashboardMetrics(
            running_count=running_count,
            failed_24h=failed_24h,
            succeeded_24h=succeeded_24h,
            avg_execution_time_ms=float(avg_execution_time_ms),
            queue_size=queue_size,
            retry_count_24h=retry_count_24h,
            system_health=health_status,
        )

    async def get_system_health(self) -> SystemHealth:
        """Aggregate health status from all service components.

        Runs health checks on:
        - PostgreSQL (critical)
        - Redis (critical)
        - RabbitMQ (critical)
        - Elasticsearch (non-critical)
        - Dagster (non-critical)

        Overall status:
        - healthy: all services responding
        - degraded: one or more non-critical services unresponsive
        - unhealthy: any critical service unresponsive

        Returns:
            SystemHealth with overall status and per-component details.
        """
        system_status, component_results = await self._health_aggregator.check_all()

        components = [
            ComponentHealthInfo(
                name=result.name,
                status=result.status.value,
                latency_ms=result.latency_ms,
                error=result.error,
            )
            for result in component_results
        ]

        return SystemHealth(
            status=HealthStatus(system_status.value),
            components=components,
            checked_at=datetime.now(timezone.utc),
        )

    async def query_logs(
        self,
        execution_id: UUID,
        page: int = 1,
    ) -> LogQueryResponse:
        """Query Elasticsearch for execution logs.

        Returns chronologically ordered, timestamped log entries for the
        specified execution, paginated in sets of 100 entries per page.
        Query must complete within 5 seconds.

        Captures: stdout/stderr, Dagster events, worker activities.

        Args:
            execution_id: The pipeline execution ID to query logs for.
            page: Page number (1-indexed).

        Returns:
            LogQueryResponse with paginated log entries.
        """
        page = max(page, 1)
        page_size = 100
        offset = (page - 1) * page_size

        if self._es_client is None:
            # Return empty result when Elasticsearch is not configured
            return LogQueryResponse(
                items=[],
                total=0,
                page=page,
                page_size=page_size,
                pages=0,
                execution_id=str(execution_id),
            )

        # Build Elasticsearch query
        query_body = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"execution_id": str(execution_id)}},
                    ]
                }
            },
            "sort": [{"timestamp": {"order": "asc"}}],
            "from": offset,
            "size": page_size,
        }

        # Query with 5-second timeout
        index_name = "pipeline-logs-*"
        response = await self._es_client.search(
            index=index_name,
            body=query_body,
            request_timeout=5,
        )

        total = response["hits"]["total"]["value"]
        pages = math.ceil(total / page_size) if total > 0 else 0

        items = []
        for hit in response["hits"]["hits"]:
            source = hit["_source"]
            items.append(
                LogEntry(
                    id=hit["_id"],
                    timestamp=source["timestamp"],
                    level=source.get("level", "INFO"),
                    message=source.get("message", ""),
                    source=source.get("source", "unknown"),
                    execution_id=source["execution_id"],
                    node_id=source.get("node_id"),
                    metadata=source.get("metadata"),
                )
            )

        return LogQueryResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
            execution_id=str(execution_id),
        )

    def expose_prometheus_metrics(self) -> bytes:
        """Return Prometheus-compatible metrics in text exposition format.

        Exposes:
        - pipeline_executions_total: Execution count by status
        - pipeline_execution_duration_seconds: Duration histogram
        - pipeline_failures_total: Failure count by reason
        - pipeline_queue_size: Current queue size
        - pipeline_retries_total: Retry count

        Returns:
            Bytes containing Prometheus text exposition format metrics.
        """
        return get_metrics_output()

    async def get_prometheus_metrics_summary(self) -> PrometheusMetrics:
        """Get a summary of Prometheus metrics as structured data.

        This provides a JSON-friendly alternative to the raw Prometheus
        text format for API consumers.

        Returns:
            PrometheusMetrics with current metric values.
        """
        now = datetime.now(timezone.utc)
        twenty_four_hours_ago = now - timedelta(hours=24)

        # Total execution count
        exec_result = await self.db.execute(
            select(func.count(PipelineRun.id))
        )
        execution_count = exec_result.scalar() or 0

        # Total duration in seconds (sum of all completed runs)
        duration_result = await self.db.execute(
            select(func.coalesce(func.sum(PipelineRun.duration_ms), 0)).where(
                PipelineRun.duration_ms.is_not(None),
            )
        )
        total_duration_ms = int(duration_result.scalar() or 0)
        execution_duration_seconds = total_duration_ms / 1000.0

        # Failure count
        failure_result = await self.db.execute(
            select(func.count(PipelineRun.id)).where(
                PipelineRun.status == "failed"
            )
        )
        failure_count = failure_result.scalar() or 0

        # Queue size
        queue_result = await self.db.execute(
            select(func.count(PipelineRun.id)).where(
                PipelineRun.status == "queued"
            )
        )
        queue_size = queue_result.scalar() or 0

        # Retry count
        retry_result = await self.db.execute(
            select(func.coalesce(func.sum(PipelineRun.retry_count), 0)).where(
                PipelineRun.retry_count > 0,
            )
        )
        retry_count = int(retry_result.scalar() or 0)

        return PrometheusMetrics(
            execution_count=execution_count,
            execution_duration_seconds=execution_duration_seconds,
            failure_count=failure_count,
            queue_size=queue_size,
            retry_count=retry_count,
        )


def get_monitoring_service(
    db: AsyncSession,
    es_client=None,
    health_aggregator: HealthCheckAggregator | None = None,
) -> MonitoringService:
    """Factory function for dependency injection of MonitoringService."""
    return MonitoringService(
        db=db,
        es_client=es_client,
        health_aggregator=health_aggregator,
    )
