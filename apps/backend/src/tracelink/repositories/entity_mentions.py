from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tracelink.domain.enums import EntityResolutionCandidateStatus, EntityType
from tracelink.domain.models import (
    EntityMention,
    EntityResolutionCandidate,
    JsonObject,
)


class EntityMentionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_fingerprint(
        self, investigation_id: UUID, document_id: UUID, fingerprint: str
    ) -> EntityMention | None:
        return cast(
            EntityMention | None,
            await self.session.scalar(
                select(EntityMention).where(
                    EntityMention.investigation_id == investigation_id,
                    EntityMention.document_id == document_id,
                    EntityMention.fingerprint == fingerprint,
                )
            ),
        )

    async def create(
        self,
        *,
        investigation_id: UUID,
        document_id: UUID,
        entity_type: EntityType,
        surface_form: str,
        normalized_form: str,
        start_offset: int | None,
        end_offset: int | None,
        chunk_index: int | None,
        extraction_method: str,
        confidence: float,
        fingerprint: str,
        metadata: JsonObject,
    ) -> EntityMention:
        mention = EntityMention(
            investigation_id=investigation_id,
            document_id=document_id,
            entity_type=entity_type,
            surface_form=surface_form,
            normalized_form=normalized_form,
            start_offset=start_offset,
            end_offset=end_offset,
            chunk_index=chunk_index,
            extraction_method=extraction_method,
            confidence=confidence,
            fingerprint=fingerprint,
            metadata_=metadata,
        )
        self.session.add(mention)
        await self.session.flush()
        return mention

    async def list_by_investigation(
        self, investigation_id: UUID, *, limit: int, offset: int
    ) -> list[EntityMention]:
        result = await self.session.scalars(
            select(EntityMention)
            .where(EntityMention.investigation_id == investigation_id)
            .order_by(EntityMention.created_at.desc(), EntityMention.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result)

    async def list_entities_by_investigation(
        self, investigation_id: UUID, *, limit: int, offset: int
    ) -> list[object]:
        from tracelink.domain.models import Entity

        result = await self.session.scalars(
            select(Entity)
            .join(EntityMention, EntityMention.entity_id == Entity.id)
            .options(selectinload(Entity.aliases))
            .where(EntityMention.investigation_id == investigation_id)
            .distinct()
            .order_by(Entity.created_at.desc(), Entity.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result)


class EntityResolutionCandidateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self,
        *,
        investigation_id: UUID,
        mention_id: UUID,
        candidate_entity_id: UUID,
        score: float,
        status: EntityResolutionCandidateStatus,
        signals: JsonObject,
    ) -> None:
        statement = insert(EntityResolutionCandidate).values(
            investigation_id=investigation_id,
            mention_id=mention_id,
            candidate_entity_id=candidate_entity_id,
            score=score,
            status=status,
            signals=signals,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_resolution_candidate_mention_entity",
            set_={
                "score": statement.excluded.score,
                "status": statement.excluded.status,
                "signals": statement.excluded.signals,
            },
        )
        await self.session.execute(statement)

    async def list_by_investigation(
        self, investigation_id: UUID, *, limit: int, offset: int
    ) -> list[EntityResolutionCandidate]:
        result = await self.session.scalars(
            select(EntityResolutionCandidate)
            .where(EntityResolutionCandidate.investigation_id == investigation_id)
            .order_by(
                EntityResolutionCandidate.created_at.desc(), EntityResolutionCandidate.id.desc()
            )
            .limit(limit)
            .offset(offset)
        )
        return list(result)
