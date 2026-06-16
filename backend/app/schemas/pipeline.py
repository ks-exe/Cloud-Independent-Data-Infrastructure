"""Pydantic schemas for pipeline API request/response models.

Covers:
- PipelineCreate, PipelineUpdate (input)
- PipelineResponse, PipelineVersionResponse, PipelineListResponse (output)
- NodeSchema, EdgeSchema (embedded structures)

Requirements: 5.1, 5.2, 5.5, 5.6, 5.8, 5.9, 5.10, 5.12
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class NodeSchema(BaseModel):
    """Schema for a pipeline node definition."""

    id: str = Field(..., description="Unique node identifier (client-generated or UUID)")
    node_type: str = Field(
        ...,
        description="Node type: source, transformation, or destination",
    )
    node_subtype: str = Field(
        ...,
        description="Node subtype (e.g., postgresql_source, filter_rows, clickhouse_destination)",
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Node configuration (connector_id, table_name, columns, etc.)",
    )
    position_x: float = Field(default=0.0, description="X position on canvas")
    position_y: float = Field(default=0.0, description="Y position on canvas")

    @field_validator("node_type")
    @classmethod
    def validate_node_type(cls, v: str) -> str:
        """Normalize and validate node type."""
        v = v.lower().strip()
        valid_types = {"source", "transformation", "destination"}
        if v not in valid_types:
            raise ValueError(f"Invalid node_type '{v}'. Must be one of: {', '.join(sorted(valid_types))}")
        return v


class EdgeSchema(BaseModel):
    """Schema for a pipeline edge connecting two nodes."""

    source_node_id: str = Field(..., description="ID of the source node")
    target_node_id: str = Field(..., description="ID of the target node")


class PipelineCreate(BaseModel):
    """Schema for creating a new pipeline."""

    name: str = Field(..., min_length=1, max_length=255, description="Pipeline name")
    description: str | None = Field(None, max_length=5000, description="Pipeline description")
    nodes: list[NodeSchema] = Field(default_factory=list, description="Pipeline nodes")
    edges: list[EdgeSchema] = Field(default_factory=list, description="Pipeline edges")


class PipelineUpdate(BaseModel):
    """Schema for updating a pipeline (creates a new version)."""

    name: str | None = Field(None, min_length=1, max_length=255, description="Pipeline name")
    description: str | None = Field(None, max_length=5000, description="Pipeline description")
    nodes: list[NodeSchema] = Field(..., description="Updated pipeline nodes")
    edges: list[EdgeSchema] = Field(..., description="Updated pipeline edges")


class NodeResponse(BaseModel):
    """Schema for a node in pipeline responses."""

    id: uuid.UUID
    node_type: str
    node_subtype: str
    config: dict[str, Any] | None = None
    position_x: float
    position_y: float

    model_config = {"from_attributes": True}


class EdgeResponse(BaseModel):
    """Schema for an edge in pipeline responses."""

    id: uuid.UUID
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID

    model_config = {"from_attributes": True}


class PipelineResponse(BaseModel):
    """Schema for pipeline API responses."""

    id: uuid.UUID
    name: str
    description: str | None = None
    status: str
    current_version: int
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    nodes: list[NodeResponse] = Field(default_factory=list)
    edges: list[EdgeResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class PipelineVersionResponse(BaseModel):
    """Schema for pipeline version history entries."""

    id: uuid.UUID
    pipeline_id: uuid.UUID
    version_number: int
    definition_snapshot: dict[str, Any]
    created_by: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class PipelineListResponse(BaseModel):
    """Paginated pipeline list response."""

    pipelines: list[PipelineResponse]
    total: int
    page: int
    page_size: int


class PipelineValidationError(BaseModel):
    """A single DAG validation error."""

    node_id: str | None = None
    error_type: str
    message: str


class PipelineValidationResponse(BaseModel):
    """Response from pipeline DAG validation."""

    is_valid: bool
    errors: list[PipelineValidationError] = Field(default_factory=list)
