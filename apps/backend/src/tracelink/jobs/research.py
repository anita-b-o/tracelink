import logging
from typing import Any
from uuid import UUID

from celery import Task
from sqlalchemy.exc import OperationalError

from tracelink.core.config import get_settings
from tracelink.domain.enums import FakeResearchMode
from tracelink.infrastructure.database import get_session_factory
from tracelink.jobs.async_runtime import async_worker_runtime
from tracelink.jobs.celery_app import celery_app
from tracelink.services.fake_research import (
    FakeResearchCancelled,
    FakeResearchError,
    FakeResearchExecutor,
)
from tracelink.services.investigation_workflow import InvestigationWorkflowService

logger = logging.getLogger(__name__)


async def execute_research_task_async(
    research_task_id: UUID,
    celery_task_id: str,
    mode: FakeResearchMode,
) -> None:
    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session, session.begin():
        task = await InvestigationWorkflowService(session, settings).claim(
            research_task_id, celery_task_id
        )
    if task is None:
        logger.info(
            "research task delivery ignored",
            extra={"research_task_id": str(research_task_id), "celery_task_id": celery_task_id},
        )
        return

    context: dict[str, Any] = {
        "investigation_id": str(task.investigation_id),
        "research_task_id": str(task.id),
        "celery_task_id": celery_task_id,
        "task_type": task.type.value,
        "status": task.status.value,
    }
    logger.info("research task started", extra=context)

    async def is_cancelled() -> bool:
        async with session_factory() as check_session:
            return await InvestigationWorkflowService(check_session, settings).is_cancelled(
                task.investigation_id
            )

    try:
        result = await FakeResearchExecutor(settings.fake_research_delay_ms).execute(
            task, mode=mode, is_cancelled=is_cancelled
        )
    except FakeResearchCancelled:
        async with session_factory() as session, session.begin():
            await InvestigationWorkflowService(session, settings).acknowledge_cancellation(
                research_task_id, celery_task_id
            )
        logger.info("research task cancelled", extra={**context, "status": "CANCELLED"})
    except FakeResearchError as exc:
        async with session_factory() as session, session.begin():
            await InvestigationWorkflowService(session, settings).fail(
                research_task_id,
                celery_task_id,
                error_code=exc.code,
                error_message=str(exc),
            )
        logger.warning("research task failed", extra={**context, "status": "FAILED"})
    except OperationalError:
        raise
    except Exception as exc:
        logger.exception("research task failed unexpectedly", extra=context)
        async with session_factory() as session, session.begin():
            await InvestigationWorkflowService(session, settings).fail(
                research_task_id,
                celery_task_id,
                error_code="UNEXPECTED_EXECUTOR_ERROR",
                error_message=str(exc),
            )
    else:
        async with session_factory() as session, session.begin():
            await InvestigationWorkflowService(session, settings).complete(
                research_task_id, celery_task_id, result
            )
        logger.info("research task completed", extra={**context, "status": "COMPLETED"})


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="tracelink.execute_research_task",
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
)
def execute_research_task(
    self: Task,
    research_task_id: str,
    mode: str = FakeResearchMode.SUCCESS.value,
) -> None:
    try:
        async_worker_runtime.run(
            execute_research_task_async(
                UUID(research_task_id), str(self.request.id), FakeResearchMode(mode)
            )
        )
    except OperationalError as exc:
        settings = get_settings()
        raise self.retry(
            exc=exc,
            countdown=min(2 ** int(self.request.retries), 30),
            max_retries=settings.celery_transport_max_retries,
        ) from exc
