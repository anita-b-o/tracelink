from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.domain.models import Evidence


class EvidenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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
        evidence = Evidence(
            investigation_id=investigation_id,
            source_id=source_id,
            document_id=document_id,
            relationship_id=relationship_id,
            entity_id=entity_id,
            excerpt=excerpt,
            locator=locator,
            confidence=confidence,
        )
        self.session.add(evidence)
        await self.session.flush()
        await self.session.refresh(evidence)
        return evidence

    async def get_by_id(self, evidence_id: UUID) -> Evidence | None:
        return await self.session.get(Evidence, evidence_id)

    async def list(
        self,
        *,
        investigation_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Evidence]:
        statement = select(Evidence)
        if investigation_id is not None:
            statement = statement.where(Evidence.investigation_id == investigation_id)
        result = await self.session.scalars(
            statement.order_by(Evidence.created_at.desc(), Evidence.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result)
