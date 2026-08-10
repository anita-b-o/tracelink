from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.domain.enums import AssertionStatus, RelationshipType
from tracelink.domain.models import JsonObject, Relationship


class RelationshipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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
        metadata: JsonObject | None = None,
    ) -> Relationship:
        relationship = Relationship(
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            type=relationship_type,
            confidence=confidence,
            status=status,
            first_observed_at=first_observed_at,
            last_observed_at=last_observed_at,
            metadata_=metadata or {},
        )
        self.session.add(relationship)
        await self.session.flush()
        await self.session.refresh(relationship)
        return relationship

    async def get_by_id(self, relationship_id: UUID) -> Relationship | None:
        return await self.session.get(Relationship, relationship_id)

    async def get_by_identity(
        self,
        source_entity_id: UUID,
        target_entity_id: UUID,
        relationship_type: RelationshipType,
    ) -> Relationship | None:
        return cast(
            Relationship | None,
            await self.session.scalar(
                select(Relationship).where(
                    Relationship.source_entity_id == source_entity_id,
                    Relationship.target_entity_id == target_entity_id,
                    Relationship.type == relationship_type,
                )
            ),
        )

    async def list(self, *, limit: int = 50, offset: int = 0) -> list[Relationship]:
        result = await self.session.scalars(
            select(Relationship)
            .order_by(Relationship.created_at.desc(), Relationship.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result)

    async def update(
        self,
        relationship: Relationship,
        *,
        confidence: float | None = None,
        status: AssertionStatus | None = None,
        last_observed_at: datetime | None = None,
    ) -> Relationship:
        if confidence is not None:
            relationship.confidence = confidence
        if status is not None:
            relationship.status = status
        if last_observed_at is not None:
            relationship.last_observed_at = last_observed_at
        await self.session.flush()
        await self.session.refresh(relationship)
        return relationship
