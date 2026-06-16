"""Audit Service — immutable audit log recording, querying, export, and storage monitoring.

This service provides append-only audit logging for compliance requirements.
The underlying PostgreSQL table has triggers preventing UPDATE and DELETE operations,
ensuring immutability at the database level.
"""

import csv
import io
import json
import math
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.models.audit import AuditLog
from backend.app.schemas.audit import (
    AuditEventCreate,
    AuditFilter,
    AuditLogResponse,
    ExportFormat,
    PaginatedAuditResponse,
    StorageStatus,
)


class AuditService:
    """Service for managing immutable audit logs.

    Provides:
    - record_event: Append a new audit log entry
    - search_logs: Search with filters and pagination (100/page)
    - export_logs: Export filtered results in CSV or JSON (max 100,000 records)
    - check_storage_capacity: Monitor storage and emit warnings at 90% threshold
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def record_event(self, event: AuditEventCreate) -> AuditLog:
        """Record a new audit log entry.

        Creates an immutable record of a user or system action. The timestamp
        is set to the current UTC time in ISO 8601 format.

        Args:
            event: The audit event data to record.

        Returns:
            The persisted AuditLog entry.
        """
        audit_log = AuditLog(
            event_type=event.event_type.value,
            actor_id=event.actor_id,
            target_resource_id=event.target_resource_id,
            target_resource_type=event.target_resource_type,
            result=event.result.value,
            ip_address=event.ip_address,
            timestamp=datetime.now(timezone.utc),
        )
        self.db.add(audit_log)
        await self.db.flush()
        await self.db.refresh(audit_log)
        return audit_log

    async def search_logs(
        self,
        filters: AuditFilter,
        page: int = 1,
        page_size: int = 100,
    ) -> PaginatedAuditResponse:
        """Search audit logs with filters and pagination.

        Supports filtering by event_type, actor_id, target_resource_id,
        time_range (start_time/end_time), and result. Results are paginated
        with a maximum of 100 entries per page.

        Args:
            filters: Filter criteria for the search.
            page: Page number (1-indexed).
            page_size: Number of results per page (max 100).

        Returns:
            Paginated result with matching audit log entries.
        """
        # Enforce maximum page size of 100
        page_size = min(page_size, 100)
        page = max(page, 1)

        # Build the query with filters
        query = select(AuditLog)
        count_query = select(func.count(AuditLog.id))

        query = self._apply_filters(query, filters)
        count_query = self._apply_filters(count_query, filters)

        # Get total count
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # Calculate pagination
        pages = math.ceil(total / page_size) if total > 0 else 0
        offset = (page - 1) * page_size

        # Fetch paginated results ordered by timestamp descending
        query = query.order_by(AuditLog.timestamp.desc()).offset(offset).limit(page_size)
        result = await self.db.execute(query)
        logs = result.scalars().all()

        items = [
            AuditLogResponse(
                id=log.id,
                event_type=log.event_type,
                actor_id=log.actor_id,
                target_resource_id=log.target_resource_id,
                target_resource_type=log.target_resource_type,
                result=log.result,
                ip_address=log.ip_address,
                timestamp=log.timestamp,
            )
            for log in logs
        ]

        return PaginatedAuditResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )

    async def export_logs(
        self,
        filters: AuditFilter,
        format: ExportFormat = ExportFormat.JSON,
    ) -> bytes:
        """Export audit logs in CSV or JSON format.

        Exports up to 100,000 records matching the given filters.

        Args:
            filters: Filter criteria for the export.
            format: Export format (csv or json).

        Returns:
            The exported data as bytes.
        """
        max_export = settings.audit_log_max_export_records

        # Build query with filters, capped at max export limit
        query = select(AuditLog)
        query = self._apply_filters(query, filters)
        query = query.order_by(AuditLog.timestamp.desc()).limit(max_export)

        result = await self.db.execute(query)
        logs = result.scalars().all()

        if format == ExportFormat.CSV:
            return self._export_csv(logs)
        else:
            return self._export_json(logs)

    async def check_storage_capacity(self) -> StorageStatus:
        """Check audit log storage capacity and determine warning status.

        Estimates storage usage based on record count and average row size.
        Emits a warning when storage reaches 90% of the estimated capacity
        based on retention period and growth rate.

        Returns:
            StorageStatus with current usage metrics and warning flag.
        """
        # Get total record count
        count_result = await self.db.execute(
            select(func.count(AuditLog.id))
        )
        total_records = count_result.scalar() or 0

        # Estimate storage size (approximate 500 bytes per audit log row)
        avg_row_size_bytes = 500
        estimated_size_mb = (total_records * avg_row_size_bytes) / (1024 * 1024)

        # Estimate capacity based on retention period
        # Use PostgreSQL pg_total_relation_size if available, otherwise estimate
        try:
            size_result = await self.db.execute(
                text("SELECT pg_total_relation_size('audit_logs')")
            )
            actual_size_bytes = size_result.scalar() or 0
            estimated_size_mb = actual_size_bytes / (1024 * 1024)
        except Exception:
            # Fallback to estimate if pg_total_relation_size is not available
            pass

        # Calculate usage percentage relative to a configured capacity
        # We estimate max capacity as: (retention_days / days_of_data_so_far) * current_size
        # For simplicity, use a threshold based on table size relative to a configurable max
        # Default: warn if estimated size exceeds 90% of a practical limit
        # Practical estimate: 10GB max for audit logs before archival
        max_capacity_mb = 10 * 1024  # 10 GB
        current_usage_percent = estimated_size_mb / max_capacity_mb if max_capacity_mb > 0 else 0.0

        threshold = settings.audit_log_storage_warning_threshold
        warning = current_usage_percent >= threshold

        return StorageStatus(
            total_records=total_records,
            estimated_size_mb=round(estimated_size_mb, 2),
            capacity_threshold_percent=threshold,
            current_usage_percent=round(current_usage_percent, 4),
            warning=warning,
            retention_days=settings.audit_log_retention_days,
        )

    def _apply_filters(self, query, filters: AuditFilter):
        """Apply filter criteria to a SQLAlchemy query."""
        if filters.event_type is not None:
            query = query.where(AuditLog.event_type == filters.event_type.value)
        if filters.actor_id is not None:
            query = query.where(AuditLog.actor_id == filters.actor_id)
        if filters.target_resource_id is not None:
            query = query.where(
                AuditLog.target_resource_id == filters.target_resource_id
            )
        if filters.start_time is not None:
            query = query.where(AuditLog.timestamp >= filters.start_time)
        if filters.end_time is not None:
            query = query.where(AuditLog.timestamp <= filters.end_time)
        if filters.result is not None:
            query = query.where(AuditLog.result == filters.result.value)
        return query

    def _export_csv(self, logs: list[AuditLog]) -> bytes:
        """Export audit logs as CSV bytes."""
        output = io.StringIO()
        writer = csv.writer(output)

        # Header row
        writer.writerow([
            "id",
            "event_type",
            "actor_id",
            "target_resource_id",
            "target_resource_type",
            "result",
            "ip_address",
            "timestamp",
        ])

        # Data rows
        for log in logs:
            writer.writerow([
                str(log.id),
                log.event_type,
                str(log.actor_id),
                log.target_resource_id or "",
                log.target_resource_type or "",
                log.result,
                log.ip_address or "",
                log.timestamp.isoformat() if log.timestamp else "",
            ])

        return output.getvalue().encode("utf-8")

    def _export_json(self, logs: list[AuditLog]) -> bytes:
        """Export audit logs as JSON bytes."""
        records = [
            {
                "id": str(log.id),
                "event_type": log.event_type,
                "actor_id": str(log.actor_id),
                "target_resource_id": log.target_resource_id,
                "target_resource_type": log.target_resource_type,
                "result": log.result,
                "ip_address": log.ip_address,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            }
            for log in logs
        ]
        return json.dumps(records, indent=2).encode("utf-8")


def get_audit_service(db: AsyncSession) -> AuditService:
    """Factory function for dependency injection of AuditService."""
    return AuditService(db)
