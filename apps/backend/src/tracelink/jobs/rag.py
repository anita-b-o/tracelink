import logging
from uuid import UUID

from celery import Task
from sqlalchemy.exc import OperationalError

from tracelink.core.config import get_settings
from tracelink.infrastructure.database import get_session_factory
from tracelink.jobs.async_runtime import async_worker_runtime
from tracelink.jobs.celery_app import celery_app
from tracelink.services.embedding_providers import (
    TransientEmbeddingProviderError,
    get_embedding_provider,
)
from tracelink.services.ownership import require_owned_investigation
from tracelink.services.retrieval_indexing import RetrievalIndexingService

logger = logging.getLogger(__name__)


async def index_document_for_retrieval_async(investigation_id: UUID, document_id: UUID) -> None:
    settings = get_settings()
    async with get_session_factory()() as session, session.begin():
        await require_owned_investigation(session, investigation_id)
        await RetrievalIndexingService(session, settings, get_embedding_provider(settings)).index(
            investigation_id, document_id
        )


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="tracelink.index_document_for_retrieval",
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
)
def index_document_for_retrieval(self: Task, investigation_id: str, document_id: str) -> None:
    try:
        async_worker_runtime.run(
            index_document_for_retrieval_async(UUID(investigation_id), UUID(document_id))
        )
    except (OperationalError, TransientEmbeddingProviderError) as exc:
        settings = get_settings()
        raise self.retry(
            exc=exc,
            countdown=min(2 ** int(self.request.retries), 30),
            max_retries=settings.celery_transport_max_retries,
        ) from exc
