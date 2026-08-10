import asyncio
import logging
from typing import Any
from uuid import UUID

from celery import Task
from sqlalchemy.exc import OperationalError

from tracelink.connectors.errors import ConnectorError
from tracelink.connectors.models import ResearchTaskResult
from tracelink.connectors.registry import ConnectorRegistry, get_connector_registry
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
from tracelink.services.research_execution import ConnectorResearchExecutor

logger = logging.getLogger(__name__)


async def execute_research_task_async(
    research_task_id: UUID,
    celery_task_id: str,
    mode: FakeResearchMode | None,
    registry: ConnectorRegistry | None = None,
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

    output = None
    connector_name = "fake_research"
    if mode is None:
        configured_registry = registry or get_connector_registry()
        connectors = configured_registry.connectors_for_task_type(task.type)
        connector_name = connectors[0].name if connectors else "fake_research"
    try:
        if mode is not None:
            result = await FakeResearchExecutor(settings.fake_research_delay_ms).execute(
                task, mode=mode, is_cancelled=is_cancelled
            )
            output = None
        else:
            output = await ConnectorResearchExecutor(configured_registry).execute(
                task, is_cancelled=is_cancelled
            )
            connector_name = output.connector
            result = None
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
                error_message="simulated research failure",
                failure_result=ResearchTaskResult(
                    connector="fake_research",
                    status="failed",
                    metadata={"error_code": exc.code},
                ),
            )
        logger.warning("research task failed", extra={**context, "status": "FAILED"})
    except ConnectorError as exc:
        async with session_factory() as session, session.begin():
            await InvestigationWorkflowService(session, settings).fail(
                research_task_id,
                celery_task_id,
                error_code=exc.code,
                error_message=exc.public_message,
                failure_result=ResearchTaskResult(
                    connector=connector_name,
                    status="failed",
                    metadata={
                        "error_code": exc.code,
                        **({"status_code": exc.status_code} if exc.status_code else {}),
                    },
                ),
            )
        logger.warning(
            "research connector task failed",
            extra={
                **context,
                "status": "FAILED",
                "connector": connector_name,
                "status_code": exc.status_code,
            },
        )
    except OperationalError:
        raise
    except Exception:
        logger.exception("research task failed unexpectedly", extra=context)
        async with session_factory() as session, session.begin():
            await InvestigationWorkflowService(session, settings).fail(
                research_task_id,
                celery_task_id,
                error_code="UNEXPECTED_EXECUTOR_ERROR",
                error_message="research execution failed unexpectedly",
                failure_result=ResearchTaskResult(
                    connector="unknown",
                    status="failed",
                    metadata={"error_code": "UNEXPECTED_EXECUTOR_ERROR"},
                ),
            )
    else:
        persisted_result: ResearchTaskResult | None = None
        async with session_factory() as session, session.begin():
            workflow = InvestigationWorkflowService(session, settings)
            if output is not None:
                persisted_result = await workflow.complete_with_output(
                    research_task_id, celery_task_id, output
                )
            else:
                assert result is not None
                await workflow.complete(research_task_id, celery_task_id, result)
        logger.info("research task completed", extra={**context, "status": "COMPLETED"})
        if persisted_result is not None:
            from tracelink.jobs.entities import process_document_entities

            for document_id in persisted_result.document_ids:
                await asyncio.to_thread(
                    process_document_entities.apply_async,
                    args=[str(task.investigation_id), str(document_id)],
                )


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
    mode: str | None = None,
) -> None:
    try:
        async_worker_runtime.run(
            execute_research_task_async(
                UUID(research_task_id),
                str(self.request.id),
                FakeResearchMode(mode) if mode is not None else None,
            )
        )
    except OperationalError as exc:
        settings = get_settings()
        raise self.retry(
            exc=exc,
            countdown=min(2 ** int(self.request.retries), 30),
            max_retries=settings.celery_transport_max_retries,
        ) from exc
