"""Unit tests for health check system."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.core.health import (
    ComponentHealth,
    ComponentStatus,
    DagsterHealthChecker,
    ElasticsearchHealthChecker,
    HealthCheckAggregator,
    PostgreSQLHealthChecker,
    RabbitMQHealthChecker,
    RedisHealthChecker,
    SystemStatus,
)


# ---------- ComponentHealth dataclass ----------


class TestComponentHealth:
    def test_healthy_component(self):
        result = ComponentHealth(
            name="postgresql",
            status=ComponentStatus.HEALTHY,
            latency_ms=5.2,
        )
        assert result.name == "postgresql"
        assert result.status == ComponentStatus.HEALTHY
        assert result.latency_ms == 5.2
        assert result.error is None

    def test_unhealthy_component_with_error(self):
        result = ComponentHealth(
            name="redis",
            status=ComponentStatus.UNHEALTHY,
            latency_ms=2001.0,
            error="Connection refused",
        )
        assert result.status == ComponentStatus.UNHEALTHY
        assert result.error == "Connection refused"


# ---------- HealthCheckAggregator ----------


class TestHealthCheckAggregator:
    """Tests for the aggregator logic using mock checkers."""

    def _make_checker(self, name: str, is_critical: bool, status: ComponentStatus, latency: float = 5.0):
        """Create a mock checker that returns a fixed result."""
        checker = AsyncMock()
        checker.name = name
        checker.is_critical = is_critical
        checker.check = AsyncMock(
            return_value=ComponentHealth(
                name=name,
                status=status,
                latency_ms=latency,
            )
        )
        return checker

    @pytest.mark.asyncio
    async def test_all_healthy_returns_healthy(self):
        checkers = [
            self._make_checker("postgresql", True, ComponentStatus.HEALTHY),
            self._make_checker("redis", True, ComponentStatus.HEALTHY),
            self._make_checker("rabbitmq", True, ComponentStatus.HEALTHY),
            self._make_checker("elasticsearch", False, ComponentStatus.HEALTHY),
            self._make_checker("dagster", False, ComponentStatus.HEALTHY),
        ]
        aggregator = HealthCheckAggregator(checkers)
        status, results = await aggregator.check_all()

        assert status == SystemStatus.HEALTHY
        assert len(results) == 5
        assert all(r.status == ComponentStatus.HEALTHY for r in results)

    @pytest.mark.asyncio
    async def test_critical_unhealthy_returns_unhealthy(self):
        checkers = [
            self._make_checker("postgresql", True, ComponentStatus.UNHEALTHY),
            self._make_checker("redis", True, ComponentStatus.HEALTHY),
            self._make_checker("rabbitmq", True, ComponentStatus.HEALTHY),
            self._make_checker("elasticsearch", False, ComponentStatus.HEALTHY),
            self._make_checker("dagster", False, ComponentStatus.HEALTHY),
        ]
        aggregator = HealthCheckAggregator(checkers)
        status, results = await aggregator.check_all()

        assert status == SystemStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_non_critical_unhealthy_returns_degraded(self):
        checkers = [
            self._make_checker("postgresql", True, ComponentStatus.HEALTHY),
            self._make_checker("redis", True, ComponentStatus.HEALTHY),
            self._make_checker("rabbitmq", True, ComponentStatus.HEALTHY),
            self._make_checker("elasticsearch", False, ComponentStatus.UNHEALTHY),
            self._make_checker("dagster", False, ComponentStatus.HEALTHY),
        ]
        aggregator = HealthCheckAggregator(checkers)
        status, results = await aggregator.check_all()

        assert status == SystemStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_critical_and_non_critical_unhealthy_returns_unhealthy(self):
        """Critical failure takes precedence over non-critical failure."""
        checkers = [
            self._make_checker("postgresql", True, ComponentStatus.UNHEALTHY),
            self._make_checker("redis", True, ComponentStatus.HEALTHY),
            self._make_checker("rabbitmq", True, ComponentStatus.HEALTHY),
            self._make_checker("elasticsearch", False, ComponentStatus.UNHEALTHY),
            self._make_checker("dagster", False, ComponentStatus.HEALTHY),
        ]
        aggregator = HealthCheckAggregator(checkers)
        status, results = await aggregator.check_all()

        assert status == SystemStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_checker_exception_treated_as_unhealthy(self):
        """If a checker raises an unhandled exception, it's treated as unhealthy."""
        checkers = [
            self._make_checker("postgresql", True, ComponentStatus.HEALTHY),
            self._make_checker("redis", True, ComponentStatus.HEALTHY),
            self._make_checker("rabbitmq", True, ComponentStatus.HEALTHY),
            self._make_checker("elasticsearch", False, ComponentStatus.HEALTHY),
            self._make_checker("dagster", False, ComponentStatus.HEALTHY),
        ]
        # Make postgresql raise an exception
        checkers[0].check = AsyncMock(side_effect=RuntimeError("Connection lost"))
        aggregator = HealthCheckAggregator(checkers)
        status, results = await aggregator.check_all()

        assert status == SystemStatus.UNHEALTHY
        assert results[0].status == ComponentStatus.UNHEALTHY
        assert "Connection lost" in results[0].error


