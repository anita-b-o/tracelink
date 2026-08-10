from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tracelink.domain.enums import (
    RelationshipCandidateStatus,
    RelationshipClaimKind,
    RelationshipType,
)
from tracelink.domain.models import JsonObject, RelationshipCandidate


class RelationshipCandidateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self,
        *,
        investigation_id: UUID,
        document_id: UUID,
        source_entity_id: UUID,
        target_entity_id: UUID,
        relationship_type: RelationshipType,
        claim_kind: RelationshipClaimKind,
        confidence: float,
        score: float,
        extraction_method: str,
        supporting_text: str | None,
        start_offset: int | None,
        end_offset: int | None,
        temporal_start: str | None,
        temporal_end: str | None,
        metadata: JsonObject,
        signals: JsonObject,
        status: RelationshipCandidateStatus,
        fingerprint: str,
    ) -> RelationshipCandidate:
        insert_statement = insert(RelationshipCandidate).values(
            investigation_id=investigation_id,
            document_id=document_id,
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            type=relationship_type,
            claim_kind=claim_kind,
            confidence=confidence,
            score=score,
            extraction_method=extraction_method,
            supporting_text=supporting_text,
            start_offset=start_offset,
            end_offset=end_offset,
            temporal_start=temporal_start,
            temporal_end=temporal_end,
            metadata_=metadata,
            signals=signals,
            status=status,
            fingerprint=fingerprint,
        )
        statement = insert_statement.on_conflict_do_update(
            constraint="uq_relationship_candidate_fingerprint",
            set_={
                "score": insert_statement.excluded.score,
                "status": insert_statement.excluded.status,
                "signals": insert_statement.excluded.signals,
                "metadata": insert_statement.excluded.metadata,
                "updated_at": insert_statement.excluded.updated_at,
            },
        ).returning(RelationshipCandidate)
        return (await self.session.scalars(statement)).one()

    async def list_by_investigation(
        self, investigation_id: UUID, *, limit: int, offset: int
    ) -> list[RelationshipCandidate]:
        result = await self.session.scalars(
            select(RelationshipCandidate)
            .options(
                selectinload(RelationshipCandidate.source_entity),
                selectinload(RelationshipCandidate.target_entity),
            )
            .where(RelationshipCandidate.investigation_id == investigation_id)
            .order_by(RelationshipCandidate.created_at.desc(), RelationshipCandidate.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result)

    async def list_claims(
        self,
        investigation_id: UUID,
        source_entity_id: UUID,
        target_entity_id: UUID,
        relationship_type: RelationshipType,
    ) -> list[RelationshipCandidate]:
        result = await self.session.scalars(
            select(RelationshipCandidate).where(
                RelationshipCandidate.investigation_id == investigation_id,
                RelationshipCandidate.source_entity_id == source_entity_id,
                RelationshipCandidate.target_entity_id == target_entity_id,
                RelationshipCandidate.type == relationship_type,
            )
        )
        return list(result)
