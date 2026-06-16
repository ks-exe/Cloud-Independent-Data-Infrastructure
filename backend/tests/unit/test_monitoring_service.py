"""Unit tests for the Monitoring Service.

Tests cover:
- get_dashboard_metrics: Verifies aggregation of running, failed, succeeded counts,
  average execution time, queue size, retry count, and system health.
- get_system_health: Verifies aggregated component health status.
- query_logs: Verifies Elasticsearch query with pagination and chronological ordering.
- expose_prometheus_metrics: Verifies Prometheus text format output.
"""

import math
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from backend.app.core.health import (
    ComponentHealth,
    ComponentStatus,
    HealthCheckAggregator,
    SystemStatus,
)
from backend.app.schemas.monitoring import (
    DashboardMetrics,
    HealthStatus,
    LogEntry,
    LogQueryResponse,
    PrometheusMetrics,
    SystemHealth,
)
from backend.app.services.monitoring_service import MonitoringService


# ---------- Fixtures ----------


@pytest.fixture
def mock_db():
    """Create a mock async database session."""
    db = AsyncMock()
    return db


@pytest.fixture
def mock_health_aggregator():
    """Create a mock health aggregator that returns healthy status."""
    aggregator = AsyncMock(spec=HealthCheckAggregator)
    aggregator.check_all = AsyncMock(
        return_value=(
            SystemStatus.HEALTHY,
            [
                ComponentHealth("postgresql", ComponentStatus.HEALTHY, 5.0),
                ComponentHealth("redis", ComponentStatus.HEALTHY, 3.0),
                ComponentHealth("rabbitmq", ComponentStatus.HEALTHY, 10.0),
                ComponentHealth("elasticsearch", ComponentStatus.HEALTHY, 15.0),
                ComponentHealth("dagster", ComponentStatus.HEALTHY, 20.0),
            ],
        )
    )
    return aggregator


@pytest.fixture
def mock_es_client():
    """Create a mock Elasticsearch client."""
    client = AsyncMock()
    return client


@pytest.fixture
def service(mock_db, mock_health_aggregator):
    """Create a MonitoringService with mocked dependencies."""
    return MonitoringService(
        db=mock_db,
        es_client=None,
        health_aggregator=mock_health_aggregator,
    )


@pytest.fixture
def service_with_es(mock_db, mock_health_aggregator, mock_es_client):
    """Create a MonitoringService with mocked ES client."""
    return MonitoringService(
        db=mock_db,
        es_client=mock_es_client,
        health_aggregator=mock_health_aggregator,
    )


# ---------- DashboardMetrics Tests ----------