# ---------- Individual checker tests (with mocked dependencies) ----------


class TestPostgreSQLHealthChecker:
    @pytest.mark.asyncio
    async def test_healthy_when_query_succeeds(self):
        checker = PostgreSQLHealthChecker(
            host="localhost", port=5432, user="user", password="pass", database="testdb"
        )
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=1)
        mock_conn.close = AsyncMock()

        with patch("backend.app.core.health.asyncpg.connect", return_value=mock_conn):
            result = await checker.check()

        assert result.status == ComponentStatus.HEALTHY
        assert result.name == "postgresql"
        assert result.latency_ms > 0

    @pytest.mark.asyncio
    async def test_unhealthy_when_connection_fails(self):
        checker = PostgreSQLHealthChecker(
            host="localhost", port=5432, user="user", password="pass", database="testdb"
        )

        with patch(
            "backend.app.core.health.asyncpg.connect",
            side_effect=ConnectionRefusedError("Connection refused"),
        ):
            result = await checker.check()

        assert result.status == ComponentStatus.UNHEALTHY
        assert "Connection refused" in result.error


class TestRedisHealthChecker:
    @pytest.mark.asyncio
    async def test_healthy_when_ping_succeeds(self):
        checker = RedisHealthChecker(host="localhost", port=6379, password="pass")

        with patch("backend.app.core.health.AsyncRedis") as mock_redis_cls:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock(return_value=True)
            mock_client.aclose = AsyncMock()
            mock_redis_cls.return_value = mock_client

            result = await checker.check()

        assert result.status == ComponentStatus.HEALTHY
        assert result.name == "redis"

    @pytest.mark.asyncio
    async def test_unhealthy_when_ping_fails(self):
        checker = RedisHealthChecker(host="localhost", port=6379, password="pass")

        with patch("backend.app.core.health.AsyncRedis") as mock_redis_cls:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock(side_effect=ConnectionError("Cannot connect"))
            mock_client.aclose = AsyncMock()
            mock_redis_cls.return_value = mock_client

            result = await checker.check()

        assert result.status == ComponentStatus.UNHEALTHY
        assert "Cannot connect" in result.error


