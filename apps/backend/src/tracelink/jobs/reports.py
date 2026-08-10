import logging
from uuid import UUID

from celery import Task
from sqlalchemy.exc import OperationalError

from tracelink.core.config import get_settings
from tracelink.infrastructure.database import get_session_factory
from tracelink.jobs.async_runtime import async_worker_runtime
from tracelink.jobs.celery_app import celery_app
from tracelink.services.embedding_providers import get_embedding_provider
from tracelink.services.grounded_reports import InvestigationReportService
from tracelink.services.hybrid_retrieval import HybridRetriever
from tracelink.services.llm_providers import (
    TransientLLMProviderError,
    get_llm_provider,
)

logger = logging.getLogger(__name__)


async def generate_investigation_report_async(report_id: UUID, celery_task_id: str) -> None:
    settings = get_settings()
    async with get_session_factory()() as session, session.begin():
        embeddings = get_embedding_provider(settings)
        llm = get_llm_provider(settings)
        report = await InvestigationReportService(
            session,
            settings,
            llm,
            HybridRetriever(session, settings, embeddings),
        ).generate(report_id, celery_task_id)
    logger.info(
        "grounded report generation completed",
        extra={
            "report_id": str(report_id),
            "investigation_id": str(report.investigation_id),
            "llm_provider": report.provider,
            "llm_model": report.model,
            "status": report.status.value,
        },
    )


async def fail_investigation_report_async(report_id: UUID, code: str, message: str) -> None:
    settings = get_settings()
    async with get_session_factory()() as session, session.begin():
        llm = get_llm_provider(settings)
        embeddings = get_embedding_provider(settings)
        await InvestigationReportService(
            session,
            settings,
            llm,
            HybridRetriever(session, settings, embeddings),
        ).fail(report_id, code=code, message=message)


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="tracelink.generate_investigation_report",
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
)
def generate_investigation_report(self: Task, report_id: str) -> None:
    identifier = UUID(report_id)
    try:
        async_worker_runtime.run(
            generate_investigation_report_async(identifier, str(self.request.id))
        )
    except (OperationalError, TransientLLMProviderError) as exc:
        settings = get_settings()
        raise self.retry(
            exc=exc,
            countdown=min(2 ** int(self.request.retries), 30),
            max_retries=settings.celery_transport_max_retries,
        ) from exc
    except Exception as exc:
        logger.exception("grounded report generation failed", extra={"report_id": report_id})
        async_worker_runtime.run(
            fail_investigation_report_async(identifier, "REPORT_GENERATION_FAILED", str(exc)[:500])
        )
