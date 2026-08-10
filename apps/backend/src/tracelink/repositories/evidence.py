from __future__ import annotations

import builtins
import hashlib
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.domain.enums import EvidenceType
from tracelink.domain.models import Evidence, JsonObject


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
        start_offset: int | None = None,
        end_offset: int | None = None,
        evidence_type: EvidenceType = EvidenceType.SUPPORTING,
        metadata: JsonObject | None = None,
        fingerprint: str | None = None,
    ) -> Evidence:
        if fingerprint is None:
            identity = (
                f"{investigation_id}|{source_id}|{document_id}|{relationship_id}|{entity_id}|"
                f"{start_offset}|{end_offset}|{locator}|{excerpt or ''}|{evidence_type.value}"
            )
            fingerprint = hashlib.sha256(identity.encode()).hexdigest()
        evidence = Evidence(
            investigation_id=investigation_id,
            source_id=source_id,
            document_id=document_id,
            relationship_id=relationship_id,
            entity_id=entity_id,
            excerpt=excerpt,
            locator=locator,
            start_offset=start_offset,
            end_offset=end_offset,
            evidence_type=evidence_type,
            metadata_=metadata or {},
            fingerprint=fingerprint,
            confidence=confidence,
        )
        self.session.add(evidence)
        await self.session.flush()
        await self.session.refresh(evidence)
        return evidence

    async def upsert(
        self,
        *,
        investigation_id: UUID,
        source_id: UUID,
        document_id: UUID,
        relationship_id: UUID,
        confidence: float,
        start_offset: int | None,
        end_offset: int | None,
        locator: str | None,
        evidence_type: EvidenceType,
        metadata: JsonObject,
        fingerprint: str,
    ) -> Evidence:
        insert_statement = insert(Evidence).values(
            investigation_id=investigation_id,
            source_id=source_id,
            document_id=document_id,
            relationship_id=relationship_id,
            confidence=confidence,
            start_offset=start_offset,
            end_offset=end_offset,
            locator=locator,
            evidence_type=evidence_type,
            metadata_=metadata,
            fingerprint=fingerprint,
        )
        statement = insert_statement.on_conflict_do_update(
            constraint="uq_evidence_investigation_fingerprint",
            set_={
                "confidence": insert_statement.excluded.confidence,
                "metadata": insert_statement.excluded.metadata,
            },
        ).returning(Evidence)
        return (await self.session.scalars(statement)).one()

    async def get_by_id(self, evidence_id: UUID) -> Evidence | None:
        return await self.session.get(Evidence, evidence_id)

    async def list(
        self,
        *,
        investigation_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> builtins.list[Evidence]:
        statement = select(Evidence)
        if investigation_id is not None:
            statement = statement.where(Evidence.investigation_id == investigation_id)
        result = await self.session.scalars(
            statement.order_by(Evidence.created_at.desc(), Evidence.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result)

    async def list_by_relationship(
        self, relationship_id: UUID, *, limit: int, offset: int
    ) -> builtins.list[Evidence]:
        result = await self.session.scalars(
            select(Evidence)
            .where(Evidence.relationship_id == relationship_id)
            .order_by(Evidence.created_at.desc(), Evidence.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result)
