"""Connector management API routes.

Provides CRUD operations for data connectors:
- GET /api/v1/connectors - list connectors (connectors.read)
- POST /api/v1/connectors - create connector (connectors.create)
- GET /api/v1/connectors/{id} - get connector details (connectors.read)
- PUT /api/v1/connectors/{id} - update connector (connectors.update)
- DELETE /api/v1/connectors/{id} - delete connector (connectors.delete)
- POST /api/v1/connectors/{id}/test - test connection (connectors.test)
- GET /api/v1/connectors/{id}/health - health check (connectors.read)

Permission matrix:
- Admin: full access
- Data_Engineer: full access (create, read, update, delete, test)
- Viewer: read-only (list, get, health)
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.security import TokenClaims, require_permissions
from backend.app.schemas.connector import (
    ConnectionTestResult,
    ConnectorCreate,
    ConnectorDeletionError,
    ConnectorListResponse,
    ConnectorResponse,
    ConnectorUpdate,
    HealthStatus,
)
from backend.app.services.connector_service import (
    ConnectorDeletionBlockedError,
    ConnectorDisabledInAirGapError,
    ConnectorNotFoundError,
    ConnectorServiceError,
    ConnectorTypeError,
    get_connector_service,
)

router = APIRouter(prefix="/connectors", tags=["Connectors"])


@router.get("/", response_model=ConnectorListResponse, operation_id="connectors_list")
async def list_connectors(
    direction: str | None = Query(None, description="Filter by direction (source/destination)"),
    connector_type: str | None = Query(None, alias="type", description="Filter by connector type"),
    connector_status: str | None = Query(None, alias="status", description="Filter by status"),
    current_user: TokenClaims = Depends(require_permissions("connectors.read")),
    db: AsyncSession = Depends(get_db),
):
    """List all connectors with optional filters.

    Returns connectors with masked credentials (never exposes plaintext).
    """
    service = get_connector_service(db)
    return await service.list_connectors(
        direction=direction,
        connector_type=connector_type,
        status=connector_status,
    )


@router.post("/", response_model=ConnectorResponse, status_code=status.HTTP_201_CREATED, operation_id="connectors_create")
async def create_connector(
    connector_data: ConnectorCreate,
    current_user: TokenClaims = Depends(require_permissions("connectors.create")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new data connector.

    Encrypts credentials using AES-256-GCM with a per-connector IV.
    Supported source types: postgresql, mysql, csv, excel, rest_api.
    Supported destination types: postgresql, clickhouse.
    """
    service = get_connector_service(db)
    try:
        return await service.create_connector(connector_data, current_user.user_id)
    except ConnectorDisabledInAirGapError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=e.message,
        )
    except ConnectorTypeError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=e.message,
        )
    except ConnectorServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.message,
        )


@router.get("/{connector_id}", response_model=ConnectorResponse, operation_id="connectors_get")
async def get_connector(
    connector_id: uuid.UUID,
    current_user: TokenClaims = Depends(require_permissions("connectors.read")),
    db: AsyncSession = Depends(get_db),
):
    """Get connector details by ID.

    Credentials are always masked in the response.
    """
    service = get_connector_service(db)
    try:
        return await service.get_connector(connector_id)
    except ConnectorNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connector {connector_id} not found",
        )


@router.put("/{connector_id}", response_model=ConnectorResponse, operation_id="connectors_update")
async def update_connector(
    connector_id: uuid.UUID,
    update_data: ConnectorUpdate,
    current_user: TokenClaims = Depends(require_permissions("connectors.update")),
    db: AsyncSession = Depends(get_db),
):
    """Update connector configuration.

    Re-encrypts credentials if they are changed.
    """
    service = get_connector_service(db)
    try:
        return await service.update_connector(connector_id, update_data)
    except ConnectorNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connector {connector_id} not found",
        )
    except ConnectorServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.message,
        )


@router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="connectors_delete")
async def delete_connector(
    connector_id: uuid.UUID,
    current_user: TokenClaims = Depends(require_permissions("connectors.delete")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a connector (blocked if referenced by active pipelines).

    Returns HTTP 409 Conflict with the list of dependent pipelines if deletion is blocked.
    """
    service = get_connector_service(db)
    try:
        await service.delete_connector(connector_id)
    except ConnectorNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connector {connector_id} not found",
        )
    except ConnectorDeletionBlockedError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": e.message,
                "dependent_pipelines": [
                    {
                        "pipeline_id": str(p.pipeline_id),
                        "pipeline_name": p.pipeline_name,
                        "status": p.status,
                    }
                    for p in e.dependent_pipelines
                ],
            },
        )


@router.post("/{connector_id}/test", response_model=ConnectionTestResult, operation_id="connectors_test")
async def test_connection(
    connector_id: uuid.UUID,
    current_user: TokenClaims = Depends(require_permissions("connectors.test")),
    db: AsyncSession = Depends(get_db),
):
    """Test connector connectivity.

    Attempts to establish a connection to the target system with a 30-second timeout.
    Returns success/failure with latency information.
    """
    service = get_connector_service(db)
    try:
        return await service.test_connection(connector_id)
    except ConnectorNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connector {connector_id} not found",
        )
    except ConnectorServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.message,
        )


@router.get("/{connector_id}/health", response_model=HealthStatus, operation_id="connectors_health_check")
async def health_check(
    connector_id: uuid.UUID,
    current_user: TokenClaims = Depends(require_permissions("connectors.read")),
    db: AsyncSession = Depends(get_db),
):
    """Get connector health status with circuit breaker protection.

    Circuit breaker pattern:
    - CLOSED: Normal operation, health checks proceed
    - OPEN: After 3 consecutive failures, checks are skipped for 60 seconds
    - HALF_OPEN: After recovery timeout, one check is allowed to test recovery
    """
    service = get_connector_service(db)
    try:
        return await service.health_check(connector_id)
    except ConnectorNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connector {connector_id} not found",
        )
    except ConnectorServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.message,
        )
