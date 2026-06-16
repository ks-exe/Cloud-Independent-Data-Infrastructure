"""Data lineage API routes.

Provides access to data lineage information:
- POST /api/v1/lineage/events - record lineage event (lineage.write)
- GET /api/v1/lineage/graph/{table_name} - lineage graph (lineage.read)
- GET /api/v1/lineage/query - time-range query (lineage.read)
- GET /api/v1/lineage/node/{node_id} - node metadata (lineage.read)

Permission matrix:
- Admin: full access
- Auditor: full read access
- Data_Engineer: write access (recording events during execution)
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.security import TokenClaims, require_permissions
from backend.app.schemas.lineage import (
    LineageEventCreate,
    LineageEventResponse,
    LineageGraph,
    LineageNodeMetadata,
)
from backend.app.services.lineage_service import LineageService, get_lineage_service

router = APIRouter(prefix="/lineage", tags=["Lineage"])


@router.post("/events", response_model=LineageEventResponse, operation_id="lineage_record_event")
async def record_lineage_event(
    event: LineageEventCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenClaims = Depends(require_permissions("lineage.write")),
):
    """Record a lineage event for a data movement step."""
    service = get_lineage_service(db)
    lineage_event = await service.record_lineage_event(event)
    return LineageEventResponse(
        id=lineage_event.id,
        pipeline_id=lineage_event.pipeline_id,
        execution_id=lineage_event.execution_id,
        source_system=lineage_event.source_system,
        source_table=lineage_event.source_table,
        destination_system=lineage_event.destination_system,
        destination_table=lineage_event.destination_table,
        transformation_node=lineage_event.transformation_node,
        triggered_by=lineage_event.triggered_by,
        timestamp=lineage_event.timestamp,
    )


@router.get("/graph/{table_name}", response_model=LineageGraph, operation_id="lineage_get_graph")
async def get_lineage_graph(
    table_name: str,
    depth: int = Query(default=10, ge=1, le=10, description="Traversal depth (1-10)"),
    db: AsyncSession = Depends(get_db),
    current_user: TokenClaims = Depends(require_permissions("lineage.read")),
):
    """Get lineage graph for a table with configurable depth.

    Returns upstream and downstream lineage traversed up to the specified
    depth (max 10 levels). Returns an empty graph with a message if no
    lineage data exists for the specified table.
    """
    service = get_lineage_service(db)
    return await service.get_lineage_graph(table_name, depth=depth)


@router.get("/query", response_model=list[LineageEventResponse], operation_id="lineage_query_by_time_range")
async def query_lineage_by_time_range(
    start: datetime = Query(..., description="Start of time range (inclusive, ISO 8601)"),
    end: datetime = Query(..., description="End of time range (inclusive, ISO 8601)"),
    db: AsyncSession = Depends(get_db),
    current_user: TokenClaims = Depends(require_permissions("lineage.read")),
):
    """Query lineage events within a time range (inclusive).

    Returns all lineage events with timestamps within [start, end].
    """
    service = get_lineage_service(db)
    return await service.query_by_time_range(start=start, end=end)


@router.get("/node/{node_id}", response_model=LineageNodeMetadata, operation_id="lineage_get_node_metadata")
async def get_node_metadata(
    node_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenClaims = Depends(require_permissions("lineage.read")),
):
    """Get metadata for a lineage graph node.

    Returns the last execution timestamp, row count, and triggering user
    for the most recent execution involving the specified node.
    """
    service = get_lineage_service(db)
    return await service.get_node_metadata(node_id)
