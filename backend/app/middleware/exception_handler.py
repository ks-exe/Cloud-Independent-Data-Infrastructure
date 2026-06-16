"""Global exception handler that sanitizes internal details from error responses.

Never exposes: stack traces, SQL queries, file paths, or server hostnames.
"""

import re
import logging

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.schemas.error import ErrorDetail, create_error_response

logger = logging.getLogger(__name__)

# Patterns to detect internal details that must never be exposed
_INTERNAL_PATTERNS = [
    re.compile(r"(?:\/[\w.-]+){2,}"),  # File paths
    re.compile(r"(?:SELECT|INSERT|UPDATE|DELETE|FROM|WHERE|JOIN)\s", re.IGNORECASE),  # SQL fragments
    re.compile(r"Traceback \(most recent call last\)"),  # Stack traces
    re.compile(r"File \".*\", line \d+"),  # Python traceback lines
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),  # IP addresses (server internal)
    re.compile(r"\b[a-zA-Z0-9-]+\.(?:internal|local|corp)\b"),  # Internal hostnames
]

_SAFE_GENERIC_MESSAGE = "An internal error occurred. Please contact support if the problem persists."


def _sanitize_message(message: str) -> str:
    """Remove any internal details from an error message."""
    for pattern in _INTERNAL_PATTERNS:
        if pattern.search(message):
            return _SAFE_GENERIC_MESSAGE
    return message


def _map_validation_error_code(error_type: str) -> str:
    """Map Pydantic validation error types to structured error codes."""
    mapping = {
        "missing": "FIELD_REQUIRED",
        "value_error": "INVALID_VALUE",
        "type_error": "INVALID_TYPE",
        "string_too_short": "STRING_TOO_SHORT",
        "string_too_long": "STRING_TOO_LONG",
        "string_pattern_mismatch": "PATTERN_MISMATCH",
        "int_parsing": "INVALID_INTEGER",
        "float_parsing": "INVALID_FLOAT",
        "bool_parsing": "INVALID_BOOLEAN",
        "enum": "INVALID_ENUM_VALUE",
        "uuid_parsing": "INVALID_UUID",
        "url_parsing": "INVALID_URL",
        "json_invalid": "INVALID_JSON",
        "greater_than": "VALUE_TOO_SMALL",
        "less_than": "VALUE_TOO_LARGE",
        "greater_than_equal": "VALUE_TOO_SMALL",
        "less_than_equal": "VALUE_TOO_LARGE",
        "list_type": "INVALID_LIST",
    }
    return mapping.get(error_type, "VALIDATION_ERROR")


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Handle HTTP exceptions with sanitized messages."""
    message = _sanitize_message(str(exc.detail)) if exc.detail else "Request failed"

    error_response = create_error_response(
        code=f"HTTP_{exc.status_code}",
        message=message,
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=error_response.model_dump(),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle request validation errors with structured error arrays.

    Returns all validation errors in a single response (HTTP 422).
    """
    details: list[ErrorDetail] = []

    for error in exc.errors():
        # Build field path from location tuple (e.g., ("body", "username") -> "username")
        loc = error.get("loc", ())
        # Skip the first element if it's "body", "query", "path", etc.
        field_parts = [str(part) for part in loc if part not in ("body", "query", "path", "header")]
        field_name = ".".join(field_parts) if field_parts else None

        # Get the rejected value safely
        rejected_value = error.get("input")

        # Sanitize rejected value - don't expose overly large payloads
        if isinstance(rejected_value, str) and len(rejected_value) > 200:
            rejected_value = rejected_value[:200] + "..."
        elif isinstance(rejected_value, (dict, list)):
            rejected_value = None  # Don't echo complex objects

        details.append(
            ErrorDetail(
                error_code=_map_validation_error_code(error.get("type", "")),
                field=field_name,
                rejected_value=rejected_value,
                message=error.get("msg", "Validation error"),
            )
        )

    error_response = create_error_response(
        code="VALIDATION_ERROR",
        message="Request validation failed",
        details=details,
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=error_response.model_dump(),
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle uncaught exceptions without exposing internal details.

    Logs the full exception for debugging but returns a safe generic message.
    """
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)

    error_response = create_error_response(
        code="INTERNAL_ERROR",
        message=_SAFE_GENERIC_MESSAGE,
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_response.model_dump(),
    )
