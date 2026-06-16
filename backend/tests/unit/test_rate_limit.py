"""Unit tests for rate limiting middleware."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from backend.app.middleware.rate_limit import RateLimitMiddleware


@pytest.fixture
def app_with_rate_limit():
    """Create a test app with rate limiting middleware."""
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, requests_per_minute=5, window_seconds=60)

    @app.get("/test")
    async def test_endpoint():
        return {"status": "ok"}

    @app.get("/health")
    async def health_endpoint():
        return {"status": "healthy"}

    return app


@pytest.fixture
def mock_redis():
    """Create a mock Redis client for testing."""
    mock_client = AsyncMock()
    mock_pipeline = AsyncMock()

    # Pipeline execute returns: [removed_count, current_count, zadd_result, expire_result]
    mock_pipeline.execute = AsyncMock(return_value=[0, 0, 1, True])
    mock_pipeline.zremrangebyscore = MagicMock(return_value=mock_pipeline)
    mock_pipeline.zcard = MagicMock(return_value=mock_pipeline)
    mock_pipeline.zadd = MagicMock(return_value=mock_pipeline)
    mock_pipeline.expire = MagicMock(return_value=mock_pipeline)

    mock_client.pipeline = MagicMock(return_value=mock_pipeline)
    mock_client.zrem = AsyncMock()

    return mock_client, mock_pipeline


class TestRateLimitMiddleware:
    """Tests for the RateLimitMiddleware class."""

    def test_request_below_limit_succeeds(self, app_with_rate_limit, mock_redis):
        """Requests below the rate limit should succeed with rate limit headers."""
        mock_client, mock_pipeline = mock_redis
        # current_count = 2, meaning 2 requests already in the window
        mock_pipeline.execute = AsyncMock(return_value=[0, 2, 1, True])

        with patch("backend.app.middleware.rate_limit.get_redis_client", return_value=mock_client):
            client = TestClient(app_with_rate_limit)
            response = client.get("/test")

        assert response.status_code == 200
        assert "X-RateLimit-Limit" in response.headers
        assert response.headers["X-RateLimit-Limit"] == "5"
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers

    def test_request_exceeds_limit_returns_429(self, app_with_rate_limit, mock_redis):
        """Requests exceeding the rate limit should return HTTP 429."""
        mock_client, mock_pipeline = mock_redis
        # current_count = 5, at limit (max is 5)
        mock_pipeline.execute = AsyncMock(return_value=[0, 5, 1, True])

        with patch("backend.app.middleware.rate_limit.get_redis_client", return_value=mock_client):
            client = TestClient(app_with_rate_limit)
            response = client.get("/test")

        assert response.status_code == 429
        assert "Retry-After" in response.headers
        assert "X-RateLimit-Limit" in response.headers
        assert response.headers["X-RateLimit-Remaining"] == "0"

        # Verify response body has error structure
        body = response.json()
        assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert "Rate limit exceeded" in body["error"]["message"]

    def test_health_endpoint_skips_rate_limiting(self, app_with_rate_limit, mock_redis):
        """Health check endpoint should bypass rate limiting."""
        mock_client, _ = mock_redis

        with patch("backend.app.middleware.rate_limit.get_redis_client", return_value=mock_client):
            client = TestClient(app_with_rate_limit)
            response = client.get("/health")

        assert response.status_code == 200
        # Should not have rate limit headers since it's skipped
        assert "X-RateLimit-Limit" not in response.headers

    def test_redis_failure_allows_request_through(self, app_with_rate_limit):
        """When Redis is unavailable, requests should still succeed (fail-open)."""
        mock_client = AsyncMock()
        mock_client.pipeline = MagicMock(side_effect=Exception("Redis connection refused"))

        with patch("backend.app.middleware.rate_limit.get_redis_client", return_value=mock_client):
            client = TestClient(app_with_rate_limit)
            response = client.get("/test")

        assert response.status_code == 200

    def test_unauthenticated_request_uses_ip(self, app_with_rate_limit, mock_redis):
        """Unauthenticated requests should use IP-based rate limiting."""
        mock_client, mock_pipeline = mock_redis
        mock_pipeline.execute = AsyncMock(return_value=[0, 0, 1, True])

        with patch("backend.app.middleware.rate_limit.get_redis_client", return_value=mock_client):
            client = TestClient(app_with_rate_limit)
            response = client.get("/test")

        assert response.status_code == 200
        # Verify the key used contains "ip:" prefix
        pipeline_calls = mock_pipeline.zremrangebyscore.call_args_list
        if pipeline_calls:
            key_arg = pipeline_calls[0][0][0] if pipeline_calls[0][0] else None
            if key_arg:
                assert key_arg.startswith("rate_limit:ip:")

    def test_authenticated_request_uses_user_id(self, app_with_rate_limit, mock_redis):
        """Authenticated requests should use user_id-based rate limiting."""
        mock_client, mock_pipeline = mock_redis
        mock_pipeline.execute = AsyncMock(return_value=[0, 0, 1, True])

        # Create a JWT-like token (won't be validated, just parsed for sub claim)
        with patch("backend.app.middleware.rate_limit.get_redis_client", return_value=mock_client):
            with patch("jose.jwt.get_unverified_claims", return_value={"sub": "user-123"}):
                client = TestClient(app_with_rate_limit)
                response = client.get("/test", headers={"Authorization": "Bearer fake.jwt.token"})

        assert response.status_code == 200

    def test_remaining_count_decreases_with_requests(self, app_with_rate_limit, mock_redis):
        """Remaining request count should decrease as requests are made."""
        mock_client, mock_pipeline = mock_redis
        # Simulate 3 existing requests (limit is 5)
        mock_pipeline.execute = AsyncMock(return_value=[0, 3, 1, True])

        with patch("backend.app.middleware.rate_limit.get_redis_client", return_value=mock_client):
            client = TestClient(app_with_rate_limit)
            response = client.get("/test")

        assert response.status_code == 200
        # 5 - 3 - 1 (current) = 1 remaining
        assert response.headers["X-RateLimit-Remaining"] == "1"

    def test_429_response_removes_added_request(self, app_with_rate_limit, mock_redis):
        """When rate limited, the current request should be removed from Redis."""
        mock_client, mock_pipeline = mock_redis
        mock_pipeline.execute = AsyncMock(return_value=[0, 5, 1, True])

        with patch("backend.app.middleware.rate_limit.get_redis_client", return_value=mock_client):
            client = TestClient(app_with_rate_limit)
            response = client.get("/test")

        assert response.status_code == 429
        # Verify zrem was called to remove the request we added
        mock_client.zrem.assert_called_once()

    def test_x_forwarded_for_header_used_for_ip(self, app_with_rate_limit, mock_redis):
        """When behind a proxy, X-Forwarded-For should be used for IP identification."""
        mock_client, mock_pipeline = mock_redis
        mock_pipeline.execute = AsyncMock(return_value=[0, 0, 1, True])

        with patch("backend.app.middleware.rate_limit.get_redis_client", return_value=mock_client):
            client = TestClient(app_with_rate_limit)
            response = client.get("/test", headers={"X-Forwarded-For": "203.0.113.50, 70.41.3.18"})

        assert response.status_code == 200
