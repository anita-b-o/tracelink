import logging
from uuid import UUID

from celery import Task
from kombu.exceptions import OperationalError as KombuOperationalError
from sqlalchemy.exc import OperationalError

from tracelink.core.config import get_settings
from tracelink.domain.entity_extraction import EntityExtractionProviderError
from tracelink.infrastructure.database import get_session_factory
from tracelink.jobs.async_runtime import async_worker_runtime
from tracelink.jobs.celery_app import celery_app
from tracelink.services.document_entity_processing import DocumentEntityProcessingService
from tracelink.services.outbox import enqueue_task
from tracelink.services.ownership import require_owned_investigation

logger = logging.getLogger(__name__)


async def process_document_entities_async(
    investigation_id: UUID, document_id: UUID, downstream_queue: str | None = None
) -> bool:
    settings = get_settings()
    async with get_session_factory()() as session, session.begin():
        await require_owned_investigation(session, investigation_id)
        mentions = await DocumentEntityProcessingService(session, settings).process(
            investigation_id, document_id
        )
        should_process_relationships = (
            len({mention.entity_id for mention in mentions if mention.entity_id is not None}) >= 2
        )
        await enqueue_task(
            session,
            (
                "tracelink.process_document_relationships"
                if should_process_relationships
                else "tracelink.index_document_for_retrieval"
            ),
            [str(investigation_id), str(document_id)],
            queue=downstream_queue,
        )
    logger.info(
        "document entity extraction completed",
        extra={
            "investigation_id": str(investigation_id),
            "document_id": str(document_id),
            "status": "COMPLETED",
            "mention_count": len(mentions),
        },
    )
    return should_process_relationships


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="tracelink.process_document_entities",
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
)
def process_document_entities(
    self: Task,
    investigation_id: str,
    document_id: str,
) -> None:
    try:
        delivery_info = self.request.delivery_info or {}
        routing_key = delivery_info.get("routing_key")
        async_worker_runtime.run(
            process_document_entities_async(
                UUID(investigation_id),
                UUID(document_id),
                str(routing_key) if routing_key else None,
            )
        )
    except (OperationalError, KombuOperationalError, EntityExtractionProviderError) as exc:
        settings = get_settings()
        raise self.retry(
            exc=exc,
            countdown=min(2 ** int(self.request.retries), 30),
            max_retries=settings.celery_transport_max_retries,
        ) from exc
