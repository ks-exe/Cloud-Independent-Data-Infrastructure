"""Unit tests for the Notification Service.

Tests notification generation, role-based targeting, deduplication,
pagination, mark-as-read, and cleanup functionality.

Validates: Requirements 14.1, 14.2, 14.3, 14.4, 14.5, 14.6
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.models.notifications import Notification
from backend.app.schemas.notification import (
    NotificationCreate,
    NotificationEvent,
    NotificationEventType,
    NotificationListResponse,
    NotificationResponse,
)
from backend.app.services.notification_service import (
    DEDUP_WINDOW_SECONDS,
    PAGE_SIZE,
    RETENTION_DAYS,
    NotificationService,
)


# ---------- Helpers ----------


def _make_mock_notification(
    user_id: uuid.UUID | None = None,
    event_type: str = "pipeline_failure",
    source_resource_id: str | None = "pipeline-123",
    summary: str = "Test notification",
    is_read: bool = False,
    recurrence_count: int = 0,
    created_at: datetime | None = None,
):
    """Create a mock Notification object."""
    notif = MagicMock(spec=Notification)
    notif.id = uuid.uuid4()
    notif.user_id = user_id or uuid.uuid4()
    notif.event_type = event_type
    notif.source_resource_id = source_resource_id
    notif.summary = summary
    notif.is_read = is_read
    notif.recurrence_count = recurrence_count
    notif.created_at = created_at or datetime.now(timezone.utc)
    notif.expires_at = notif.created_at + timedelta(days=30)
    return notif


def _make_pipeline_failure_event(
    pipeline_owner_id: uuid.UUID | None = None,
) -> NotificationEvent:
    """Create a pipeline failure notification event."""
    return NotificationEvent(
        event_type=NotificationEventType.PIPELINE_FAILURE,
        source_resource_id="pipeline-abc",
        pipeline_name="ETL Daily Load",
        execution_id="exec-12345",
        failure_timestamp=datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc),
        failing_node="transform_join",
        pipeline_owner_id=pipeline_owner_id or uuid.uuid4(),
    )


def _make_connector_failure_event() -> NotificationEvent:
    """Create a connector health failure event."""
    return NotificationEvent(
        event_type=NotificationEventType.CONNECTOR_HEALTH_FAILURE,
        source_resource_id="connector-xyz",
        connector_name="Production PostgreSQL",
        connector_type="postgresql",
        failure_timestamp=datetime(2024, 6, 15, 11, 0, 0, tzinfo=timezone.utc),
    )


def _make_resource_threshold_event() -> NotificationEvent:
    """Create a resource threshold event."""
    return NotificationEvent(
        event_type=NotificationEventType.RESOURCE_THRESHOLD,
        source_resource_id="resource-storage",
        resource_name="Disk Storage",
        current_value="92%",
        threshold_value="90%",
    )


# ---------- Schema Tests ----------


class TestNotificationSchemas:
    """Tests for notification Pydantic schema validation."""

    def test_notification_create_valid(self):
        schema = NotificationCreate(
            user_id=uuid.uuid4(),
            event_type=NotificationEventType.PIPELINE_FAILURE,
            source_resource_id="pipeline-123",
            summary="Pipeline failed",
        )
        assert schema.event_type == NotificationEventType.PIPELINE_FAILURE
        assert schema.summary == "Pipeline failed"

    def test_notification_create_optional_fields(self):
        schema = NotificationCreate(
            user_id=uuid.uuid4(),
            event_type=NotificationEventType.CONNECTOR_HEALTH_FAILURE,
            summary="Connector down",
        )
        assert schema.source_resource_id is None
        assert schema.expires_at is None

    def test_notification_event_pipeline_failure(self):
        event = _make_pipeline_failure_event()
        assert event.event_type == NotificationEventType.PIPELINE_FAILURE
        assert event.pipeline_name == "ETL Daily Load"
        assert event.execution_id == "exec-12345"
        assert event.failing_node == "transform_join"

    def test_notification_event_connector_failure(self):
        event = _make_connector_failure_event()
        assert event.event_type == NotificationEventType.CONNECTOR_HEALTH_FAILURE
        assert event.connector_name == "Production PostgreSQL"
        assert event.connector_type == "postgresql"

    def test_notification_event_resource_threshold(self):
        event = _make_resource_threshold_event()
        assert event.event_type == NotificationEventType.RESOURCE_THRESHOLD
        assert event.resource_name == "Disk Storage"
        assert event.current_value == "92%"
        assert event.threshold_value == "90%"

    def test_notification_response_model(self):
        resp = NotificationResponse(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            event_type="pipeline_failure",
            source_resource_id="pipeline-123",
            summary="Pipeline failed",
            is_read=False,
            recurrence_count=0,
            created_at=datetime.now(timezone.utc),
        )
        assert resp.is_read is False
        assert resp.recurrence_count == 0

    def test_notification_list_response_pagination(self):
        resp = NotificationListResponse(
            items=[],
            total=0,
            page=1,
            page_size=30,
            pages=0,
        )
        assert resp.total == 0
        assert resp.page_size == 30
        assert resp.pages == 0

    def test_notification_event_types_defined(self):
        expected = {"pipeline_failure", "connector_health_failure", "resource_threshold"}
        actual = {e.value for e in NotificationEventType}
        assert actual == expected


# ---------- NotificationService.create_notification ----------


class TestNotificationServiceCreate:
    """Tests for notification creation with role-based targeting."""

    @pytest.mark.asyncio
    async def test_pipeline_failure_targets_owner_and_operators(self):
        """Requirement 14.1: Pipeline failure → owner + Operators."""
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        owner_id = uuid.uuid4()
        operator_ids = [uuid.uuid4(), uuid.uuid4()]

        event = _make_pipeline_failure_event(pipeline_owner_id=owner_id)

        # Mock suppress_duplicate to return False (no suppression)
        with patch.object(service, "suppress_duplicate", return_value=False):
            # Mock _get_users_by_role
            with patch.object(
                service, "_get_users_by_role", return_value=operator_ids
            ):
                # Mock _set_dedup_key
                with patch.object(service, "_set_dedup_key", return_value=None):
                    notifications = await service.create_notification(event)

        # Should create notifications for owner + 2 operators = 3
        assert mock_db.add.call_count == 3
        assert mock_db.flush.awaited

    @pytest.mark.asyncio
    async def test_connector_failure_targets_data_engineers_and_operators(self):
        """Requirement 14.2: Connector failure → Data_Engineers + Operators."""
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        de_ids = [uuid.uuid4()]
        op_ids = [uuid.uuid4(), uuid.uuid4()]

        event = _make_connector_failure_event()

        with patch.object(service, "suppress_duplicate", return_value=False):
            with patch.object(
                service, "_get_users_by_role", side_effect=[de_ids, op_ids]
            ):
                with patch.object(service, "_set_dedup_key", return_value=None):
                    notifications = await service.create_notification(event)

        # Should create notifications for 1 DE + 2 Ops = 3
        assert mock_db.add.call_count == 3

    @pytest.mark.asyncio
    async def test_resource_threshold_targets_admins(self):
        """Requirement 14.3: Resource threshold → Admins."""
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        admin_ids = [uuid.uuid4(), uuid.uuid4()]

        event = _make_resource_threshold_event()

        with patch.object(service, "suppress_duplicate", return_value=False):
            with patch.object(service, "_get_users_by_role", return_value=admin_ids):
                with patch.object(service, "_set_dedup_key", return_value=None):
                    notifications = await service.create_notification(event)

        # Should create notifications for 2 admins
        assert mock_db.add.call_count == 2

    @pytest.mark.asyncio
    async def test_pipeline_failure_summary_contains_required_fields(self):
        """Requirement 14.1: Notification contains pipeline name, execution ID, timestamp, failing node."""
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        owner_id = uuid.uuid4()
        event = _make_pipeline_failure_event(pipeline_owner_id=owner_id)

        with patch.object(service, "suppress_duplicate", return_value=False):
            with patch.object(service, "_get_users_by_role", return_value=[]):
                with patch.object(service, "_set_dedup_key", return_value=None):
                    await service.create_notification(event)

        # Verify the notification content
        added_obj = mock_db.add.call_args[0][0]
        assert "ETL Daily Load" in added_obj.summary
        assert "exec-12345" in added_obj.summary
        assert "transform_join" in added_obj.summary
        assert "2024-06-15" in added_obj.summary

    @pytest.mark.asyncio
    async def test_connector_failure_summary_contains_required_fields(self):
        """Requirement 14.2: Notification contains connector name, type, and timestamp."""
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        event = _make_connector_failure_event()

        with patch.object(service, "suppress_duplicate", return_value=False):
            with patch.object(service, "_get_users_by_role", return_value=[uuid.uuid4()]):
                with patch.object(service, "_set_dedup_key", return_value=None):
                    await service.create_notification(event)

        added_obj = mock_db.add.call_args[0][0]
        assert "Production PostgreSQL" in added_obj.summary
        assert "postgresql" in added_obj.summary

    @pytest.mark.asyncio
    async def test_resource_threshold_summary_contains_required_fields(self):
        """Requirement 14.3: Notification contains resource name, current value, threshold."""
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        event = _make_resource_threshold_event()

        with patch.object(service, "suppress_duplicate", return_value=False):
            with patch.object(service, "_get_users_by_role", return_value=[uuid.uuid4()]):
                with patch.object(service, "_set_dedup_key", return_value=None):
                    await service.create_notification(event)

        added_obj = mock_db.add.call_args[0][0]
        assert "Disk Storage" in added_obj.summary
        assert "92%" in added_obj.summary
        assert "90%" in added_obj.summary

    @pytest.mark.asyncio
    async def test_create_notification_suppressed_returns_empty(self):
        """Requirement 14.6: Suppressed duplicates don't create new notifications."""
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        event = _make_pipeline_failure_event()

        with patch.object(service, "suppress_duplicate", return_value=True):
            notifications = await service.create_notification(event)

        assert notifications == []
        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_notification_no_recipients_returns_empty(self):
        """When no recipients match, return empty list without error."""
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        event = _make_resource_threshold_event()

        with patch.object(service, "suppress_duplicate", return_value=False):
            with patch.object(service, "_get_users_by_role", return_value=[]):
                notifications = await service.create_notification(event)

        assert notifications == []
        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_notification_sets_expiration(self):
        """Requirement 14.5: Notifications should have an expiration for 30-day cleanup."""
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        event = _make_resource_threshold_event()

        with patch.object(service, "suppress_duplicate", return_value=False):
            with patch.object(service, "_get_users_by_role", return_value=[uuid.uuid4()]):
                with patch.object(service, "_set_dedup_key", return_value=None):
                    await service.create_notification(event)

        added_obj = mock_db.add.call_args[0][0]
        assert added_obj.expires_at is not None
        # Should be approximately 30 days from now
        expected_expiry = datetime.now(timezone.utc) + timedelta(days=RETENTION_DAYS)
        delta = abs((added_obj.expires_at - expected_expiry).total_seconds())
        assert delta < 5  # Within 5 seconds tolerance


