from celery import Celery

from tracelink.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "tracelink",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    enable_utc=True,
    result_serializer="json",
    task_serializer="json",
    task_track_started=True,
    timezone="UTC",
)
