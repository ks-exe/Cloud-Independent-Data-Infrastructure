"""Pydantic schemas for notification operations."""

import enum
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from backend.app.core.validators import MAX_TEXT_LENGTH


class NotificationEventType(str, enum.Enum):
    """Enumeration of notification event types."""

    PIPELINE_FAILURE = "pipeline_failure"
    CONNECTOR_HEALTH_FAILURE = "connector_health_failure"
    RESOURCE_THRESHOLD = "resource_threshold"


class NotificationCreate(BaseModel):
    """Schema for creating a notification internally (from event processing)."""

    user_id: UUID = Field(..., description="Target user to receive the notification")
    event_type: NotificationEventType = Field(..., description="Type of notification event")
    source_resource_id: str | None = Field(
        None, description="ID of the resource that triggered the event"
    )
    summary: str = Field(..., description="Human-readable notification summary", max_length=MAX_TEXT_LENGTH)
    expires_at: datetime | None = Field(None, description="Expiration timestamp for auto-cleanup")


class NotificationResponse(BaseModel):
    """Schema for a single notification in API responses."""

    id: UUID
    user_id: UUID
    event_type: str
    source_resource_id: str | None
    summary: str
    is_read: bool
    recurrence_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationListResponse(BaseModel):
    """Paginated response for user notifications."""

    items: list[NotificationResponse]
    total: int = Field(..., description="Total number of notifications")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Items per page")
    pages: int = Field(..., description="Total number of pages")


class NotificationEvent(BaseModel):
    """Schema representing an incoming notification event to be processed.

    Used as input to NotificationService.create_notification to determine
    recipients and generate appropriate notification summaries.
    """

    event_type: NotificationEventType = Field(..., description="Type of event")
    source_resource_id: str | None = Field(
        None, description="ID of the resource that triggered the event"
    )

    # Pipeline failure fields
    pipeline_name: str | None = Field(None, description="Name of the failed pipeline")
    execution_id: str | None = Field(None, description="Pipeline execution identifier")
    failure_timestamp: datetime | None = Field(None, description="When the failure occurred")
    failing_node: str | None = Field(None, description="Name of the node that failed")
    pipeline_owner_id: UUID | None = Field(None, description="Owner user ID for pipeline failures")

    # Connector health failure fields
    connector_name: str | None = Field(None, description="Name of the failed connector")
    connector_type: str | None = Field(None, description="Type of the connector")

    # Resource threshold fields
    resource_name: str | None = Field(None, description="Name of the resource exceeding threshold")
    current_value: str | None = Field(None, description="Current resource value")
    threshold_value: str | None = Field(None, description="Threshold that was exceeded")