# ---------- NotificationService.get_user_notifications ----------


class TestNotificationServiceGetUserNotifications:
    """Tests for paginated notification retrieval."""

    @pytest.mark.asyncio
    async def test_returns_paginated_response(self):
        """Requirement 14.4: Chronological list with pagination."""
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        user_id = uuid.uuid4()
        mock_notifications = [_make_mock_notification(user_id=user_id) for _ in range(3)]

        # Mock count query
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 3

        # Mock data query
        mock_data_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_notifications
        mock_data_result.scalars.return_value = mock_scalars

        mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_data_result])

        result = await service.get_user_notifications(user_id, page=1)

        assert isinstance(result, NotificationListResponse)
        assert result.total == 3
        assert result.page == 1
        assert result.page_size == 30
        assert len(result.items) == 3

    @pytest.mark.asyncio
    async def test_default_page_size_is_30(self):
        """Task spec: 30 per page default."""
        assert PAGE_SIZE == 30

        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        user_id = uuid.uuid4()

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        mock_data_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_data_result.scalars.return_value = mock_scalars

        mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_data_result])

        result = await service.get_user_notifications(user_id, page=1)
        assert result.page_size == 30

    @pytest.mark.asyncio
    async def test_page_clamp_minimum(self):
        """Page should be at least 1."""
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        user_id = uuid.uuid4()

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        mock_data_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_data_result.scalars.return_value = mock_scalars

        mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_data_result])

        result = await service.get_user_notifications(user_id, page=0)
        assert result.page == 1

    @pytest.mark.asyncio
    async def test_page_size_clamp_maximum(self):
        """Page size should be clamped to 100."""
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        user_id = uuid.uuid4()

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        mock_data_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_data_result.scalars.return_value = mock_scalars

        mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_data_result])

        result = await service.get_user_notifications(user_id, page=1, page_size=200)
        assert result.page_size == 100

    @pytest.mark.asyncio
    async def test_empty_notification_list(self):
        """Returns valid response for users with no notifications."""
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        user_id = uuid.uuid4()

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        mock_data_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_data_result.scalars.return_value = mock_scalars

        mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_data_result])

        result = await service.get_user_notifications(user_id, page=1)
        assert result.total == 0
        assert result.items == []
        assert result.pages == 0


