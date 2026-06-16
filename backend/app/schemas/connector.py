"""Pydantic schemas for connector API request/response models."""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from backend.app.core.validators import MAX_DESCRIPTION_LENGTH, MAX_TEXT_LENGTH


class SourceType(str, Enum):
    """Supported source connector types."""

    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    CSV = "csv"
    EXCEL = "excel"
    REST_API = "rest_api"


class DestinationType(str, Enum):
    """Supported destination connector types."""

    POSTGRESQL = "postgresql"
    CLICKHOUSE = "clickhouse"


class ConnectorDirection(str, Enum):
    """Connector direction (source or destination)."""

    SOURCE = "source"
    DESTINATION = "destination"


# Fixed mask value for credential fields in API responses
CREDENTIAL_MASK = "********"


class ConnectorCreate(BaseModel):
    """Schema for creating a new connector."""

    name: str = Field(..., min_length=1, max_length=255, description="Connector display name")
    type: str = Field(..., description="Connector type (e.g., postgresql, mysql, csv)")
    direction: ConnectorDirection = Field(..., description="Source or destination")
    host: str | None = Field(None, max_length=255, description="Host address")
    port: int | None = Field(None, ge=1, le=65535, description="Port number")
    database_name: str | None = Field(None, max_length=255, description="Database name")
    credentials: dict[str, Any] = Field(
        default_factory=dict,
        description="Credential key-value pairs (username, password, api_key, etc.)",
    )
    extra_params: dict[str, Any] | None = Field(
        None, description="Additional connection parameters"
    )

    @field_validator("type")
    @classmethod
    def validate_connector_type(cls, v: str, info) -> str:
        """Validate that the type matches the direction."""
        # We validate type against direction in the service layer
        # since we need access to the direction field
        return v.lower()

    @field_validator("direction", mode="before")
    @classmethod
    def normalize_direction(cls, v: str) -> str:
        """Normalize direction to lowercase."""
        if isinstance(v, str):
            return v.lower()
        return v


class ConnectorUpdate(BaseModel):
    """Schema for updating an existing connector."""

    name: str | None = Field(None, min_length=1, max_length=255)
    host: str | None = Field(None, max_length=255)
    port: int | None = Field(None, ge=1, le=65535)
    database_name: str | None = Field(None, max_length=255)
    credentials: dict[str, Any] | None = Field(
        None, description="New credentials (replaces existing if provided)"
    )
    extra_params: dict[str, Any] | None = Field(None)


class ConnectorResponse(BaseModel):
    """Schema for connector API responses — credentials are always masked."""

    id: uuid.UUID
    name: str
    type: str
    direction: str
    status: str
    host: str | None = None
    port: int | None = None
    database_name: str | None = None
    credentials: dict[str, str] = Field(
        default_factory=dict,
        description="Masked credentials — always shows '********'",
    )
    extra_params: dict[str, Any] | None = None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConnectorListResponse(BaseModel):
    """Paginated connector list response."""

    connectors: list[ConnectorResponse]
    total: int


class ConnectionTestResult(BaseModel):
    """Result of a connector connection test."""

    success: bool
    message: str
    latency_ms: float | None = None
    tested_at: datetime


class HealthStatus(BaseModel):
    """Connector health status with circuit breaker info."""

    connector_id: uuid.UUID
    status: str  # "healthy", "unhealthy", "degraded"
    circuit_breaker_state: str  # "closed", "open", "half_open"
    failure_count: int = 0
    last_check_time: datetime | None = None
    message: str | None = None


class DependentPipelineInfo(BaseModel):
    """Information about a pipeline that depends on a connector."""

    pipeline_id: uuid.UUID
    pipeline_name: str
    status: str


class ConnectorDeletionError(BaseModel):
    """Error response when connector deletion is blocked by dependent pipelines."""

    detail: str
    dependent_pipelines: list[DependentPipelineInfo]