class TestRabbitMQHealthChecker:
    @pytest.mark.asyncio
    async def test_healthy_when_api_returns_200(self):
        checker = RabbitMQHealthChecker(
            host="localhost", port=5672, user="user", password="pass"
        )

        mock_response = AsyncMock()
        mock_response.status_code = 200

        with patch("backend.app.core.health.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await checker.check()

        assert result.status == ComponentStatus.HEALTHY
        assert result.name == "rabbitmq"

    @pytest.mark.asyncio
    async def test_unhealthy_when_api_returns_error(self):
        checker = RabbitMQHealthChecker(
            host="localhost", port=5672, user="user", password="pass"
        )

        mock_response = AsyncMock()
        mock_response.status_code = 500

        with patch("backend.app.core.health.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await checker.check()

        assert result.status == ComponentStatus.UNHEALTHY


class TestElasticsearchHealthChecker:
    @pytest.mark.asyncio
    async def test_healthy_when_cluster_green(self):
        checker = ElasticsearchHealthChecker(url="http://localhost:9200")

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: {"status": "green", "cluster_name": "test"}

        with patch("backend.app.core.health.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await checker.check()

        assert result.status == ComponentStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_healthy_when_cluster_yellow(self):
        checker = ElasticsearchHealthChecker(url="http://localhost:9200")

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: {"status": "yellow", "cluster_name": "test"}

        with patch("backend.app.core.health.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await checker.check()

        assert result.status == ComponentStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_unhealthy_when_cluster_red(self):
        checker = ElasticsearchHealthChecker(url="http://localhost:9200")

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: {"status": "red", "cluster_name": "test"}

        with patch("backend.app.core.health.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await checker.check()

        assert result.status == ComponentStatus.UNHEALTHY


class TestDagsterHealthChecker:
    @pytest.mark.asyncio
    async def test_healthy_when_server_info_returns_200(self):
        checker = DagsterHealthChecker(host="localhost", port=3000)

        mock_response = AsyncMock()
        mock_response.status_code = 200

        with patch("backend.app.core.health.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await checker.check()

        assert result.status == ComponentStatus.HEALTHY
        assert result.name == "dagster"

    @pytest.mark.asyncio
    async def test_unhealthy_when_connection_refused(self):
        checker = DagsterHealthChecker(host="localhost", port=3000)

        with patch("backend.app.core.health.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                side_effect=ConnectionError("Connection refused")
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await checker.check()

        assert result.status == ComponentStatus.UNHEALTHY


# ---------- API Endpoint tests ----------


class TestHealthEndpoint:
    """Tests for the /api/v1/health endpoint."""

    @pytest.mark.asyncio
    async def test_returns_200_when_all_healthy(self):
        from httpx import ASGITransport, AsyncClient

        from backend.app.core.health import ComponentHealth, ComponentStatus, SystemStatus
        from backend.app.main import app

        mock_results = (
            SystemStatus.HEALTHY,
            [
                ComponentHealth("postgresql", ComponentStatus.HEALTHY, 5.0),
                ComponentHealth("redis", ComponentStatus.HEALTHY, 3.0),
                ComponentHealth("rabbitmq", ComponentStatus.HEALTHY, 10.0),
                ComponentHealth("elasticsearch", ComponentStatus.HEALTHY, 15.0),
                ComponentHealth("dagster", ComponentStatus.HEALTHY, 20.0),
            ],
        )

        with patch(
            "backend.app.api.v1.health.create_health_aggregator_from_settings"
        ) as mock_factory:
            mock_aggregator = AsyncMock()
            mock_aggregator.check_all = AsyncMock(return_value=mock_results)
            mock_factory.return_value = mock_aggregator

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["service_name"] == "cloud-data-platform"
        assert data["status"] == "healthy"
        assert "components" in data
        assert data["components"]["postgresql"]["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_returns_503_when_critical_unhealthy(self):
        from httpx import ASGITransport, AsyncClient

        from backend.app.core.health import ComponentHealth, ComponentStatus, SystemStatus
        from backend.app.main import app

        mock_results = (
            SystemStatus.UNHEALTHY,
            [
                ComponentHealth("postgresql", ComponentStatus.UNHEALTHY, 2001.0, "Timeout"),
                ComponentHealth("redis", ComponentStatus.HEALTHY, 3.0),
                ComponentHealth("rabbitmq", ComponentStatus.HEALTHY, 10.0),
                ComponentHealth("elasticsearch", ComponentStatus.HEALTHY, 15.0),
                ComponentHealth("dagster", ComponentStatus.HEALTHY, 20.0),
            ],
        )

        with patch(
            "backend.app.api.v1.health.create_health_aggregator_from_settings"
        ) as mock_factory:
            mock_aggregator = AsyncMock()
            mock_aggregator.check_all = AsyncMock(return_value=mock_results)
            mock_factory.return_value = mock_aggregator

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/v1/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["components"]["postgresql"]["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_returns_200_when_degraded(self):
        from httpx import ASGITransport, AsyncClient

        from backend.app.core.health import ComponentHealth, ComponentStatus, SystemStatus
        from backend.app.main import app

        mock_results = (
            SystemStatus.DEGRADED,
            [
                ComponentHealth("postgresql", ComponentStatus.HEALTHY, 5.0),
                ComponentHealth("redis", ComponentStatus.HEALTHY, 3.0),
                ComponentHealth("rabbitmq", ComponentStatus.HEALTHY, 10.0),
                ComponentHealth("elasticsearch", ComponentStatus.UNHEALTHY, 2001.0, "Timeout"),
                ComponentHealth("dagster", ComponentStatus.HEALTHY, 20.0),
            ],
        )

        with patch(
            "backend.app.api.v1.health.create_health_aggregator_from_settings"
        ) as mock_factory:
            mock_aggregator = AsyncMock()
            mock_aggregator.check_all = AsyncMock(return_value=mock_results)
            mock_factory.return_value = mock_aggregator

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_root_health_endpoint_still_works(self):
        """The root /health endpoint should still function as a liveness probe."""
        from httpx import ASGITransport, AsyncClient

        from backend.app.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["service_name"] == "cloud-data-platform"
        assert data["status"] == "healthy"
