"""Internal async helpers for notification task execution.

These are called from Celery tasks to interact with the database
and notification service asynchronously.
"""

import logging

from backend.app.core.database import async_session_factory
from backend.app.schemas.notification import NotificationEvent, NotificationEventType
from backend.app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


async def process_notification_event(event_data: dict) -> dict:
    """Process a notification event and create notifications for recipients.

    Args:
        event_data: Raw event data dictionary from Celery task.

    Returns:
        Dictionary with status and count of notifications created.
    """
    async with async_session_factory() as session:
        try:
            service = NotificationService(session)
            event = NotificationEvent(**event_data)
            notifications = await service.create_notification(event)
            await session.commit()
            return {
                "status": "success",
                "notifications_created": len(notifications),
            }
        except Exception as exc:
            await session.rollback()
            logger.error("Failed to process notification event: %s", exc)
            raise


async def run_cleanup_expired() -> dict:
    """Run the expired notification cleanup.

    Returns:
        Dictionary with the count of deleted notifications.
    """
    async with async_session_factory() as session:
        try:
            service = NotificationService(session)
            deleted_count = await service.cleanup_expired()
            await session.commit()
            return {
                "status": "success",
                "deleted_count": deleted_count,
            }
        except Exception as exc:
            await session.rollback()
            logger.error("Failed to cleanup expired notifications: %s", exc)
            raise
