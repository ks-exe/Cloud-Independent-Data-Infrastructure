"""API version header middleware.

Adds X-API-Version header to all responses.
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response


class APIVersionHeaderMiddleware(BaseHTTPMiddleware):
    """Middleware that adds an API version header to all responses."""

    def __init__(self, app, version: str = "v1"):
        super().__init__(app)
        self.version = version

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-API-Version"] = self.version
        return response