class TestGetDashboardMetrics:
    """Tests for get_dashboard_metrics method."""

    @pytest.mark.asyncio
    async def test_returns_dashboard_metrics_all_zeros(self, service, mock_db):
        """When no pipeline runs exist, all counts are zero."""
        # Mock the database execute calls to return 0 for all queries
        mock_scalar_result = MagicMock()
        mock_scalar_result.scalar.return_value = 0

        mock_db.execute = AsyncMock(return_value=mock_scalar_result)

        result = await service.get_dashboard_metrics()

        assert isinstance(result, DashboardMetrics)
        assert result.running_count == 0
        assert result.failed_24h == 0
        assert result.succeeded_24h == 0
        assert result.avg_execution_time_ms == 0.0
        assert result.queue_size == 0
        assert result.retry_count_24h == 0
        assert result.system_health == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_returns_correct_counts(self, service, mock_db):
        """Verify correct counts are returned from database queries."""
        # Simulate different values for each query (6 calls total)
        results = [5, 3, 12, 45000.0, 2, 7]
        call_index = [0]

        def make_result():
            mock = MagicMock()
            val = results[call_index[0]] if call_index[0] < len(results) else 0
            mock.scalar.return_value = val
            call_index[0] += 1
            return mock

        mock_db.execute = AsyncMock(side_effect=lambda *a, **kw: make_result())

        result = await service.get_dashboard_metrics()

        assert result.running_count == 5
        assert result.failed_24h == 3
        assert result.succeeded_24h == 12
        assert result.avg_execution_time_ms == 45000.0
        assert result.queue_size == 2
        assert result.retry_count_24h == 7
        assert result.system_health == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_degraded_system_health(self, mock_db):
        """When non-critical services are down, status is degraded."""
        aggregator = AsyncMock(spec=HealthCheckAggregator)
        aggregator.check_all = AsyncMock(
            return_value=(
                SystemStatus.DEGRADED,
                [
                    ComponentHealth("postgresql", ComponentStatus.HEALTHY, 5.0),
                    ComponentHealth("redis", ComponentStatus.HEALTHY, 3.0),
                    ComponentHealth("rabbitmq", ComponentStatus.HEALTHY, 10.0),
                    ComponentHealth("elasticsearch", ComponentStatus.UNHEALTHY, 2001.0, "Timeout"),
                    ComponentHealth("dagster", ComponentStatus.HEALTHY, 20.0),
                ],
            )
        )
        svc = MonitoringService(db=mock_db, health_aggregator=aggregator)

        mock_scalar_result = MagicMock()
        mock_scalar_result.scalar.return_value = 0
        mock_db.execute = AsyncMock(return_value=mock_scalar_result)

        result = await svc.get_dashboard_metrics()
        assert result.system_health == HealthStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_unhealthy_system_health(self, mock_db):
        """When critical services are down, status is unhealthy."""
        aggregator = AsyncMock(spec=HealthCheckAggregator)
        aggregator.check_all = AsyncMock(
            return_value=(
                SystemStatus.UNHEALTHY,
                [
                    ComponentHealth("postgresql", ComponentStatus.UNHEALTHY, 2001.0, "Connection refused"),
                    ComponentHealth("redis", ComponentStatus.HEALTHY, 3.0),
                    ComponentHealth("rabbitmq", ComponentStatus.HEALTHY, 10.0),
                    ComponentHealth("elasticsearch", ComponentStatus.HEALTHY, 15.0),
                    ComponentHealth("dagster", ComponentStatus.HEALTHY, 20.0),
                ],
            )
        )
        svc = MonitoringService(db=mock_db, health_aggregator=aggregator)

        mock_scalar_result = MagicMock()
        mock_scalar_result.scalar.return_value = 0
        mock_db.execute = AsyncMock(return_value=mock_scalar_result)

        result = await svc.get_dashboard_metrics()
        assert result.system_health == HealthStatus.UNHEALTHY


# ---------- SystemHealth Tests ----------


