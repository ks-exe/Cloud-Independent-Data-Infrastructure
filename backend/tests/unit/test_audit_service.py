"""Unit tests for the Audit Service."""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.schemas.audit import (
    AuditEventCreate,
    AuditEventType,
    AuditFilter,
    AuditLogResponse,
    AuditResult,
    ExportFormat,
    PaginatedAuditResponse,
    StorageStatus,
)
from backend.app.services.audit_service import AuditService


# ---------- Helpers ----------


def _make_mock_audit_log(
    event_type: str = "LOGIN",
    actor_id: uuid.UUID | None = None,
    result: str = "success",
    ip_address: str = "192.168.1.1",
    target_resource_id: str | None = None,
    target_resource_type: str | None = None,
):
    """Create a mock AuditLog object."""
    log = MagicMock()
    log.id = uuid.uuid4()
    log.event_type = event_type
    log.actor_id = actor_id or uuid.uuid4()
    log.target_resource_id = target_resource_id
    log.target_resource_type = target_resource_type
    log.result = result
    log.ip_address = ip_address
    log.timestamp = datetime.now(timezone.utc)
    return log


# ---------- Schema Tests ----------


class TestAuditSchemas:
    """Tests for Pydantic schema validation."""

    def test_audit_event_create_valid(self):
        event = AuditEventCreate(
            event_type=AuditEventType.LOGIN,
            actor_id=uuid.uuid4(),
            result=AuditResult.SUCCESS,
            ip_address="10.0.0.1",
        )
        assert event.event_type == AuditEventType.LOGIN
        assert event.result == AuditResult.SUCCESS

    def test_audit_event_create_all_fields(self):
        actor = uuid.uuid4()
        event = AuditEventCreate(
            event_type=AuditEventType.PIPELINE_CREATION,
            actor_id=actor,
            target_resource_id="pipeline-123",
            target_resource_type="pipeline",
            result=AuditResult.SUCCESS,
            ip_address="192.168.0.100",
        )
        assert event.target_resource_id == "pipeline-123"
        assert event.target_resource_type == "pipeline"

    def test_audit_event_create_invalid_ip_too_long(self):
        with pytest.raises(ValueError):
            AuditEventCreate(
                event_type=AuditEventType.LOGIN,
                actor_id=uuid.uuid4(),
                result=AuditResult.SUCCESS,
                ip_address="x" * 46,
            )

    def test_audit_filter_time_range_validation(self):
        """end_time must be after start_time."""
        with pytest.raises(ValueError):
            AuditFilter(
                start_time=datetime(2024, 6, 1, tzinfo=timezone.utc),
                end_time=datetime(2024, 5, 1, tzinfo=timezone.utc),
            )

    def test_audit_filter_valid_time_range(self):
        f = AuditFilter(
            start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 12, 31, tzinfo=timezone.utc),
        )
        assert f.start_time < f.end_time

    def test_all_event_types_defined(self):
        expected = {
            "LOGIN", "LOGOUT", "USER_CREATION", "USER_UPDATE", "USER_DELETION",
            "PIPELINE_CREATION", "PIPELINE_UPDATE", "PIPELINE_EXECUTION",
            "CONNECTOR_CREATION", "CONNECTOR_MODIFICATION",
            "PERMISSION_DENIED", "UNAUTHENTICATED_ACCESS",
        }
        actual = {e.value for e in AuditEventType}
        assert actual == expected

    def test_paginated_response_model(self):
        resp = PaginatedAuditResponse(
            items=[],
            total=0,
            page=1,
            page_size=100,
            pages=0,
        )
        assert resp.total == 0
        assert resp.pages == 0

    def test_storage_status_model(self):
        status = StorageStatus(
            total_records=50000,
            estimated_size_mb=25.0,
            capacity_threshold_percent=0.9,
            current_usage_percent=0.0024,
            warning=False,
            retention_days=730,
        )
        assert not status.warning
        assert status.retention_days == 730


# ---------- AuditService.record_event ----------


class TestAuditServiceRecordEvent:
    @pytest.mark.asyncio
    async def test_record_event_creates_entry(self):
        mock_db = AsyncMock()
        service = AuditService(mock_db)

        event = AuditEventCreate(
            event_type=AuditEventType.LOGIN,
            actor_id=uuid.uuid4(),
            result=AuditResult.SUCCESS,
            ip_address="10.0.0.1",
        )

        result = await service.record_event(event)

        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited_once()
        mock_db.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_record_event_sets_utc_timestamp(self):
        mock_db = AsyncMock()
        service = AuditService(mock_db)

        event = AuditEventCreate(
            event_type=AuditEventType.USER_CREATION,
            actor_id=uuid.uuid4(),
            target_resource_id="user-456",
            target_resource_type="user",
            result=AuditResult.SUCCESS,
            ip_address="172.16.0.1",
        )

        await service.record_event(event)

        # Verify the added object has the correct fields
        added_obj = mock_db.add.call_args[0][0]
        assert added_obj.event_type == "USER_CREATION"
        assert added_obj.result == "success"
        assert added_obj.timestamp.tzinfo is not None


