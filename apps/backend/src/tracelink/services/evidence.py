from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.domain.models import Document, Entity, Evidence, Investigation, Relationship, Source
from tracelink.domain.validation import validate_confidence, validate_evidence_target
from tracelink.repositories.evidence import EvidenceRepository
from tracelink.services.errors import DomainNotFoundError


class EvidenceService:
    def __init__(self, session: AsyncSession, repository: EvidenceRepository) -> None:
        self.session = session
        self.repository = repository

    async def create(
        self,
        *,
        investigation_id: UUID,
        source_id: UUID,
        confidence: float,
        document_id: UUID | None = None,
        relationship_id: UUID | None = None,
        entity_id: UUID | None = None,
        excerpt: str | None = None,
        locator: str | None = None,
    ) -> Evidence:
        validate_confidence(confidence)
        validate_evidence_target(entity_id, relationship_id)
        if await self.session.get(Investigation, investigation_id) is None:
            raise DomainNotFoundError("investigation not found")
        if await self.session.get(Source, source_id) is None:
            raise DomainNotFoundError("source not found")
        if entity_id is not None and await self.session.get(Entity, entity_id) is None:
            raise DomainNotFoundError("entity not found")
        if (
            relationship_id is not None
            and await self.session.get(Relationship, relationship_id) is None
        ):
            raise DomainNotFoundError("relationship not found")
        if document_id is not None:
            document = await self.session.get(Document, document_id)
            if document is None:
                raise DomainNotFoundError("document not found")
            if document.source_id != source_id:
                raise ValueError("document does not belong to the evidence source")
        return await self.repository.create(
            investigation_id=investigation_id,
            source_id=source_id,
            document_id=document_id,
            relationship_id=relationship_id,
            entity_id=entity_id,
            excerpt=excerpt,
            locator=locator,
            confidence=confidence,
        )
