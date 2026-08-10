from __future__ import annotations

import builtins
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
        temporal_start: str | None = None,
        temporal_end: str | None = None,
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
            temporal_start=temporal_start,
            temporal_end=temporal_end,
            metadata_=metadata or {},
        )
        self.session.add(relationship)
        await self.session.flush()
        await self.session.refresh(relationship)
        return relationship

    async def get_by_id(self, relationship_id: UUID) -> Relationship | None:
        return cast(
            Relationship | None,
            await self.session.scalar(
                select(Relationship)
                .options(
                    selectinload(Relationship.source_entity),
                    selectinload(Relationship.target_entity),
                    selectinload(Relationship.evidence),
                )
                .where(Relationship.id == relationship_id)
            ),
        )

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

    async def list_by_investigation(
        self, investigation_id: UUID, *, limit: int, offset: int
    ) -> builtins.list[tuple[Relationship, int]]:
        from tracelink.domain.models import Evidence

        result = await self.session.execute(
            select(Relationship, func.count(Evidence.id))
            .join(Evidence, Evidence.relationship_id == Relationship.id)
            .options(
                selectinload(Relationship.source_entity),
                selectinload(Relationship.target_entity),
            )
            .where(Evidence.investigation_id == investigation_id)
            .group_by(Relationship.id)
            .order_by(Relationship.updated_at.desc(), Relationship.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [(relationship, int(count)) for relationship, count in result]

    async def upsert(
        self,
        *,
        source_entity_id: UUID,
        target_entity_id: UUID,
        relationship_type: RelationshipType,
        confidence: float,
        status: AssertionStatus,
        observed_at: datetime,
        temporal_start: str | None,
        temporal_end: str | None,
        metadata: JsonObject,
    ) -> Relationship:
        insert_statement = insert(Relationship).values(
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            type=relationship_type,
            confidence=confidence,
            status=status,
            first_observed_at=observed_at,
            last_observed_at=observed_at,
            temporal_start=temporal_start,
            temporal_end=temporal_end,
            metadata_=metadata,
        )
        statement = insert_statement.on_conflict_do_update(
            constraint="uq_relationship_directed_type",
            set_={
                "confidence": func.greatest(
                    Relationship.confidence, insert_statement.excluded.confidence
                ),
                "status": case(
                    (
                        Relationship.status == AssertionStatus.CONTRADICTED,
                        Relationship.status,
                    ),
                    else_=insert_statement.excluded.status,
                ),
                "first_observed_at": func.least(
                    Relationship.first_observed_at, insert_statement.excluded.first_observed_at
                ),
                "last_observed_at": func.greatest(
                    Relationship.last_observed_at, insert_statement.excluded.last_observed_at
                ),
                "temporal_start": func.coalesce(
                    Relationship.temporal_start, insert_statement.excluded.temporal_start
                ),
                "temporal_end": func.coalesce(
                    insert_statement.excluded.temporal_end, Relationship.temporal_end
                ),
                "metadata": Relationship.metadata_.op("||")(insert_statement.excluded.metadata),
                "updated_at": func.now(),
            },
        ).returning(Relationship)
        return (await self.session.scalars(statement)).one()

    async def update(
        self,
        relationship: Relationship,
        *,
        confidence: float | None = None,
        status: AssertionStatus | None = None,
        last_observed_at: datetime | None = None,
        temporal_end: str | None = None,
    ) -> Relationship:
        if confidence is not None:
            relationship.confidence = confidence
        if status is not None:
            relationship.status = status
        if last_observed_at is not None:
            relationship.last_observed_at = last_observed_at
        if temporal_end is not None:
            relationship.temporal_end = temporal_end
        await self.session.flush()
        await self.session.refresh(relationship)
        return relationship
