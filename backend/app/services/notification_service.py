"""Notification Service — generation, deduplication, delivery, and retention management.

This service provides:
- create_notification: Generate notifications for role-based recipients based on event type
- get_user_notifications: Paginated chronological list with read status
- mark_as_read: Mark individual notification as read
- suppress_duplicate: Suppress same source within 15 min, increment recurrence_count
- cleanup_expired: Delete notifications older than 30 days

Uses Celery + RabbitMQ for async dispatch and Redis for deduplication windows.
"""

import logging
import math
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.redis import get_redis_client
from backend.app.models.notifications import Notification
from backend.app.models.users import Role, User
from backend.app.schemas.notification import (
    NotificationCreate,
    NotificationEvent,
    NotificationEventType,
    NotificationListResponse,
    NotificationResponse,
)

logger = logging.getLogger(__name__)

# Deduplication window in seconds (15 minutes)
DEDUP_WINDOW_SECONDS = settings.notification_dedup_window_minutes * 60
# Retention period in days
RETENTION_DAYS = settings.notification_retention_days
# Page size for notification listing
PAGE_SIZE = 30


class NotificationService:
    """Service for managing user notifications.

    Provides notification generation with role-based targeting,
    deduplication within a 15-minute window, pagination, and
    automatic cleanup of expired notifications.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_notification(self, event: NotificationEvent) -> list[Notification]:
        """Generate notifications for correct role-based recipients.

        Routing rules:
        - Pipeline failure → pipeline owner + all Operators
        - Connector health failure → all Data_Engineers + all Operators
        - Resource threshold → all Admins

        Before creating, checks for duplicates within the suppression window.

        Args:
            event: The notification event containing event-specific details.

        Returns:
            List of created Notification objects (may be empty if suppressed).
        """
        # Check for duplicate suppression first
        if event.source_resource_id:
            is_suppressed = await self.suppress_duplicate(
                source_id=event.source_resource_id,
                event_type=event.event_type.value,
            )
            if is_suppressed:
                return []

        # Determine recipients based on event type
        recipient_ids = await self._get_recipients(event)

        if not recipient_ids:
            logger.warning(
                "No recipients found for notification event_type=%s source=%s",
                event.event_type.value,
                event.source_resource_id,
            )
            return []

        # Build notification summary
        summary = self._build_summary(event)

        # Calculate expiration
        expires_at = datetime.now(timezone.utc) + timedelta(days=RETENTION_DAYS)

        # Create notifications for each recipient
        notifications = []
        for user_id in recipient_ids:
            notification = Notification(
                user_id=user_id,
                event_type=event.event_type.value,
                source_resource_id=event.source_resource_id,
                summary=summary,
                is_read=False,
                recurrence_count=0,
                expires_at=expires_at,
            )
            self.db.add(notification)
            notifications.append(notification)

        await self.db.flush()

        # Set deduplication key in Redis
        if event.source_resource_id:
            await self._set_dedup_key(event.source_resource_id, event.event_type.value)

        return notifications

    async def get_user_notifications(
        self, user_id: UUID, page: int = 1, page_size: int = PAGE_SIZE
    ) -> NotificationListResponse:
        """Get paginated chronological list of user notifications with read status.

        Returns notifications ordered by created_at descending (newest first).

        Args:
            user_id: The user whose notifications to retrieve.
            page: Page number (1-indexed).
            page_size: Number of notifications per page (default 20).

        Returns:
            Paginated notification list response.
        """
        page = max(page, 1)
        page_size = max(1, min(page_size, 100))  # Clamp between 1 and 100

        # Count total notifications for the user
        count_query = select(func.count(Notification.id)).where(
            Notification.user_id == user_id
        )
        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0

        # Calculate pagination
        pages = math.ceil(total / page_size) if total > 0 else 0
        offset = (page - 1) * page_size

        # Fetch notifications ordered chronologically (newest first)
        query = (
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        result = await self.db.execute(query)
        notifications = result.scalars().all()

        items = [
            NotificationResponse(
                id=n.id,
                user_id=n.user_id,
                event_type=n.event_type,
                source_resource_id=n.source_resource_id,
                summary=n.summary,
                is_read=n.is_read,
                recurrence_count=n.recurrence_count,
                created_at=n.created_at,
            )
            for n in notifications
        ]

        return NotificationListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )

    async def mark_as_read(self, notification_id: UUID, user_id: UUID) -> None:
        """Mark an individual notification as read.

        Only the owning user can mark their notifications as read.

        Args:
            notification_id: The notification to mark as read.
            user_id: The user making the request (for ownership verification).

        Raises:
            ValueError: If the notification does not exist or belongs to another user.
        """
        stmt = (
            update(Notification)
            .where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
            )
            .values(is_read=True)
        )
        result = await self.db.execute(stmt)

        if result.rowcount == 0:
            raise ValueError("Notification not found or does not belong to this user")

        await self.db.flush()

    async def suppress_duplicate(self, source_id: str, event_type: str) -> bool:
        """Check if a notification should be suppressed as a duplicate.

        If the same source triggers an identical event type within 15 minutes
        of an existing unacknowledged notification, suppress the new one and
        increment the recurrence_count on the existing notification.

        Args:
            source_id: The resource ID that triggered the event.
            event_type: The type of event.

        Returns:
            True if the notification should be suppressed, False otherwise.
        """
        dedup_key = f"notification_dedup:{source_id}:{event_type}"

        try:
            redis_client = get_redis_client()
            existing = await redis_client.get(dedup_key)

            if existing:
                # Duplicate within window — increment recurrence count on existing notification
                await self._increment_recurrence(source_id, event_type)
                return True
        except Exception as exc:
            # Redis unavailable — fall through to DB check
            logger.warning("Redis dedup check failed (fallback to DB): %s", exc)

            # Fallback: check database for recent unread notification from same source
            window_start = datetime.now(timezone.utc) - timedelta(
                seconds=DEDUP_WINDOW_SECONDS
            )
            stmt = select(Notification).where(
                Notification.source_resource_id == source_id,
                Notification.event_type == event_type,
                Notification.is_read == False,  # noqa: E712
                Notification.created_at >= window_start,
            )
            result = await self.db.execute(stmt)
            existing_notification = result.scalars().first()

            if existing_notification:
                existing_notification.recurrence_count += 1
                await self.db.flush()
                return True

        return False

    async def cleanup_expired(self) -> int:
        """Delete notifications older than the configured retention period (30 days).

        Returns:
            The number of notifications deleted.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)

        stmt = delete(Notification).where(Notification.created_at < cutoff)
        result = await self.db.execute(stmt)
        await self.db.flush()

        deleted_count = result.rowcount
        logger.info("Cleaned up %d expired notifications", deleted_count)
        return deleted_count

    # --- Private helpers ---

    async def _get_recipients(self, event: NotificationEvent) -> list[UUID]:
        """Determine notification recipients based on event type and role targeting.

        Routing:
        - pipeline_failure → pipeline owner + all Operators
        - connector_health_failure → all Data_Engineers + all Operators
        - resource_threshold → all Admins
        """
        recipient_ids: set[UUID] = set()

        if event.event_type == NotificationEventType.PIPELINE_FAILURE:
            # Pipeline owner
            if event.pipeline_owner_id:
                recipient_ids.add(event.pipeline_owner_id)
            # All Operators
            operators = await self._get_users_by_role("Operator")
            recipient_ids.update(operators)

        elif event.event_type == NotificationEventType.CONNECTOR_HEALTH_FAILURE:
            # All Data_Engineers
            data_engineers = await self._get_users_by_role("Data_Engineer")
            recipient_ids.update(data_engineers)
            # All Operators
            operators = await self._get_users_by_role("Operator")
            recipient_ids.update(operators)

        elif event.event_type == NotificationEventType.RESOURCE_THRESHOLD:
            # All Admins
            admins = await self._get_users_by_role("Admin")
            recipient_ids.update(admins)

        return list(recipient_ids)

    async def _get_users_by_role(self, role_name: str) -> list[UUID]:
        """Get all active user IDs with a specific role."""
        stmt = (
            select(User.id)
            .join(Role, User.role_id == Role.id)
            .where(
                Role.name == role_name,
                User.is_active == True,  # noqa: E712
                User.is_deleted == False,  # noqa: E712
            )
        )
        result = await self.db.execute(stmt)
        return [row[0] for row in result.all()]

    def _build_summary(self, event: NotificationEvent) -> str:
        """Build a human-readable summary for the notification."""
        if event.event_type == NotificationEventType.PIPELINE_FAILURE:
            timestamp_str = (
                event.failure_timestamp.isoformat()
                if event.failure_timestamp
                else "unknown time"
            )
            return (
                f"Pipeline '{event.pipeline_name or 'unknown'}' failed "
                f"(execution: {event.execution_id or 'N/A'}) "
                f"at {timestamp_str}. "
                f"Failing node: {event.failing_node or 'unknown'}"
            )

        elif event.event_type == NotificationEventType.CONNECTOR_HEALTH_FAILURE:
            timestamp_str = (
                event.failure_timestamp.isoformat()
                if event.failure_timestamp
                else "unknown time"
            )
            return (
                f"Connector '{event.connector_name or 'unknown'}' "
                f"(type: {event.connector_type or 'unknown'}) "
                f"health check failed at {timestamp_str}"
            )

        elif event.event_type == NotificationEventType.RESOURCE_THRESHOLD:
            return (
                f"Resource '{event.resource_name or 'unknown'}' exceeded threshold: "
                f"current value {event.current_value or 'N/A'}, "
                f"threshold {event.threshold_value or 'N/A'}"
            )

        return f"Notification: {event.event_type.value}"

    async def _increment_recurrence(self, source_id: str, event_type: str) -> None:
        """Increment recurrence_count on the most recent unread notification from the same source."""
        window_start = datetime.now(timezone.utc) - timedelta(
            seconds=DEDUP_WINDOW_SECONDS
        )
        stmt = (
            select(Notification)
            .where(
                Notification.source_resource_id == source_id,
                Notification.event_type == event_type,
                Notification.is_read == False,  # noqa: E712
                Notification.created_at >= window_start,
            )
            .order_by(Notification.created_at.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        notification = result.scalars().first()

        if notification:
            notification.recurrence_count += 1
            await self.db.flush()

    async def _set_dedup_key(self, source_id: str, event_type: str) -> None:
        """Set a deduplication key in Redis with TTL matching the suppression window."""
        dedup_key = f"notification_dedup:{source_id}:{event_type}"
        try:
            redis_client = get_redis_client()
            await redis_client.setex(dedup_key, DEDUP_WINDOW_SECONDS, "1")
        except Exception as exc:
            # Redis unavailable — deduplication will fall back to DB check
            logger.warning("Failed to set Redis dedup key: %s", exc)


def get_notification_service(db: AsyncSession) -> NotificationService:
    """Factory function for dependency injection of NotificationService."""
    return NotificationService(db)
