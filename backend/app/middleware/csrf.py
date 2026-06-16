"""CSRF token-based protection for state-modifying endpoints.

Implements the double-submit cookie pattern:
- A random CSRF token is set in a cookie (readable by JavaScript)
- State-modifying requests must include the same token in the X-CSRF-Token header
- The middleware validates that header value matches cookie value
"""

import hmac
import secrets

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from backend.app.schemas.error import create_error_response

# HTTP methods that modify state and require CSRF protection
STATE_MODIFYING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Header name for CSRF token
CSRF_HEADER = "X-CSRF-Token"

# Cookie name for CSRF token
CSRF_COOKIE = "csrf_token"


class CSRFMiddleware(BaseHTTPMiddleware):
    """Middleware implementing double-submit cookie CSRF protection."""

    def __init__(self, app, secret_key: str, exempt_paths: list[str] | None = None):
        super().__init__(app)
        self.secret_key = secret_key
        # Paths exempt from CSRF (e.g., login, token refresh)
        self.exempt_paths = exempt_paths or [
            "/api/v1/auth/login",
            "/api/v1/auth/refresh",
            "/api/v1/auth/reset-password-request",
            "/health",
            "/docs",
            "/openapi.json",
            "/redoc",
        ]

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip CSRF for safe methods (GET, HEAD, OPTIONS)
        if request.method not in STATE_MODIFYING_METHODS:
            response = await call_next(request)
            # Ensure CSRF cookie is set for clients to read
            self._ensure_csrf_cookie(response, request)
            return response

        # Skip exempt paths
        if self._is_exempt(request.url.path):
            response = await call_next(request)
            self._ensure_csrf_cookie(response, request)
            return response

        # Validate CSRF token (double-submit cookie pattern)
        cookie_token = request.cookies.get(CSRF_COOKIE)
        header_token = request.headers.get(CSRF_HEADER)

        if not cookie_token or not header_token:
            return self._create_csrf_error("CSRF token missing")

        if not self._tokens_match(cookie_token, header_token):
            return self._create_csrf_error("CSRF token invalid")

        response = await call_next(request)
        self._ensure_csrf_cookie(response, request)
        return response

    def _tokens_match(self, cookie_token: str, header_token: str) -> bool:
        """Validate that header token matches cookie token using constant-time comparison."""
        return hmac.compare_digest(cookie_token, header_token)

    def _is_exempt(self, path: str) -> bool:
        """Check if the path is exempt from CSRF validation."""
        return any(path.startswith(exempt) for exempt in self.exempt_paths)

    def _ensure_csrf_cookie(self, response: Response, request: Request) -> None:
        """Set CSRF cookie if not already present in the request."""
        if not request.cookies.get(CSRF_COOKIE):
            token = secrets.token_hex(32)
            response.set_cookie(
                key=CSRF_COOKIE,
                value=token,
                httponly=False,  # Must be readable by JavaScript
                samesite="strict",
                secure=True,
                path="/",
            )

    def _create_csrf_error(self, message: str) -> JSONResponse:
        """Create a standardized CSRF error response."""
        error_response = create_error_response(
            code="CSRF_ERROR",
            message=message,
        )
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=error_response.model_dump(),
        )