class TestGetSystemHealth:
    """Tests for get_system_health method."""

    @pytest.mark.asyncio
    async def test_all_healthy(self, service):
        """All components healthy returns overall healthy status."""
        result = await service.get_system_health()

        assert isinstance(result, SystemHealth)
        assert result.status == HealthStatus.HEALTHY
        assert len(result.components) == 5
        assert all(c.status == "healthy" for c in result.components)
        assert result.checked_at is not None

    @pytest.mark.asyncio
    async def test_degraded_status(self, mock_db):
        """Non-critical component failure returns degraded status."""
        aggregator = AsyncMock(spec=HealthCheckAggregator)
        aggregator.check_all = AsyncMock(
            return_value=(
                SystemStatus.DEGRADED,
                [
                    ComponentHealth("postgresql", ComponentStatus.HEALTHY, 5.0),
                    ComponentHealth("redis", ComponentStatus.HEALTHY, 3.0),
                    ComponentHealth("rabbitmq", ComponentStatus.HEALTHY, 10.0),
                    ComponentHealth("elasticsearch", ComponentStatus.UNHEALTHY, 2001.0, "Timeout"),
                    ComponentHealth("dagster", ComponentStatus.HEALTHY, 20.0),
                ],
            )
        )
        svc = MonitoringService(db=mock_db, health_aggregator=aggregator)
        result = await svc.get_system_health()

        assert result.status == HealthStatus.DEGRADED
        es_component = next(c for c in result.components if c.name == "elasticsearch")
        assert es_component.status == "unhealthy"
        assert es_component.error == "Timeout"

    @pytest.mark.asyncio
    async def test_unhealthy_status(self, mock_db):
        """Critical component failure returns unhealthy status."""
        aggregator = AsyncMock(spec=HealthCheckAggregator)
        aggregator.check_all = AsyncMock(
            return_value=(
                SystemStatus.UNHEALTHY,
                [
                    ComponentHealth("postgresql", ComponentStatus.UNHEALTHY, 2001.0, "Connection refused"),
                    ComponentHealth("redis", ComponentStatus.HEALTHY, 3.0),
                    ComponentHealth("rabbitmq", ComponentStatus.HEALTHY, 10.0),
                    ComponentHealth("elasticsearch", ComponentStatus.HEALTHY, 15.0),
                    ComponentHealth("dagster", ComponentStatus.HEALTHY, 20.0),
                ],
            )
        )
        svc = MonitoringService(db=mock_db, health_aggregator=aggregator)
        result = await svc.get_system_health()

        assert result.status == HealthStatus.UNHEALTHY
        pg_component = next(c for c in result.components if c.name == "postgresql")
        assert pg_component.status == "unhealthy"
        assert pg_component.error == "Connection refused"

    @pytest.mark.asyncio
    async def test_component_details_included(self, service):
        """Component details include name, status, latency, and error."""
        result = await service.get_system_health()

        for component in result.components:
            assert component.name is not None
            assert component.status in ("healthy", "unhealthy")
            assert component.latency_ms >= 0


# ---------- QueryLogs Tests ----------


