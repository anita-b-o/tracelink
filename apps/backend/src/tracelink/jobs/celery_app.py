from celery import Celery
from celery.signals import task_postrun, worker_process_shutdown

from tracelink.core.config import get_settings
from tracelink.core.logging import configure_logging
from tracelink.observability.metrics import CELERY_JOBS

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
    broker_connection_max_retries=settings.celery_transport_max_retries,
    broker_transport_options={
        "visibility_timeout": settings.celery_visibility_timeout_seconds,
        "socket_connect_timeout": settings.redis_connect_timeout_seconds,
        "socket_timeout": settings.redis_socket_timeout_seconds,
    },
    enable_utc=True,
    result_serializer="json",
    task_serializer="json",
    task_track_started=True,
    task_soft_time_limit=settings.celery_task_soft_time_limit_seconds,
    task_time_limit=settings.celery_task_time_limit_seconds,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    timezone="UTC",
    worker_hijack_root_logger=False,
    worker_prefetch_multiplier=1,
    worker_concurrency=settings.celery_worker_concurrency,
    worker_max_tasks_per_child=settings.celery_worker_max_tasks_per_child,
    worker_soft_shutdown_timeout=60,
)


@worker_process_shutdown.connect  # type: ignore[untyped-decorator]
def close_worker_runtime(**_: object) -> None:
    from tracelink.jobs.async_runtime import async_worker_runtime

    async_worker_runtime.close()


@task_postrun.connect  # type: ignore[untyped-decorator]
def record_task_outcome(task: object = None, state: str | None = None, **_: object) -> None:
    name = str(getattr(task, "name", "unknown"))
    outcome = "success" if state == "SUCCESS" else str(state or "unknown").lower()
    CELERY_JOBS.labels(name, outcome).inc()
