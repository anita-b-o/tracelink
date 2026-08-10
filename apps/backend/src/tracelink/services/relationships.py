from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.domain.enums import AssertionStatus, RelationshipType
from tracelink.domain.models import Entity, JsonObject, Relationship
from tracelink.domain.relationship_extraction import (
    canonicalize_relationship_endpoints,
    relationship_types_compatible,
    validate_partial_date,
)
from tracelink.domain.validation import (
    validate_chronology,
    validate_confidence,
    validate_relationship_endpoints,
)
from tracelink.repositories.relationships import RelationshipRepository
from tracelink.services.errors import DomainNotFoundError


class RelationshipService:
    def __init__(self, session: AsyncSession, repository: RelationshipRepository) -> None:
        self.session = session
        self.repository = repository

    async def create(
        self,
        *,
        source_entity_id: UUID,
        target_entity_id: UUID,
        relationship_type: RelationshipType,
        confidence: float,
        status: AssertionStatus,
        first_observed_at: datetime | None = None,
        last_observed_at: datetime | None = None,
        temporal_start: str | None = None,
        temporal_end: str | None = None,
        metadata: JsonObject | None = None,
    ) -> Relationship:
        source_entity_id, target_entity_id = canonicalize_relationship_endpoints(
            source_entity_id, target_entity_id, relationship_type
        )
        validate_relationship_endpoints(source_entity_id, target_entity_id)
        validate_confidence(confidence)
        validate_chronology(
            first_observed_at,
            last_observed_at,
            "first_observed_at",
            "last_observed_at",
        )
        validate_partial_date(temporal_start)
        validate_partial_date(temporal_end)
        source_entity = await self.session.get(Entity, source_entity_id)
        if source_entity is None:
            raise DomainNotFoundError("source entity not found")
        target_entity = await self.session.get(Entity, target_entity_id)
        if target_entity is None:
            raise DomainNotFoundError("target entity not found")
        if not relationship_types_compatible(
            relationship_type, source_entity.type, target_entity.type
        ):
            raise ValueError("relationship endpoint types are incompatible")
        existing = await self.repository.get_by_identity(
            source_entity_id, target_entity_id, relationship_type
        )
        if existing is not None:
            return existing
        return await self.repository.create(
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            relationship_type=relationship_type,
            confidence=confidence,
            status=status,
            first_observed_at=first_observed_at,
            last_observed_at=last_observed_at,
            temporal_start=temporal_start,
            temporal_end=temporal_end,
            metadata=metadata,
        )
