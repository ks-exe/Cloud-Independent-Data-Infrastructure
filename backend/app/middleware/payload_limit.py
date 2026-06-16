"""Payload size limit middleware.

Returns HTTP 413 if request body exceeds configured limit (default 10MB).
"""

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from backend.app.schemas.error import create_error_response


class PayloadSizeLimitMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces maximum request payload size."""

    def __init__(self, app, max_size_mb: int = 10):
        super().__init__(app)
        self.max_size_bytes = max_size_mb * 1024 * 1024

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Check Content-Length header first (fast path)
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_size_bytes:
            return self._create_413_response()

        # For chunked transfers or missing Content-Length, read and check
        if request.method in ("POST", "PUT", "PATCH"):
            body = await request.body()
            if len(body) > self.max_size_bytes:
                return self._create_413_response()

        return await call_next(request)

    def _create_413_response(self) -> JSONResponse:
        """Create a standardized 413 Payload Too Large response."""
        max_mb = self.max_size_bytes // (1024 * 1024)
        error_response = create_error_response(
            code="PAYLOAD_TOO_LARGE",
            message=f"Request body exceeds maximum allowed size of {max_mb}MB",
        )
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content=error_response.model_dump(),
        )
