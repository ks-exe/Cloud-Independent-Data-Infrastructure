"""Pydantic schemas for monitoring and observability operations."""

import enum
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class HealthStatus(str, enum.Enum):
    """Overall system health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ComponentHealthInfo(BaseModel):
    """Health status for an individual service component."""

    name: str = Field(..., description="Component name")
    status: str = Field(..., description="Component status (healthy/unhealthy)")
    latency_ms: float = Field(..., description="Response latency in milliseconds")
    error: str | None = Field(None, description="Error message if unhealthy")


class SystemHealth(BaseModel):
    """Aggregated system health response."""

    status: HealthStatus = Field(..., description="Overall system health status")
    components: list[ComponentHealthInfo] = Field(
        ..., description="Individual component health statuses"
    )
    checked_at: datetime = Field(..., description="Timestamp of the health check")


class DashboardMetrics(BaseModel):
    """Dashboard metrics response containing key operational indicators."""

    running_count: int = Field(
        ..., description="Count of currently running pipelines"
    )
    failed_24h: int = Field(
        ..., description="Pipelines failed within the last 24 hours"
    )
    succeeded_24h: int = Field(
        ..., description="Pipelines successfully completed within the last 24 hours"
    )
    avg_execution_time_ms: float = Field(
        ..., description="Average execution time in milliseconds over the last 24 hours"
    )
    queue_size: int = Field(..., description="Current task queue size")
    retry_count_24h: int = Field(
        ..., description="Retry count within the last 24 hours"
    )
    system_health: HealthStatus = Field(
        ..., description="Current system health status"
    )


class LogEntry(BaseModel):
    """A single log entry from Elasticsearch."""

    id: str = Field(..., description="Log entry identifier")
    timestamp: datetime = Field(..., description="Log entry timestamp")
    level: str = Field(..., description="Log level (INFO, WARNING, ERROR, DEBUG)")
    message: str = Field(..., description="Log message content")
    source: str = Field(
        ..., description="Log source (stdout, stderr, dagster, worker)"
    )
    execution_id: str = Field(..., description="Associated pipeline execution ID")
    node_id: str | None = Field(None, description="Associated pipeline node ID")
    metadata: dict | None = Field(None, description="Additional log metadata")


class LogQueryResponse(BaseModel):
    """Paginated response for log queries."""

    items: list[LogEntry] = Field(..., description="Log entries for the current page")
    total: int = Field(..., description="Total number of matching log entries")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(default=100, description="Number of items per page")
    pages: int = Field(..., description="Total number of pages")
    execution_id: str = Field(..., description="The execution ID that was queried")


class PrometheusMetrics(BaseModel):
    """Prometheus-compatible metrics response metadata."""

    execution_count: int = Field(
        ..., description="Total pipeline execution count"
    )
    execution_duration_seconds: float = Field(
        ..., description="Total execution duration in seconds"
    )
    failure_count: int = Field(..., description="Total pipeline failure count")
    queue_size: int = Field(..., description="Current task queue size")
    retry_count: int = Field(..., description="Total retry count")
