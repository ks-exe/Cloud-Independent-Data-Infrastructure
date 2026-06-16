"""Prometheus metrics definitions for the data platform.

Exposes platform-level metrics using the prometheus_client library.
These metrics are collected by Prometheus and visualized in Grafana dashboards.

Metrics exposed:
- pipeline_executions_total: Counter of total pipeline executions
- pipeline_execution_duration_seconds: Histogram of execution durations
- pipeline_failures_total: Counter of total pipeline failures
- pipeline_queue_size: Gauge of current task queue size
- pipeline_retries_total: Counter of total pipeline retries
"""

from prometheus_client import Counter, Gauge, Histogram, generate_latest

# Pipeline execution count (total)
pipeline_executions_total = Counter(
    "pipeline_executions_total",
    "Total number of pipeline executions",
    ["pipeline_id", "status"],
)

# Pipeline execution duration in seconds
pipeline_execution_duration_seconds = Histogram(
    "pipeline_execution_duration_seconds",
    "Pipeline execution duration in seconds",
    ["pipeline_id"],
    buckets=[1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600],
)

# Pipeline failure count
pipeline_failures_total = Counter(
    "pipeline_failures_total",
    "Total number of pipeline execution failures",
    ["pipeline_id", "failure_reason"],
)

# Current task queue size
pipeline_queue_size = Gauge(
    "pipeline_queue_size",
    "Current number of pipeline tasks in the queue",
)

# Pipeline retry count
pipeline_retries_total = Counter(
    "pipeline_retries_total",
    "Total number of pipeline execution retries",
    ["pipeline_id"],
)


def get_metrics_output() -> bytes:
    """Generate Prometheus-compatible metrics output.

    Returns:
        Metrics in Prometheus text exposition format as bytes.
    """
    return generate_latest()


def record_execution_start(pipeline_id: str) -> None:
    """Record a pipeline execution start."""
    pipeline_executions_total.labels(pipeline_id=pipeline_id, status="started").inc()


def record_execution_success(pipeline_id: str, duration_seconds: float) -> None:
    """Record a successful pipeline execution with its duration."""
    pipeline_executions_total.labels(pipeline_id=pipeline_id, status="succeeded").inc()
    pipeline_execution_duration_seconds.labels(pipeline_id=pipeline_id).observe(
        duration_seconds
    )


def record_execution_failure(
    pipeline_id: str, failure_reason: str = "unknown"
) -> None:
    """Record a pipeline execution failure."""
    pipeline_executions_total.labels(pipeline_id=pipeline_id, status="failed").inc()
    pipeline_failures_total.labels(
        pipeline_id=pipeline_id, failure_reason=failure_reason
    ).inc()


def record_retry(pipeline_id: str) -> None:
    """Record a pipeline retry attempt."""
    pipeline_retries_total.labels(pipeline_id=pipeline_id).inc()


def update_queue_size(size: int) -> None:
    """Update the current task queue size gauge."""
    pipeline_queue_size.set(size)
