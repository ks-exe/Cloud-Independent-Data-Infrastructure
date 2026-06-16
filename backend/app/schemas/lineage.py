"""Pydantic schemas for lineage service operations."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class LineageEventCreate(BaseModel):
    """Schema for creating a new lineage event."""

    pipeline_id: UUID = Field(..., description="ID of the pipeline that produced this event")
    execution_id: UUID = Field(..., description="ID of the pipeline execution run")
    source_system: str = Field(..., min_length=1, max_length=255, description="Source system name")
    source_table: str = Field(..., min_length=1, max_length=255, description="Source table name")
    destination_system: str = Field(
        ..., min_length=1, max_length=255, description="Destination system name"
    )
    destination_table: str = Field(
        ..., min_length=1, max_length=255, description="Destination table name"
    )
    transformation_node: str | None = Field(
        None, max_length=255, description="Transformation node name (if applicable)"
    )
    triggered_by: UUID = Field(..., description="User who triggered the execution")
    timestamp: datetime = Field(..., description="Timestamp of the lineage event (UTC)")


class LineageEventResponse(BaseModel):
    """Schema for a lineage event in API responses."""

    id: UUID
    pipeline_id: UUID
    execution_id: UUID
    source_system: str
    source_table: str
    destination_system: str
    destination_table: str
    transformation_node: str | None
    triggered_by: UUID
    timestamp: datetime

    model_config = {"from_attributes": True}


class LineageGraphNode(BaseModel):
    """A node in the lineage graph (table, system, or transformation step)."""

    id: str = Field(..., description="Unique identifier for the node (e.g., system.table)")
    name: str = Field(..., description="Display name of the node")
    type: str = Field(
        ..., description="Type of node: 'table', 'system', or 'transformation'"
    )
    system: str | None = Field(None, description="System this node belongs to")
    table_name: str | None = Field(None, description="Table name for table nodes")
    metadata: dict | None = Field(None, description="Additional node metadata")


class LineageGraphEdge(BaseModel):
    """An edge in the lineage graph representing data flow."""

    source_id: str = Field(..., description="Source node ID")
    target_id: str = Field(..., description="Target node ID")
    pipeline_name: str | None = Field(None, description="Pipeline that created this flow")
    last_execution: datetime | None = Field(None, description="When this flow was last executed")


class LineageGraph(BaseModel):
    """Complete lineage graph with nodes and edges."""

    nodes: list[LineageGraphNode] = Field(default_factory=list, description="Graph nodes")
    edges: list[LineageGraphEdge] = Field(default_factory=list, description="Graph edges")
    table_name: str = Field(..., description="The table this graph was queried for")
    depth: int = Field(..., description="Maximum depth used for traversal")
    message: str | None = Field(
        None, description="Informational message (e.g., no lineage data available)"
    )


class LineageNodeMetadata(BaseModel):
    """Metadata for a lineage node."""

    node_id: str = Field(..., description="The node identifier")
    last_execution: datetime | None = Field(
        None, description="Timestamp of the most recent execution involving this node"
    )
    row_count: int | None = Field(
        None, description="Row count from the most recent execution"
    )
    triggered_by_user: UUID | None = Field(
        None, description="User who triggered the most recent execution"
    )
    total_executions: int = Field(
        0, description="Total number of executions involving this node"
    )
    message: str | None = Field(
        None, description="Informational message if no metadata available"
    )


class LineageRetentionConfig(BaseModel):
    """Configuration for lineage retention."""

    retention_days: int = Field(
        365, ge=30, le=2555, description="Retention period in days (30-2555)"
    )

    @field_validator("retention_days")
    @classmethod
    def validate_retention_range(cls, v: int) -> int:
        """Ensure retention is within allowed bounds."""
        if v < 30:
            raise ValueError("Retention period must be at least 30 days")
        if v > 2555:
            raise ValueError("Retention period must not exceed 2555 days")
        return v
