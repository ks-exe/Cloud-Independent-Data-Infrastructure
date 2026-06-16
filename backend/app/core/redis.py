"""Redis client utility for caching, rate limiting, and token management.

Provides a singleton async Redis client instance configured from application settings.
"""

import logging

import redis.asyncio as aioredis

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

# Module-level Redis client (lazy-initialized)
_redis_client: aioredis.Redis | None = None


def get_redis_client() -> aioredis.Redis:
    """Get or create the async Redis client singleton.

    Returns:
        An async Redis client connected to the configured Redis instance.
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
    return _redis_client


async def close_redis_client() -> None:
    """Close the Redis client connection pool gracefully."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("Redis client connection closed")
