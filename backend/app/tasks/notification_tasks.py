"""Celery tasks for asynchronous notification dispatch.

These tasks handle the async delivery of notifications via RabbitMQ,
decoupling event production from notification generation and storage.
"""

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from backend.app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="backend.app.tasks.notification_tasks.dispatch_notification",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
)
def dispatch_notification(self, event_data: dict) -> dict:
    """Dispatch a notification event for processing.

    This task is enqueued when a critical event occurs. It triggers
    the notification service to create notifications for the appropriate
    recipients based on event type and role-based targeting.

    Args:
        event_data: Dictionary containing the notification event details:
            - event_type: Type of event (pipeline_failure, connector_health_failure, resource_threshold)
            - source_resource_id: ID of the source resource
            - Additional fields depending on event_type

    Returns:
        Dictionary with dispatch status and notification IDs created.
    """
    import asyncio

    from backend.app.tasks._notification_dispatch import process_notification_event

    try:
        result = asyncio.get_event_loop().run_until_complete(
            process_notification_event(event_data)
        )
        return result
    except RuntimeError:
        # No event loop running, create a new one
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                process_notification_event(event_data)
            )
            return result
        finally:
            loop.close()
    except Exception as exc:
        logger.error("Notification dispatch failed: %s", exc)
        raise self.retry(exc=exc)


@celery_app.task(
    name="backend.app.tasks.notification_tasks.cleanup_expired_notifications",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def cleanup_expired_notifications(self) -> dict:
    """Periodic task to clean up notifications older than 30 days.

    Deletes expired notifications from the database. Intended to be
    run on a schedule (e.g., daily via Celery Beat).

    Returns:
        Dictionary with the count of deleted notifications.
    """
    import asyncio

    from backend.app.tasks._notification_dispatch import run_cleanup_expired

    try:
        result = asyncio.get_event_loop().run_until_complete(run_cleanup_expired())
        return result
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(run_cleanup_expired())
            return result
        finally:
            loop.close()
    except Exception as exc:
        logger.error("Notification cleanup failed: %s", exc)
        raise self.retry(exc=exc)


# Celery Beat schedule for periodic cleanup
celery_app.conf.beat_schedule = {
    "cleanup-expired-notifications": {
        "task": "backend.app.tasks.notification_tasks.cleanup_expired_notifications",
        "schedule": timedelta(hours=24),
    },
}