# ---------- AuditService.search_logs ----------


class TestAuditServiceSearchLogs:
    @pytest.mark.asyncio
    async def test_search_logs_returns_paginated_result(self):
        mock_db = AsyncMock()
        service = AuditService(mock_db)

        mock_logs = [_make_mock_audit_log() for _ in range(3)]

        # Mock count query
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 3

        # Mock data query
        mock_data_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_logs
        mock_data_result.scalars.return_value = mock_scalars

        mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_data_result])

        filters = AuditFilter()
        result = await service.search_logs(filters, page=1, page_size=100)

        assert isinstance(result, PaginatedAuditResponse)
        assert result.total == 3
        assert result.page == 1
        assert result.page_size == 100
        assert result.pages == 1
        assert len(result.items) == 3

    @pytest.mark.asyncio
    async def test_search_logs_enforces_max_page_size(self):
        mock_db = AsyncMock()
        service = AuditService(mock_db)

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        mock_data_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_data_result.scalars.return_value = mock_scalars

        mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_data_result])

        filters = AuditFilter()
        result = await service.search_logs(filters, page=1, page_size=500)

        # Page size should be capped at 100
        assert result.page_size == 100

    @pytest.mark.asyncio
    async def test_search_logs_enforces_min_page(self):
        mock_db = AsyncMock()
        service = AuditService(mock_db)

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        mock_data_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_data_result.scalars.return_value = mock_scalars

        mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_data_result])

        filters = AuditFilter()
        result = await service.search_logs(filters, page=0, page_size=100)

        # Page should be at least 1
        assert result.page == 1


# ---------- AuditService.export_logs ----------


class TestAuditServiceExportLogs:
    @pytest.mark.asyncio
    async def test_export_json_format(self):
        mock_db = AsyncMock()
        service = AuditService(mock_db)

        mock_logs = [_make_mock_audit_log(event_type="LOGIN")]

        mock_data_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_logs
        mock_data_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_data_result)

        filters = AuditFilter()
        data = await service.export_logs(filters, format=ExportFormat.JSON)

        # Should be valid JSON
        parsed = json.loads(data)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["event_type"] == "LOGIN"

    @pytest.mark.asyncio
    async def test_export_csv_format(self):
        mock_db = AsyncMock()
        service = AuditService(mock_db)

        mock_logs = [_make_mock_audit_log(event_type="LOGOUT")]

        mock_data_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_logs
        mock_data_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_data_result)

        filters = AuditFilter()
        data = await service.export_logs(filters, format=ExportFormat.CSV)

        # Should be valid CSV with header
        lines = data.decode("utf-8").strip().split("\n")
        assert len(lines) == 2  # header + 1 data row
        assert "event_type" in lines[0]
        assert "LOGOUT" in lines[1]

    @pytest.mark.asyncio
    async def test_export_empty_result(self):
        mock_db = AsyncMock()
        service = AuditService(mock_db)

        mock_data_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_data_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_data_result)

        filters = AuditFilter()
        data = await service.export_logs(filters, format=ExportFormat.JSON)

        parsed = json.loads(data)
        assert parsed == []


# ---------- AuditService.check_storage_capacity ----------


class TestAuditServiceStorageCapacity:
    @pytest.mark.asyncio
    async def test_storage_below_threshold(self):
        mock_db = AsyncMock()
        service = AuditService(mock_db)

        # Mock count result
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 1000

        # Mock pg_total_relation_size result
        mock_size_result = MagicMock()
        mock_size_result.scalar.return_value = 500000  # ~0.48 MB

        mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_size_result])

        result = await service.check_storage_capacity()

        assert isinstance(result, StorageStatus)
        assert result.total_records == 1000
        assert not result.warning
        assert result.retention_days == 730

    @pytest.mark.asyncio
    async def test_storage_above_threshold_triggers_warning(self):
        mock_db = AsyncMock()
        service = AuditService(mock_db)

        # Mock count result
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 50_000_000

        # Mock pg_total_relation_size - 9.5 GB (above 90% of 10 GB)
        mock_size_result = MagicMock()
        mock_size_result.scalar.return_value = 9.5 * 1024 * 1024 * 1024

        mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_size_result])

        result = await service.check_storage_capacity()

        assert result.warning is True
        assert result.current_usage_percent >= 0.9
