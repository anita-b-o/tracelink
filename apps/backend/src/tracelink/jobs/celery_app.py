from celery import Celery
from celery.signals import worker_process_shutdown

from tracelink.core.config import get_settings
from tracelink.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

celery_app = Celery(
    "tracelink",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "tracelink.jobs.research",
        "tracelink.jobs.entities",
        "tracelink.jobs.relationships",
        "tracelink.jobs.rag",
        "tracelink.jobs.reports",
    ],
)
celery_app.conf.update(
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    enable_utc=True,
    result_serializer="json",
    task_serializer="json",
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    timezone="UTC",
    worker_hijack_root_logger=False,
    worker_prefetch_multiplier=1,
)


@worker_process_shutdown.connect  # type: ignore[untyped-decorator]
def close_worker_runtime(**_: object) -> None:
    from tracelink.jobs.async_runtime import async_worker_runtime

    async_worker_runtime.close()
