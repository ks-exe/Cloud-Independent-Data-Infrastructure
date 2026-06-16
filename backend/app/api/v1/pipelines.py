"""Pipeline management API routes.

Provides operations for pipeline lifecycle management:
- GET /api/v1/pipelines - list pipelines (pipelines.read)
- POST /api/v1/pipelines - create pipeline (pipelines.create)
- GET /api/v1/pipelines/{id} - get pipeline (pipelines.read)
- PUT /api/v1/pipelines/{id} - update pipeline (pipelines.update)
- DELETE /api/v1/pipelines/{id} - delete pipeline (pipelines.delete)
- POST /api/v1/pipelines/{id}/validate - validate DAG (pipelines.read)
- POST /api/v1/pipelines/{id}/execute - execute pipeline (pipelines.execute)
- GET /api/v1/pipelines/{id}/versions - list versions (pipelines.read)
- DELETE /api/v1/pipelines/{id}/nodes/{node_id} - delete node (pipelines.update)
- POST /api/v1/pipelines/runs/{run_id}/retry - retry execution (pipelines.retry)

Permission matrix:
- Admin: full access
- Data_Engineer: full access (create, read, update, delete, execute, retry)
- Operator: read + retry only
- Auditor: read only
- Viewer: read only

Requirements: 5.1, 5.2, 5.5, 5.6, 5.8, 5.9, 5.10, 5.12
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.security import TokenClaims, require_permissions
from backend.app.schemas.execution import (
    ExecutionStatus,
    PipelineRunResponse,
)
from backend.app.schemas.pipeline import (
    EdgeSchema,
    NodeSchema,
    PipelineCreate,
    PipelineListResponse,
    PipelineResponse,
    PipelineUpdate,
    PipelineValidationResponse,
    PipelineVersionResponse,
)
from backend.app.services.execution_service import (
    CompilationError,
    ConnectorUnhealthyError,
    ExecutionServiceError,
    PipelineRunNotFoundError,
    RetryLimitExceededError,
    get_execution_service,
)
from backend.app.services.pipeline_service import (
    PipelineDeletionBlockedError,
    PipelineNotFoundError,
    PipelineServiceError,
    PipelineValidationFailedError,
    get_pipeline_service,
)

router = APIRouter(prefix="/pipelines", tags=["Pipelines"])


@router.get("/", response_model=PipelineListResponse, operation_id="pipelines_list")
async def list_pipelines(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    status_filter: str | None = Query(default=None, alias="status", description="Filter by status"),
    name: str | None = Query(default=None, description="Filter by name (partial match)"),
    current_user: TokenClaims = Depends(require_permissions("pipelines.read")),
    db: AsyncSession = Depends(get_db),
):
    """List all pipelines with pagination and optional filters."""
    service = get_pipeline_service(db)
    return await service.list_pipelines(
        page=page,
        page_size=page_size,
        status=status_filter,
        name=name,
    )


@router.post("/", response_model=PipelineResponse, status_code=status.HTTP_201_CREATED, operation_id="pipelines_create")
async def create_pipeline(
    body: PipelineCreate,
    current_user: TokenClaims = Depends(require_permissions("pipelines.create")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new pipeline with DAG validation."""
    service = get_pipeline_service(db)
    try:
        return await service.create_pipeline(body, current_user.user_id)
    except PipelineValidationFailedError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Pipeline validation failed",
                "errors": [err.model_dump() for err in e.errors],
            },
        )


@router.get("/{pipeline_id}", response_model=PipelineResponse, operation_id="pipelines_get")
async def get_pipeline(
    pipeline_id: uuid.UUID,
    current_user: TokenClaims = Depends(require_permissions("pipelines.read")),
    db: AsyncSession = Depends(get_db),
):
    """Get pipeline details by ID with current version nodes and edges."""
    service = get_pipeline_service(db)
    try:
        return await service.get_pipeline(pipeline_id)
    except PipelineNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline {pipeline_id} not found",
        )


@router.put("/{pipeline_id}", response_model=PipelineResponse, operation_id="pipelines_update")
async def update_pipeline(
    pipeline_id: uuid.UUID,
    body: PipelineUpdate,
    current_user: TokenClaims = Depends(require_permissions("pipelines.update")),
    db: AsyncSession = Depends(get_db),
):
    """Update pipeline definition (creates new version)."""
    service = get_pipeline_service(db)
    try:
        return await service.update_pipeline(pipeline_id, body, current_user.user_id)
    except PipelineNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline {pipeline_id} not found",
        )
    except PipelineValidationFailedError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Pipeline validation failed",
                "errors": [err.model_dump() for err in e.errors],
            },
        )


