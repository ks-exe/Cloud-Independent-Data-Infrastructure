"""Health checker classes for service components.

Each checker connects to its respective service and returns a status
within a 2-second timeout. Components are classified as critical or
non-critical for overall system health assessment.

Critical services: PostgreSQL, Redis, RabbitMQ
Non-critical services: Elasticsearch, Dagster
"""

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

import asyncpg
import httpx
from redis.asyncio import Redis as AsyncRedis


class ComponentStatus(str, Enum):
    """Health status for an individual component."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


class SystemStatus(str, Enum):
    """Overall system health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class ComponentHealth:
    """Result of a single component health check."""

    name: str
    status: ComponentStatus
    latency_ms: float
    error: str | None = None


HEALTH_CHECK_TIMEOUT = 2.0  # seconds


class HealthChecker(Protocol):
    """Protocol for health checker implementations."""

    @property
    def name(self) -> str: ...

    @property
    def is_critical(self) -> bool: ...

    async def check(self) -> ComponentHealth: ...


class PostgreSQLHealthChecker:
    """Health checker for PostgreSQL database."""

    name = "postgresql"
    is_critical = True

    def __init__(self, host: str, port: int, user: str, password: str, database: str):
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._database = database

    async def check(self) -> ComponentHealth:
        start = time.perf_counter()
        try:
            conn = await asyncio.wait_for(
                asyncpg.connect(
                    host=self._host,
                    port=self._port,
                    user=self._user,
                    password=self._password,
                    database=self._database,
                ),
                timeout=HEALTH_CHECK_TIMEOUT,
            )
            try:
                await conn.fetchval("SELECT 1")
            finally:
                await conn.close()
            latency = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name=self.name,
                status=ComponentStatus.HEALTHY,
                latency_ms=round(latency, 2),
            )
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name=self.name,
                status=ComponentStatus.UNHEALTHY,
                latency_ms=round(latency, 2),
                error=str(exc),
            )


class RedisHealthChecker:
    """Health checker for Redis cache."""

    name = "redis"
    is_critical = True

    def __init__(self, host: str, port: int, password: str, db: int = 0):
        self._host = host
        self._port = port
        self._password = password
        self._db = db

    async def check(self) -> ComponentHealth:
        start = time.perf_counter()
        try:
            client = AsyncRedis(
                host=self._host,
                port=self._port,
                password=self._password,
                db=self._db,
                socket_connect_timeout=HEALTH_CHECK_TIMEOUT,
            )
            try:
                result = await asyncio.wait_for(
                    client.ping(), timeout=HEALTH_CHECK_TIMEOUT
                )
                if not result:
                    raise ConnectionError("Redis PING returned False")
            finally:
                await client.aclose()
            latency = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name=self.name,
                status=ComponentStatus.HEALTHY,
                latency_ms=round(latency, 2),
            )
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name=self.name,
                status=ComponentStatus.UNHEALTHY,
                latency_ms=round(latency, 2),
                error=str(exc),
            )


class RabbitMQHealthChecker:
    """Health checker for RabbitMQ message broker.

    Uses the RabbitMQ management API to check health.
    """

    name = "rabbitmq"
    is_critical = True

    def __init__(self, host: str, port: int, user: str, password: str):
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        # Management API defaults to port 15672
        self._management_port = 15672

    async def check(self) -> ComponentHealth:
        start = time.perf_counter()
        url = f"http://{self._host}:{self._management_port}/api/healthchecks/node"
        try:
            async with httpx.AsyncClient(timeout=HEALTH_CHECK_TIMEOUT) as client:
                resp = await client.get(url, auth=(self._user, self._password))
                if resp.status_code == 200:
                    latency = (time.perf_counter() - start) * 1000
                    return ComponentHealth(
                        name=self.name,
                        status=ComponentStatus.HEALTHY,
                        latency_ms=round(latency, 2),
                    )
                else:
                    latency = (time.perf_counter() - start) * 1000
                    return ComponentHealth(
                        name=self.name,
                        status=ComponentStatus.UNHEALTHY,
                        latency_ms=round(latency, 2),
                        error=f"Management API returned {resp.status_code}",
                    )
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name=self.name,
                status=ComponentStatus.UNHEALTHY,
                latency_ms=round(latency, 2),
                error=str(exc),
            )