# ---------- NotificationService.mark_as_read ----------


class TestNotificationServiceMarkAsRead:
    """Tests for marking notifications as read."""

    @pytest.mark.asyncio
    async def test_mark_as_read_success(self):
        """Requirement 14.4: Support marking individual notifications as read."""
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        notification_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Mock successful update (1 row affected)
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_db.execute = AsyncMock(return_value=mock_result)

        await service.mark_as_read(notification_id, user_id)

        mock_db.execute.assert_awaited_once()
        mock_db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mark_as_read_not_found_raises(self):
        """Raises ValueError when notification not found or belongs to another user."""
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        notification_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Mock no rows affected
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="Notification not found"):
            await service.mark_as_read(notification_id, user_id)


# ---------- NotificationService.suppress_duplicate ----------


class TestNotificationServiceSuppressDuplicate:
    """Tests for deduplication within 15-minute window."""

    @pytest.mark.asyncio
    async def test_suppresses_when_redis_key_exists(self):
        """Requirement 14.6: Same source within 15 min is suppressed."""
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="1")

        with patch(
            "backend.app.services.notification_service.get_redis_client",
            return_value=mock_redis,
        ):
            with patch.object(service, "_increment_recurrence", return_value=None):
                result = await service.suppress_duplicate("pipeline-abc", "pipeline_failure")

        assert result is True

    @pytest.mark.asyncio
    async def test_no_suppression_when_redis_key_missing(self):
        """No suppression when no prior notification in window."""
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch(
            "backend.app.services.notification_service.get_redis_client",
            return_value=mock_redis,
        ):
            result = await service.suppress_duplicate("pipeline-abc", "pipeline_failure")

        assert result is False

    @pytest.mark.asyncio
    async def test_fallback_to_db_when_redis_unavailable(self):
        """Falls back to DB check when Redis is unavailable."""
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        # Mock Redis raising an exception
        def raise_redis_error():
            raise ConnectionError("Redis unavailable")

        # Mock DB query returning no recent notification
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = None
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch(
            "backend.app.services.notification_service.get_redis_client",
            side_effect=ConnectionError("Redis unavailable"),
        ):
            result = await service.suppress_duplicate("pipeline-abc", "pipeline_failure")

        assert result is False

    @pytest.mark.asyncio
    async def test_fallback_db_finds_recent_notification(self):
        """Falls back to DB and finds recent unread notification → suppress."""
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        # Mock existing notification in DB
        existing_notif = MagicMock()
        existing_notif.recurrence_count = 2

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = existing_notif
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch(
            "backend.app.services.notification_service.get_redis_client",
            side_effect=ConnectionError("Redis unavailable"),
        ):
            result = await service.suppress_duplicate("pipeline-abc", "pipeline_failure")

        assert result is True
        assert existing_notif.recurrence_count == 3
        mock_db.flush.assert_awaited()

    def test_dedup_window_is_15_minutes(self):
        """Requirement 14.6: Suppression window is 15 minutes."""
        assert DEDUP_WINDOW_SECONDS == 15 * 60


