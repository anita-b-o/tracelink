import logging
from typing import Any
from uuid import UUID

from celery import Task
from kombu.exceptions import OperationalError as KombuOperationalError
from sqlalchemy.exc import OperationalError

from tracelink.connectors.errors import ConnectorError
from tracelink.connectors.models import ConnectorOutput, ResearchTaskResult
from tracelink.connectors.registry import ConnectorRegistry, get_connector_registry
from tracelink.core.config import get_settings
from tracelink.domain.enums import FakeResearchMode
from tracelink.infrastructure.database import get_session_factory
from tracelink.jobs.async_runtime import async_worker_runtime
from tracelink.jobs.celery_app import celery_app
from tracelink.observability.metrics import CONNECTOR_FAILURES
from tracelink.services.fake_research import (
    FakeResearchCancelled,
    FakeResearchError,
    FakeResearchExecutor,
)
from tracelink.services.investigation_workflow import InvestigationWorkflowService
from tracelink.services.outbox import enqueue_task
from tracelink.services.ownership import require_owned_investigation
from tracelink.services.research_execution import ConnectorResearchExecutor

logger = logging.getLogger(__name__)


async def execute_research_task_async(
    research_task_id: UUID,
    celery_task_id: str,
    mode: FakeResearchMode | None,
    registry: ConnectorRegistry | None = None,
    downstream_queue: str | None = None,
) -> None:
    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session, session.begin():
        task = await InvestigationWorkflowService(session, settings).claim(
            research_task_id, celery_task_id
        )
        if task is not None:
            await require_owned_investigation(session, task.investigation_id)
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
            fake_result = await FakeResearchExecutor(settings.fake_research_delay_ms).execute(
                task, mode=mode, is_cancelled=is_cancelled
            )
            if isinstance(fake_result, ConnectorOutput):
                output = fake_result
                result = None
            else:
                result = fake_result
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
        CONNECTOR_FAILURES.labels(connector_name, exc.code).inc()
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
                assert persisted_result is not None
                for document_id in persisted_result.document_ids:
                    await enqueue_task(
                        session,
                        "tracelink.process_document_entities",
                        [str(task.investigation_id), str(document_id)],
                        queue=downstream_queue,
                    )
            else:
                assert result is not None
                await workflow.complete(research_task_id, celery_task_id, result)
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
    mode: str | None = None,
) -> None:
    try:
        delivery_info = self.request.delivery_info or {}
        routing_key = delivery_info.get("routing_key")
        async_worker_runtime.run(
            execute_research_task_async(
                UUID(research_task_id),
                str(self.request.id),
                FakeResearchMode(mode) if mode is not None else None,
                downstream_queue=str(routing_key) if routing_key else None,
            )
        )
    except (OperationalError, KombuOperationalError) as exc:
        settings = get_settings()
        raise self.retry(
            exc=exc,
            countdown=min(2 ** int(self.request.retries), 30),
            max_retries=settings.celery_transport_max_retries,
        ) from exc
