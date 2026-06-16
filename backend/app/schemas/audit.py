"""Pydantic schemas for audit log operations."""

import enum
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class AuditEventType(str, enum.Enum):
    """Enumeration of all auditable event types."""

    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    USER_CREATION = "USER_CREATION"
    USER_UPDATE = "USER_UPDATE"
    USER_DELETION = "USER_DELETION"
    PIPELINE_CREATION = "PIPELINE_CREATION"
    PIPELINE_UPDATE = "PIPELINE_UPDATE"
    PIPELINE_EXECUTION = "PIPELINE_EXECUTION"
    CONNECTOR_CREATION = "CONNECTOR_CREATION"
    CONNECTOR_MODIFICATION = "CONNECTOR_MODIFICATION"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    UNAUTHENTICATED_ACCESS = "UNAUTHENTICATED_ACCESS"


class AuditResult(str, enum.Enum):
    """Result status of an audited action."""

    SUCCESS = "success"
    FAILURE = "failure"


class AuditEventCreate(BaseModel):
    """Schema for creating a new audit log entry."""

    event_type: AuditEventType = Field(..., description="Type of the audited event")
    actor_id: UUID = Field(..., description="ID of the user who performed the action")
    target_resource_id: str | None = Field(
        None, description="ID of the affected resource"
    )
    target_resource_type: str | None = Field(
        None, description="Type of the affected resource (e.g., user, pipeline, connector)"
    )
    result: AuditResult = Field(..., description="Outcome of the action")
    ip_address: str | None = Field(None, description="IP address of the actor")

    @field_validator("ip_address")
    @classmethod
    def validate_ip_address(cls, v: str | None) -> str | None:
        """Basic IP address validation."""
        if v is None:
            return v
        # Allow IPv4 and IPv6 addresses
        if len(v) > 45:
            raise ValueError("IP address must be at most 45 characters")
        return v


class AuditLogResponse(BaseModel):
    """Schema for a single audit log entry in API responses."""

    id: UUID
    event_type: str
    actor_id: UUID
    target_resource_id: str | None
    target_resource_type: str | None
    result: str
    ip_address: str | None
    timestamp: datetime

    model_config = {"from_attributes": True}


class AuditFilter(BaseModel):
    """Filter parameters for searching audit logs."""

    event_type: AuditEventType | None = Field(None, description="Filter by event type")
    actor_id: UUID | None = Field(None, description="Filter by actor user ID")
    target_resource_id: str | None = Field(None, description="Filter by target resource ID")
    start_time: datetime | None = Field(None, description="Filter events from this time (inclusive)")
    end_time: datetime | None = Field(None, description="Filter events until this time (inclusive)")
    result: AuditResult | None = Field(None, description="Filter by result status")

    @field_validator("end_time")
    @classmethod
    def end_time_after_start_time(cls, v: datetime | None, info: Any) -> datetime | None:
        """Ensure end_time is after start_time if both are provided."""
        if v is not None and info.data.get("start_time") is not None:
            if v < info.data["start_time"]:
                raise ValueError("end_time must be after start_time")
        return v


class PaginatedAuditResponse(BaseModel):
    """Paginated response for audit log search results."""

    items: list[AuditLogResponse]
    total: int = Field(..., description="Total number of matching records")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Number of items per page")
    pages: int = Field(..., description="Total number of pages")


class StorageStatus(BaseModel):
    """Response for audit log storage capacity check."""

    total_records: int = Field(..., description="Total number of audit log records")
    estimated_size_mb: float = Field(..., description="Estimated storage size in MB")
    capacity_threshold_percent: float = Field(
        ..., description="Configured warning threshold (0.0-1.0)"
    )
    current_usage_percent: float = Field(
        ..., description="Current usage as a fraction of estimated capacity"
    )
    warning: bool = Field(..., description="Whether the storage warning threshold is exceeded")
    retention_days: int = Field(..., description="Configured retention period in days")


class ExportFormat(str, enum.Enum):
    """Supported export formats."""

    CSV = "csv"
    JSON = "json"