# ---------- NotificationService.cleanup_expired ----------


class TestNotificationServiceCleanupExpired:
    """Tests for 30-day retention cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_deletes_old_notifications(self):
        """Requirement 14.5: Retain for 30 days before cleanup."""
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        mock_result = MagicMock()
        mock_result.rowcount = 42
        mock_db.execute = AsyncMock(return_value=mock_result)

        deleted = await service.cleanup_expired()

        assert deleted == 42
        mock_db.execute.assert_awaited_once()
        mock_db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cleanup_zero_when_none_expired(self):
        """Returns 0 when no notifications are past retention."""
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_db.execute = AsyncMock(return_value=mock_result)

        deleted = await service.cleanup_expired()

        assert deleted == 0

    def test_retention_is_30_days(self):
        """Requirement 14.5: 30-day retention period."""
        assert RETENTION_DAYS == 30


# ---------- NotificationService._build_summary ----------


class TestNotificationServiceBuildSummary:
    """Tests for notification summary generation."""

    def test_pipeline_failure_summary_format(self):
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        event = _make_pipeline_failure_event()
        summary = service._build_summary(event)

        assert "ETL Daily Load" in summary
        assert "exec-12345" in summary
        assert "transform_join" in summary
        assert "2024-06-15" in summary

    def test_connector_failure_summary_format(self):
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        event = _make_connector_failure_event()
        summary = service._build_summary(event)

        assert "Production PostgreSQL" in summary
        assert "postgresql" in summary

    def test_resource_threshold_summary_format(self):
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        event = _make_resource_threshold_event()
        summary = service._build_summary(event)

        assert "Disk Storage" in summary
        assert "92%" in summary
        assert "90%" in summary

    def test_unknown_event_type_fallback_summary(self):
        """Summary still works for edge case event types."""
        mock_db = AsyncMock()
        service = NotificationService(mock_db)

        # Test with a valid but exhaustive check
        event = NotificationEvent(
            event_type=NotificationEventType.PIPELINE_FAILURE,
            pipeline_name=None,
            execution_id=None,
            failure_timestamp=None,
            failing_node=None,
        )
        summary = service._build_summary(event)
        assert "unknown" in summary


# ---------- Celery Task Tests ----------


class TestNotificationTasks:
    """Tests for Celery async dispatch tasks."""

    @pytest.mark.asyncio
    async def test_process_notification_event_dispatch(self):
        """Verify async dispatch helper processes events correctly."""
        from backend.app.tasks._notification_dispatch import process_notification_event

        event_data = {
            "event_type": "resource_threshold",
            "source_resource_id": "resource-disk",
            "resource_name": "Disk Storage",
            "current_value": "95%",
            "threshold_value": "90%",
        }

        with patch(
            "backend.app.tasks._notification_dispatch.async_session_factory"
        ) as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch(
                "backend.app.tasks._notification_dispatch.NotificationService"
            ) as MockService:
                mock_service_instance = AsyncMock()
                mock_service_instance.create_notification = AsyncMock(return_value=[])
                MockService.return_value = mock_service_instance

                result = await process_notification_event(event_data)

        assert result["status"] == "success"
        assert result["notifications_created"] == 0

    @pytest.mark.asyncio
    async def test_cleanup_expired_task_dispatch(self):
        """Verify cleanup task helper works correctly."""
        from backend.app.tasks._notification_dispatch import run_cleanup_expired

        with patch(
            "backend.app.tasks._notification_dispatch.async_session_factory"
        ) as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch(
                "backend.app.tasks._notification_dispatch.NotificationService"
            ) as MockService:
                mock_service_instance = AsyncMock()
                mock_service_instance.cleanup_expired = AsyncMock(return_value=15)
                MockService.return_value = mock_service_instance

                result = await run_cleanup_expired()

        assert result["status"] == "success"
        assert result["deleted_count"] == 15