@router.delete("/{pipeline_id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="pipelines_delete")
async def delete_pipeline(
    pipeline_id: uuid.UUID,
    current_user: TokenClaims = Depends(require_permissions("pipelines.delete")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a pipeline (blocked if active schedules exist)."""
    service = get_pipeline_service(db)
    try:
        await service.delete_pipeline(pipeline_id)
    except PipelineNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline {pipeline_id} not found",
        )
    except PipelineDeletionBlockedError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=e.message,
        )


@router.post("/{pipeline_id}/validate", response_model=PipelineValidationResponse, operation_id="pipelines_validate")
async def validate_pipeline(
    pipeline_id: uuid.UUID,
    current_user: TokenClaims = Depends(require_permissions("pipelines.read")),
    db: AsyncSession = Depends(get_db),
):
    """Validate pipeline DAG topology and completeness for the current version."""
    service = get_pipeline_service(db)
    try:
        pipeline = await service.get_pipeline(pipeline_id)
    except PipelineNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline {pipeline_id} not found",
        )

    # Convert response nodes/edges back to schemas for validation
    nodes = [
        NodeSchema(
            id=str(n.id),
            node_type=n.node_type,
            node_subtype=n.node_subtype,
            config=n.config or {},
            position_x=n.position_x,
            position_y=n.position_y,
        )
        for n in pipeline.nodes
    ]
    edges = [
        EdgeSchema(
            source_node_id=str(e.source_node_id),
            target_node_id=str(e.target_node_id),
        )
        for e in pipeline.edges
    ]

    return service.validate_dag(nodes, edges)


@router.post("/{pipeline_id}/execute", response_model=PipelineRunResponse, operation_id="pipelines_execute")
async def execute_pipeline(
    pipeline_id: uuid.UUID,
    current_user: TokenClaims = Depends(require_permissions("pipelines.execute")),
    db: AsyncSession = Depends(get_db),
):
    """Execute a pipeline (triggers Dagster execution).

    Validates connector health, compiles the DAG, and submits to Dagster.
    """
    execution_service = get_execution_service(db)
    try:
        return await execution_service.execute_pipeline(pipeline_id, current_user.user_id)
    except ConnectorUnhealthyError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": e.message,
                "code": e.code,
                "unhealthy_connectors": e.unhealthy_connectors,
            },
        )
    except CompilationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": e.message,
                "code": e.code,
            },
        )
    except ExecutionServiceError as e:
        if e.code == "PIPELINE_NOT_FOUND":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=e.message,
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Pipeline execution failed", "code": e.code},
        )


@router.get("/runs/{run_id}/status", response_model=ExecutionStatus, operation_id="pipelines_get_execution_status")
async def get_execution_status(
    run_id: uuid.UUID,
    current_user: TokenClaims = Depends(require_permissions("pipelines.read")),
    db: AsyncSession = Depends(get_db),
):
    """Poll execution status for a pipeline run."""
    execution_service = get_execution_service(db)
    try:
        return await execution_service.poll_execution_status(run_id)
    except PipelineRunNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline run {run_id} not found",
        )


@router.get("/{pipeline_id}/versions", response_model=list[PipelineVersionResponse], operation_id="pipelines_list_versions")
async def list_versions(
    pipeline_id: uuid.UUID,
    current_user: TokenClaims = Depends(require_permissions("pipelines.read")),
    db: AsyncSession = Depends(get_db),
):
    """List pipeline version history."""
    service = get_pipeline_service(db)
    try:
        return await service.get_versions(pipeline_id)
    except PipelineNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline {pipeline_id} not found",
        )


@router.delete("/{pipeline_id}/nodes/{node_id}", response_model=PipelineResponse, operation_id="pipelines_delete_node")
async def delete_node(
    pipeline_id: uuid.UUID,
    node_id: uuid.UUID,
    current_user: TokenClaims = Depends(require_permissions("pipelines.update")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a node and its connected edges from the pipeline (creates new version)."""
    service = get_pipeline_service(db)
    try:
        return await service.delete_node(pipeline_id, node_id, current_user.user_id)
    except PipelineNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline {pipeline_id} not found",
        )
    except PipelineServiceError as e:
        if e.code == "NODE_NOT_FOUND":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=e.message,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.message,
        )


@router.post("/runs/{run_id}/retry", response_model=PipelineRunResponse, operation_id="pipelines_retry_execution")
async def retry_execution(
    run_id: uuid.UUID,
    current_user: TokenClaims = Depends(require_permissions("pipelines.retry")),
    db: AsyncSession = Depends(get_db),
):
    """Retry a failed pipeline execution (max 3 retries)."""
    execution_service = get_execution_service(db)
    try:
        return await execution_service.retry_execution(run_id, current_user.user_id)
    except PipelineRunNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline run {run_id} not found",
        )
    except RetryLimitExceededError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": e.message,
                "code": e.code,
            },
        )
    except ExecutionServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": e.message,
                "code": e.code,
            },
        )
