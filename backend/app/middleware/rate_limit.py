"""Rate limiting middleware using Redis sliding window algorithm.

Implements a sliding window rate limiter that tracks requests per user (or IP
for unauthenticated requests) using Redis sorted sets. This provides more
accurate rate limiting than fixed window counters by considering the actual
distribution of requests over time.

Key pattern: rate_limit:{identifier}
Algorithm: Redis sorted sets with timestamps as scores. Each request adds
a member with the current timestamp. Expired entries are pruned on each check.
"""

import logging
import time

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from backend.app.core.config import settings
from backend.app.core.redis import get_redis_client
from backend.app.schemas.error import create_error_response

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding window rate limiter using Redis sorted sets.

    For authenticated requests (JWT token present), uses user_id as the key.
    For unauthenticated requests, uses the client IP address.

    Adds rate limit headers to all responses:
    - X-RateLimit-Limit: Maximum requests allowed in the window
    - X-RateLimit-Remaining: Requests remaining in the current window
    - X-RateLimit-Reset: Unix timestamp when the window resets
    """

    def __init__(
        self,
        app,
        requests_per_minute: int | None = None,
        window_seconds: int | None = None,
    ):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute or settings.rate_limit_requests_per_minute
        self.window_seconds = window_seconds or settings.rate_limit_window_seconds

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip rate limiting for health check endpoints
        if request.url.path in ("/health", "/docs", "/redoc", "/openapi.json"):
            return await call_next(request)

        identifier = self._get_identifier(request)
        now = time.time()
        window_start = now - self.window_seconds

        try:
            redis_client = get_redis_client()
            key = f"rate_limit:{identifier}"

            # Use a pipeline for atomic operations
            pipe = redis_client.pipeline()

            # Remove expired entries outside the sliding window
            pipe.zremrangebyscore(key, 0, window_start)

            # Count current requests in the window
            pipe.zcard(key)

            # Add the current request with timestamp as score and unique member
            member = f"{now}:{id(request)}"
            pipe.zadd(key, {member: now})

            # Set TTL on the key to auto-cleanup
            pipe.expire(key, self.window_seconds + 1)

            results = await pipe.execute()

            # results[0] = number of removed entries
            # results[1] = current count (before adding this request)
            current_count = results[1]

            # Calculate remaining requests and reset time
            remaining = max(0, self.requests_per_minute - current_count - 1)
            reset_time = int(now + self.window_seconds)

            # Check if rate limit is exceeded
            if current_count >= self.requests_per_minute:
                # Remove the request we just added since it's being rejected
                await redis_client.zrem(key, member)

                retry_after = int(self.window_seconds - (now - window_start))
                retry_after = max(1, retry_after)

                return self._create_429_response(
                    retry_after=retry_after,
                    limit=self.requests_per_minute,
                    reset_time=reset_time,
                )

            # Proceed with the request
            response = await call_next(request)

            # Add rate limit headers to all responses
            response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Reset"] = str(reset_time)

            return response

        except Exception as exc:
            # If Redis is unavailable, allow the request through (fail-open)
            # to avoid blocking legitimate traffic
            logger.warning("Rate limiter Redis error (fail-open): %s", str(exc))
            return await call_next(request)

    def _get_identifier(self, request: Request) -> str:
        """Extract the rate limit identifier from the request.

        Uses user_id from JWT token if available, otherwise falls back to client IP.
        """
        # Try to extract user_id from Authorization header
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            user_id = self._extract_user_id_from_token(token)
            if user_id:
                return f"user:{user_id}"

        # Fall back to client IP
        client_ip = self._get_client_ip(request)
        return f"ip:{client_ip}"

    def _extract_user_id_from_token(self, token: str) -> str | None:
        """Extract user_id from JWT token without full validation.

        This is a lightweight extraction for rate limiting purposes only.
        Full token validation happens in the auth middleware.
        """
        try:
            from jose import jwt

            # Decode without verification for rate limiting key extraction
            # Auth middleware handles full validation
            payload = jwt.get_unverified_claims(token)
            return payload.get("sub")
        except Exception:
            return None

    def _get_client_ip(self, request: Request) -> str:
        """Get the client IP address, respecting X-Forwarded-For for proxied requests."""
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            # Take the first IP in the chain (original client)
            return forwarded_for.split(",")[0].strip()

        # Fall back to direct client address
        if request.client:
            return request.client.host
        return "unknown"

    def _create_429_response(
        self,
        retry_after: int,
        limit: int,
        reset_time: int,
    ) -> JSONResponse:
        """Create a standardized 429 Too Many Requests response."""
        error_response = create_error_response(
            code="RATE_LIMIT_EXCEEDED",
            message=f"Rate limit exceeded. Maximum {limit} requests per minute allowed. "
            f"Please retry after {retry_after} seconds.",
        )
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content=error_response.model_dump(),
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(reset_time),
            },
        )