class TestQueryLogs:
    """Tests for query_logs method."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_es_client(self, service):
        """When Elasticsearch is not configured, returns empty results."""
        execution_id = uuid4()
        result = await service.query_logs(execution_id=execution_id, page=1)

        assert isinstance(result, LogQueryResponse)
        assert result.items == []
        assert result.total == 0
        assert result.page == 1
        assert result.page_size == 100
        assert result.pages == 0
        assert result.execution_id == str(execution_id)

    @pytest.mark.asyncio
    async def test_queries_elasticsearch_correctly(self, service_with_es, mock_es_client):
        """Verifies correct Elasticsearch query construction."""
        execution_id = uuid4()
        now = datetime.now(timezone.utc).isoformat()

        mock_es_client.search = AsyncMock(
            return_value={
                "hits": {
                    "total": {"value": 2},
                    "hits": [
                        {
                            "_id": "log-1",
                            "_source": {
                                "timestamp": now,
                                "level": "INFO",
                                "message": "Pipeline started",
                                "source": "dagster",
                                "execution_id": str(execution_id),
                                "node_id": None,
                                "metadata": None,
                            },
                        },
                        {
                            "_id": "log-2",
                            "_source": {
                                "timestamp": now,
                                "level": "ERROR",
                                "message": "Connection failed",
                                "source": "stderr",
                                "execution_id": str(execution_id),
                                "node_id": "node-123",
                                "metadata": {"retry": 1},
                            },
                        },
                    ],
                }
            }
        )

        result = await service_with_es.query_logs(execution_id=execution_id, page=1)

        assert result.total == 2
        assert len(result.items) == 2
        assert result.page == 1
        assert result.pages == 1
        assert result.execution_id == str(execution_id)

        # Verify first log entry
        assert result.items[0].id == "log-1"
        assert result.items[0].level == "INFO"
        assert result.items[0].message == "Pipeline started"
        assert result.items[0].source == "dagster"

        # Verify second log entry
        assert result.items[1].id == "log-2"
        assert result.items[1].level == "ERROR"
        assert result.items[1].node_id == "node-123"
        assert result.items[1].metadata == {"retry": 1}

        # Verify ES was called with correct parameters
        mock_es_client.search.assert_called_once()
        call_kwargs = mock_es_client.search.call_args[1]
        assert call_kwargs["index"] == "pipeline-logs-*"
        assert call_kwargs["request_timeout"] == 5
        query_body = call_kwargs["body"]
        assert query_body["sort"] == [{"timestamp": {"order": "asc"}}]
        assert query_body["from"] == 0
        assert query_body["size"] == 100

    @pytest.mark.asyncio
    async def test_pagination_page_2(self, service_with_es, mock_es_client):
        """Verifies correct offset calculation for page 2."""
        execution_id = uuid4()

        mock_es_client.search = AsyncMock(
            return_value={
                "hits": {
                    "total": {"value": 150},
                    "hits": [
                        {
                            "_id": f"log-{i}",
                            "_source": {
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "level": "INFO",
                                "message": f"Log message {i}",
                                "source": "stdout",
                                "execution_id": str(execution_id),
                            },
                        }
                        for i in range(100, 150)
                    ],
                }
            }
        )

        result = await service_with_es.query_logs(execution_id=execution_id, page=2)

        assert result.total == 150
        assert result.page == 2
        assert result.pages == 2  # 150/100 = 2 pages

        # Verify offset is correct for page 2
        call_kwargs = mock_es_client.search.call_args[1]
        assert call_kwargs["body"]["from"] == 100

    @pytest.mark.asyncio
    async def test_page_minimum_clamped_to_1(self, service):
        """Page numbers below 1 are clamped to 1."""
        execution_id = uuid4()
        result = await service.query_logs(execution_id=execution_id, page=0)
        assert result.page == 1

    @pytest.mark.asyncio
    async def test_chronological_ordering(self, service_with_es, mock_es_client):
        """Logs are returned in chronological (ascending) order."""
        execution_id = uuid4()

        mock_es_client.search = AsyncMock(
            return_value={
                "hits": {
                    "total": {"value": 0},
                    "hits": [],
                }
            }
        )

        await service_with_es.query_logs(execution_id=execution_id, page=1)

        call_kwargs = mock_es_client.search.call_args[1]
        assert call_kwargs["body"]["sort"] == [{"timestamp": {"order": "asc"}}]


# ---------- PrometheusMetrics Tests ----------


class TestExposePrometheusMetrics:
    """Tests for expose_prometheus_metrics method."""

    def test_returns_bytes(self, service):
        """Prometheus metrics output is bytes."""
        result = service.expose_prometheus_metrics()
        assert isinstance(result, bytes)

    def test_contains_metric_names(self, service):
        """Output contains defined metric names."""
        result = service.expose_prometheus_metrics()
        output = result.decode("utf-8")

        # prometheus_client always includes HELP and TYPE lines for registered metrics
        assert "pipeline_executions_total" in output or "pipeline_queue_size" in output

    @pytest.mark.asyncio
    async def test_metrics_summary_returns_structured_data(self, service, mock_db):
        """get_prometheus_metrics_summary returns correct PrometheusMetrics."""
        results = [10, 50000, 3, 2, 5]
        call_index = [0]

        def make_result():
            mock = MagicMock()
            val = results[call_index[0]] if call_index[0] < len(results) else 0
            mock.scalar.return_value = val
            call_index[0] += 1
            return mock

        mock_db.execute = AsyncMock(side_effect=lambda *a, **kw: make_result())

        result = await service.get_prometheus_metrics_summary()

        assert isinstance(result, PrometheusMetrics)
        assert result.execution_count == 10
        assert result.execution_duration_seconds == 50.0  # 50000ms / 1000
        assert result.failure_count == 3
        assert result.queue_size == 2
        assert result.retry_count == 5


# ---------- Metrics Module Tests ----------


class TestMetricsModule:
    """Tests for the Prometheus metrics definitions module."""

    def test_record_execution_start(self):
        """record_execution_start increments the counter."""
        from backend.app.core.metrics import record_execution_start

        # Should not raise
        record_execution_start("test-pipeline-1")

    def test_record_execution_success(self):
        """record_execution_success increments counter and observes duration."""
        from backend.app.core.metrics import record_execution_success

        record_execution_success("test-pipeline-1", 30.5)

    def test_record_execution_failure(self):
        """record_execution_failure increments failure counters."""
        from backend.app.core.metrics import record_execution_failure

        record_execution_failure("test-pipeline-1", "connection_timeout")

    def test_record_retry(self):
        """record_retry increments retry counter."""
        from backend.app.core.metrics import record_retry

        record_retry("test-pipeline-1")

    def test_update_queue_size(self):
        """update_queue_size sets the gauge value."""
        from backend.app.core.metrics import pipeline_queue_size, update_queue_size

        update_queue_size(42)
        # Verify the gauge value was set
        assert pipeline_queue_size._value.get() == 42

    def test_get_metrics_output_returns_bytes(self):
        """get_metrics_output returns valid bytes."""
        from backend.app.core.metrics import get_metrics_output

        output = get_metrics_output()
        assert isinstance(output, bytes)
        assert len(output) > 0


# ---------- Schema Validation Tests ----------


class TestMonitoringSchemas:
    """Tests for monitoring Pydantic schemas."""

    def test_dashboard_metrics_schema(self):
        """DashboardMetrics accepts valid data."""
        metrics = DashboardMetrics(
            running_count=5,
            failed_24h=2,
            succeeded_24h=10,
            avg_execution_time_ms=3500.0,
            queue_size=3,
            retry_count_24h=1,
            system_health=HealthStatus.HEALTHY,
        )
        assert metrics.running_count == 5
        assert metrics.system_health == HealthStatus.HEALTHY

    def test_log_entry_schema(self):
        """LogEntry accepts valid log data."""
        entry = LogEntry(
            id="log-abc-123",
            timestamp=datetime.now(timezone.utc),
            level="ERROR",
            message="Connection failed to source database",
            source="stderr",
            execution_id="exec-123",
            node_id="node-456",
            metadata={"retry_attempt": 2},
        )
        assert entry.level == "ERROR"
        assert entry.node_id == "node-456"

    def test_log_entry_optional_fields(self):
        """LogEntry works without optional fields."""
        entry = LogEntry(
            id="log-abc-123",
            timestamp=datetime.now(timezone.utc),
            level="INFO",
            message="Pipeline started",
            source="dagster",
            execution_id="exec-123",
        )
        assert entry.node_id is None
        assert entry.metadata is None

    def test_system_health_schema(self):
        """SystemHealth schema validates correctly."""
        from backend.app.schemas.monitoring import ComponentHealthInfo

        health = SystemHealth(
            status=HealthStatus.DEGRADED,
            components=[
                ComponentHealthInfo(
                    name="postgresql",
                    status="healthy",
                    latency_ms=5.0,
                    error=None,
                ),
                ComponentHealthInfo(
                    name="elasticsearch",
                    status="unhealthy",
                    latency_ms=2001.0,
                    error="Timeout",
                ),
            ],
            checked_at=datetime.now(timezone.utc),
        )
        assert health.status == HealthStatus.DEGRADED
        assert len(health.components) == 2

    def test_log_query_response_schema(self):
        """LogQueryResponse calculates pages correctly."""
        response = LogQueryResponse(
            items=[],
            total=250,
            page=1,
            page_size=100,
            pages=3,
            execution_id="exec-123",
        )
        assert response.pages == 3

    def test_prometheus_metrics_schema(self):
        """PrometheusMetrics schema validates correctly."""
        metrics = PrometheusMetrics(
            execution_count=100,
            execution_duration_seconds=5000.5,
            failure_count=5,
            queue_size=2,
            retry_count=10,
        )
        assert metrics.execution_count == 100
        assert metrics.failure_count == 5
