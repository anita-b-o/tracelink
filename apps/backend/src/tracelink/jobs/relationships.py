import logging
from uuid import UUID

from celery import Task
from sqlalchemy.exc import OperationalError

from tracelink.core.config import get_settings
from tracelink.domain.relationship_extraction import (
    TransientRelationshipExtractionProviderError,
)
from tracelink.infrastructure.database import get_session_factory
from tracelink.jobs.async_runtime import async_worker_runtime
from tracelink.jobs.celery_app import celery_app
from tracelink.services.document_relationship_processing import (
    DocumentRelationshipProcessingService,
)
from tracelink.services.relationship_extraction_providers import (
    get_relationship_extraction_provider,
)

logger = logging.getLogger(__name__)


async def process_document_relationships_async(investigation_id: UUID, document_id: UUID) -> None:
    settings = get_settings()
    async with get_session_factory()() as session, session.begin():
        candidates = await DocumentRelationshipProcessingService(
            session, settings, get_relationship_extraction_provider()
        ).process(investigation_id, document_id)
    logger.info(
        "document relationship extraction completed",
        extra={
            "investigation_id": str(investigation_id),
            "document_id": str(document_id),
            "status": "COMPLETED",
            "relationship_candidate_count": len(candidates),
        },
    )


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="tracelink.process_document_relationships",
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
)
def process_document_relationships(
    self: Task,
    investigation_id: str,
    document_id: str,
) -> None:
    try:
        async_worker_runtime.run(
            process_document_relationships_async(UUID(investigation_id), UUID(document_id))
        )
        from tracelink.jobs.rag import index_document_for_retrieval

        delivery_info = self.request.delivery_info or {}
        routing_key = delivery_info.get("routing_key")
        options = {"queue": routing_key} if routing_key else {}
        index_document_for_retrieval.apply_async(args=[investigation_id, document_id], **options)
    except (OperationalError, TransientRelationshipExtractionProviderError) as exc:
        settings = get_settings()
        raise self.retry(
            exc=exc,
            countdown=min(2 ** int(self.request.retries), 30),
            max_retries=settings.celery_transport_max_retries,
        ) from exc
