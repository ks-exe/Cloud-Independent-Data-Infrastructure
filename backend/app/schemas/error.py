"""Structured error response schemas."""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Individual validation error detail."""

    error_code: str = Field(..., description="Machine-readable error code")
    field: str | None = Field(None, description="Field that caused the error")
    rejected_value: Any | None = Field(None, description="Value that was rejected")
    message: str = Field(..., description="Human-readable error message")


class ErrorBody(BaseModel):
    """Error response body."""

    code: str = Field(..., description="Top-level error code")
    message: str = Field(..., description="Summary error message")
    details: list[ErrorDetail] = Field(default_factory=list, description="Array of individual errors")


class ErrorResponse(BaseModel):
    """Standard API error response envelope."""

    error: ErrorBody
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


def create_error_response(
    code: str,
    message: str,
    details: list[ErrorDetail] | None = None,
    request_id: str | None = None,
) -> ErrorResponse:
    """Factory function to create a standardized error response."""
    return ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            details=details or [],
        ),
        request_id=request_id or str(uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