class ElasticsearchHealthChecker:
    """Health checker for Elasticsearch log storage."""

    name = "elasticsearch"
    is_critical = False

    def __init__(self, url: str):
        self._url = url.rstrip("/")

    async def check(self) -> ComponentHealth:
        start = time.perf_counter()
        health_url = f"{self._url}/_cluster/health"
        try:
            async with httpx.AsyncClient(timeout=HEALTH_CHECK_TIMEOUT) as client:
                resp = await client.get(health_url)
                if resp.status_code == 200:
                    data = resp.json()
                    cluster_status = data.get("status", "unknown")
                    # Elasticsearch reports green/yellow/red
                    is_healthy = cluster_status in ("green", "yellow")
                    latency = (time.perf_counter() - start) * 1000
                    return ComponentHealth(
                        name=self.name,
                        status=ComponentStatus.HEALTHY
                        if is_healthy
                        else ComponentStatus.UNHEALTHY,
                        latency_ms=round(latency, 2),
                        error=None
                        if is_healthy
                        else f"Cluster status: {cluster_status}",
                    )
                else:
                    latency = (time.perf_counter() - start) * 1000
                    return ComponentHealth(
                        name=self.name,
                        status=ComponentStatus.UNHEALTHY,
                        latency_ms=round(latency, 2),
                        error=f"Elasticsearch returned {resp.status_code}",
                    )
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name=self.name,
                status=ComponentStatus.UNHEALTHY,
                latency_ms=round(latency, 2),
                error=str(exc),
            )


class DagsterHealthChecker:
    """Health checker for Dagster orchestration webserver."""

    name = "dagster"
    is_critical = False

    def __init__(self, host: str, port: int):
        self._host = host
        self._port = port

    async def check(self) -> ComponentHealth:
        start = time.perf_counter()
        url = f"http://{self._host}:{self._port}/server_info"
        try:
            async with httpx.AsyncClient(timeout=HEALTH_CHECK_TIMEOUT) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    latency = (time.perf_counter() - start) * 1000
                    return ComponentHealth(
                        name=self.name,
                        status=ComponentStatus.HEALTHY,
                        latency_ms=round(latency, 2),
                    )
                else:
                    latency = (time.perf_counter() - start) * 1000
                    return ComponentHealth(
                        name=self.name,
                        status=ComponentStatus.UNHEALTHY,
                        latency_ms=round(latency, 2),
                        error=f"Dagster returned {resp.status_code}",
                    )
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name=self.name,
                status=ComponentStatus.UNHEALTHY,
                latency_ms=round(latency, 2),
                error=str(exc),
            )


class HealthCheckAggregator:
    """Aggregates health checks from all service components.

    Determines overall system status based on component health:
    - healthy: all services responding
    - degraded: one or more non-critical services unresponsive
    - unhealthy: any critical service unresponsive
    """

    def __init__(self, checkers: list[HealthChecker]):
        self._checkers = checkers

    async def check_all(self) -> tuple[SystemStatus, list[ComponentHealth]]:
        """Run all health checks concurrently and determine system status."""
        results = await asyncio.gather(
            *(checker.check() for checker in self._checkers),
            return_exceptions=True,
        )

        component_results: list[ComponentHealth] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                component_results.append(
                    ComponentHealth(
                        name=self._checkers[i].name,
                        status=ComponentStatus.UNHEALTHY,
                        latency_ms=0.0,
                        error=str(result),
                    )
                )
            else:
                component_results.append(result)

        # Determine overall status
        critical_unhealthy = any(
            r.status == ComponentStatus.UNHEALTHY
            for r, checker in zip(component_results, self._checkers)
            if checker.is_critical
        )
        non_critical_unhealthy = any(
            r.status == ComponentStatus.UNHEALTHY
            for r, checker in zip(component_results, self._checkers)
            if not checker.is_critical
        )

        if critical_unhealthy:
            system_status = SystemStatus.UNHEALTHY
        elif non_critical_unhealthy:
            system_status = SystemStatus.DEGRADED
        else:
            system_status = SystemStatus.HEALTHY

        return system_status, component_results


def create_health_aggregator_from_settings() -> HealthCheckAggregator:
    """Factory that creates the health aggregator from application settings."""
    from backend.app.core.config import settings

    checkers: list[HealthChecker] = [
        PostgreSQLHealthChecker(
            host=settings.postgres_host,
            port=settings.postgres_port,
            user=settings.postgres_user,
            password=settings.postgres_password,
            database=settings.postgres_db,
        ),
        RedisHealthChecker(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password,
            db=settings.redis_db,
        ),
        RabbitMQHealthChecker(
            host=settings.rabbitmq_host,
            port=settings.rabbitmq_port,
            user=settings.rabbitmq_user,
            password=settings.rabbitmq_password,
        ),
        ElasticsearchHealthChecker(url=settings.elasticsearch_url),
        DagsterHealthChecker(
            host=settings.dagster_webserver_host,
            port=settings.dagster_webserver_port,
        ),
    ]

    return HealthCheckAggregator(checkers)
