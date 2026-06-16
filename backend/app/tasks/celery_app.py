"""Celery application configuration.

Uses RabbitMQ as the message broker and Redis as the result backend.
"""

from celery import Celery

from backend.app.core.config import settings

celery_app = Celery(
    "cloud_data_platform",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_always_eager=settings.celery_task_always_eager,
    worker_concurrency=settings.celery_worker_concurrency,
    task_routes={
        "backend.app.tasks.notification_tasks.*": {"queue": "notifications"},
    },
)

# Auto-discover task modules
celery_app.autodiscover_tasks(["backend.app.tasks"])
