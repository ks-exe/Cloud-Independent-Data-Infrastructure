"""Audit log API routes.

Provides endpoints for:
- GET /api/v1/audit — Search audit logs with filters and pagination (audit.read)
- GET /api/v1/audit/export — Export audit logs in CSV or JSON format (audit.export)
- GET /api/v1/audit/storage — Check audit log storage capacity (audit.read)

Permission matrix:
- Admin: full access
- Auditor: full access (read, export)
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.security import TokenClaims, require_permissions
from backend.app.schemas.audit import (
    AuditEventType,
    AuditFilter,
    AuditResult,
    ExportFormat,
    PaginatedAuditResponse,
    StorageStatus,
)
from backend.app.services.audit_service import AuditService, get_audit_service

router = APIRouter(prefix="/audit", tags=["Audit"])


def _get_service(db: AsyncSession = Depends(get_db)) -> AuditService:
    """Dependency to provide AuditService instance."""
    return get_audit_service(db)


@router.get("", response_model=PaginatedAuditResponse, operation_id="audit_search_logs")
async def search_audit_logs(
    event_type: AuditEventType | None = Query(None, description="Filter by event type"),
    actor_id: UUID | None = Query(None, description="Filter by actor user ID"),
    target_resource_id: str | None = Query(None, description="Filter by target resource ID"),
    result: AuditResult | None = Query(None, description="Filter by result (success/failure)"),
    start_time: datetime | None = Query(None, description="Start of time range (ISO 8601)"),
    end_time: datetime | None = Query(None, description="End of time range (ISO 8601)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(100, ge=1, le=100, description="Items per page (max 100)"),
    current_user: TokenClaims = Depends(require_permissions("audit.read")),
    service: AuditService = Depends(_get_service),
) -> PaginatedAuditResponse:
    """Search audit logs with filters and pagination.

    Supports filtering by event type, user (actor_id), resource, time range,
    and result status. Returns paginated results with a maximum of 100 entries
    per page.
    """
    filters = AuditFilter(
        event_type=event_type,
        actor_id=actor_id,
        target_resource_id=target_resource_id,
        start_time=start_time,
        end_time=end_time,
        result=result,
    )
    return await service.search_logs(filters=filters, page=page, page_size=page_size)


@router.get("/export", operation_id="audit_export_logs")
async def export_audit_logs(
    event_type: AuditEventType | None = Query(None, description="Filter by event type"),
    actor_id: UUID | None = Query(None, description="Filter by actor user ID"),
    target_resource_id: str | None = Query(None, description="Filter by target resource ID"),
    result: AuditResult | None = Query(None, description="Filter by result (success/failure)"),
    start_time: datetime | None = Query(None, description="Start of time range (ISO 8601)"),
    end_time: datetime | None = Query(None, description="End of time range (ISO 8601)"),
    format: ExportFormat = Query(ExportFormat.JSON, description="Export format: csv or json"),
    current_user: TokenClaims = Depends(require_permissions("audit.export")),
    service: AuditService = Depends(_get_service),
) -> Response:
    """Export audit logs in CSV or JSON format.

    Exports up to 100,000 records matching the specified filters.
    Returns the file as a downloadable attachment.
    """
    filters = AuditFilter(
        event_type=event_type,
        actor_id=actor_id,
        target_resource_id=target_resource_id,
        start_time=start_time,
        end_time=end_time,
        result=result,
    )
    data = await service.export_logs(filters=filters, format=format)

    if format == ExportFormat.CSV:
        media_type = "text/csv"
        filename = "audit_logs_export.csv"
    else:
        media_type = "application/json"
        filename = "audit_logs_export.json"

    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/storage", response_model=StorageStatus, operation_id="audit_check_storage")
async def check_storage_capacity(
    current_user: TokenClaims = Depends(require_permissions("audit.read")),
    service: AuditService = Depends(_get_service),
) -> StorageStatus:
    """Check audit log storage capacity.

    Returns current storage metrics and whether the 90% capacity
    warning threshold has been exceeded.
    """
    return await service.check_storage_capacity()
