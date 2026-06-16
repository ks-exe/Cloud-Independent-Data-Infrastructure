"""Pydantic schemas for schedule API request/response models."""

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from backend.app.core.validators import pydantic_validate_cron


class ScheduleStatus(str, Enum):
    """Schedule lifecycle status."""

    ACTIVE = "active"
    PAUSED = "paused"


class ScheduleCreate(BaseModel):
    """Schema for creating a new pipeline schedule."""

    pipeline_id: uuid.UUID = Field(..., description="Pipeline to schedule")
    cron_expression: str = Field(
        ...,
        min_length=5,
        max_length=100,
        description="Standard 5-field cron expression (minute hour day month weekday)",
    )

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: str) -> str:
        """Validate cron expression format at schema level."""
        return pydantic_validate_cron(v)


class ScheduleUpdate(BaseModel):
    """Schema for updating an existing schedule's cron expression."""

    cron_expression: str = Field(
        ...,
        min_length=5,
        max_length=100,
        description="Standard 5-field cron expression (minute hour day month weekday)",
    )

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: str) -> str:
        """Validate cron expression format at schema level."""
        return pydantic_validate_cron(v)


class ScheduleResponse(BaseModel):
    """Schema for schedule API responses."""

    id: uuid.UUID
    pipeline_id: uuid.UUID
    cron_expression: str
    status: str
    dagster_schedule_name: str | None = None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ScheduleListResponse(BaseModel):
    """Paginated schedule list response."""

    schedules: list[ScheduleResponse]
    total: int


class CronValidationResult(BaseModel):
    """Result of cron expression validation."""

    valid: bool
    expression: str
    error: str | None = None
    description: str | None = None
    minimum_interval_seconds: int | None = None


class ScheduleSkipRecord(BaseModel):
    """Record of a skipped scheduled execution."""

    schedule_id: uuid.UUID
    pipeline_id: uuid.UUID
    skip_reason: str
    skipped_at: datetime
