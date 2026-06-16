"""FastAPI application entry point.

Configures the application with:
- Versioned API router (/api/v1/)
- Global exception handlers (sanitized error responses)
- CORS middleware
- CSRF token-based protection for state-modifying endpoints
- Payload size limit middleware (default 10MB)
- API version response header (X-API-Version: v1)
- OpenAPI 3.0 auto-generated documentation at /docs and /openapi.json (no auth required)
"""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.api.v1.router import api_v1_router
from backend.app.core.config import settings
from backend.app.middleware.api_version import APIVersionHeaderMiddleware
from backend.app.middleware.csrf import CSRFMiddleware
from backend.app.middleware.exception_handler import (
    generic_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from backend.app.middleware.payload_limit import PayloadSizeLimitMiddleware
from backend.app.middleware.rate_limit import RateLimitMiddleware


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Cloud-Independent Data Platform API",
        description=(
            "Self-service data infrastructure API for regulated industries. "
            "Provides pipeline building, scheduling, monitoring, lineage tracking, "
            "and audit capabilities for on-premises deployments without public cloud dependency."
        ),
        version=settings.app_version,
        # OpenAPI docs always accessible without auth (Requirement 13.1)
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact={
            "name": "Platform Engineering Team",
            "email": "platform-support@example.com",
        },
        license_info={
            "name": "Proprietary",
        },
        openapi_tags=[
            {"name": "Authentication", "description": "Login, logout, token refresh, password reset"},
            {"name": "Users", "description": "User account CRUD and role management"},
            {"name": "Connectors", "description": "Data connector CRUD, testing, and health checks"},
            {"name": "Pipelines", "description": "Pipeline CRUD, validation, execution, and versioning"},
            {"name": "Schedules", "description": "Pipeline schedule CRUD, pause/resume, cron validation"},
            {"name": "Monitoring", "description": "Dashboard metrics, system health, and log queries"},
            {"name": "Lineage", "description": "Data lineage graph traversal and queries"},
            {"name": "Audit", "description": "Audit log search and export"},
            {"name": "Notifications", "description": "User notification management"},
            {"name": "Health", "description": "Service health check endpoints"},
            {"name": "Settings", "description": "System settings management"},
            {"name": "System", "description": "Root-level system endpoints"},
        ],
    )

    # Register exception handlers
    _register_exception_handlers(app)

    # Register middleware (order matters: last added = first executed)
    _register_middleware(app)

    # Register routers
    app.include_router(api_v1_router)

    # Root health check (outside versioned API)
    @app.get("/health", tags=["System"], operation_id="root_health_check")
    async def root_health():
        """Basic application health check."""
        return {"service_name": settings.app_name, "status": "healthy"}

    return app


def _register_exception_handlers(app: FastAPI) -> None:
    """Register global exception handlers for sanitized error responses."""
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)


def _register_middleware(app: FastAPI) -> None:
    """Register middleware stack.

    Middleware execution order (first to last):
    1. API Version Header - adds X-API-Version to all responses
    2. Rate Limiting - enforces per-user request limits (429)
    3. Payload Size Limit - rejects oversized requests (413)
    4. CSRF Protection - validates tokens on state-modifying requests
    5. CORS - handles cross-origin requests
    """
    # API Version Header (outermost - runs on all responses)
    app.add_middleware(APIVersionHeaderMiddleware, version="v1")

    # Rate Limiting (sliding window via Redis)
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=settings.rate_limit_requests_per_minute,
        window_seconds=settings.rate_limit_window_seconds,
    )

    # Payload Size Limit
    app.add_middleware(PayloadSizeLimitMiddleware, max_size_mb=settings.max_payload_size_mb)

    # CSRF Protection
    app.add_middleware(
        CSRFMiddleware,
        secret_key=settings.csrf_secret_key,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:5173"],  # Dev frontends
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=[
            "X-API-Version",
            "X-CSRF-Token",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
            "Retry-After",
        ],
    )


# Create the application instance
app = create_app()
