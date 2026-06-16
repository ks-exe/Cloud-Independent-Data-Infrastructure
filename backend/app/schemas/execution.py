"""Pydantic schemas for pipeline execution API request/response models.

Covers:
- ExecutionRequest (input for triggering execution)
- ExecutionStatus (status polling response)
- PipelineRunResponse (full run record response)

Requirements: 6.1, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 16.5
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ExecutionRequest(BaseModel):
    """Schema for triggering a pipeline execution."""

    trigger_type: str = Field(
        default="manual",
        description="Trigger type: manual or scheduled",
    )


class ExecutionStatus(BaseModel):
    """Schema for execution status polling response."""

    run_id: uuid.UUID
    pipeline_id: uuid.UUID
    status: str = Field(
        ...,
        description="Execution status: queued, running, succeeded, failed",
    )
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    node_row_counts: dict[str, Any] | None = None
    retry_count: int = 0
    error_message: str | None = None
    failing_node: str | None = None

    model_config = {"from_attributes": True}


class PipelineRunResponse(BaseModel):
    """Schema for a full pipeline run record response."""

    id: uuid.UUID
    pipeline_id: uuid.UUID
    pipeline_version: int
    status: str
    trigger_type: str
    triggered_by: uuid.UUID
    retry_count: int = 0
    node_row_counts: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
