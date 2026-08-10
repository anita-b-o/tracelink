from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.domain.models import InvestigationArtifact


class InvestigationArtifactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def associate(
        self, *, investigation_id: UUID, source_id: UUID, document_id: UUID | None
    ) -> None:
        statement = (
            insert(InvestigationArtifact)
            .values(
                investigation_id=investigation_id,
                source_id=source_id,
                document_id=document_id,
            )
            .on_conflict_do_nothing(constraint="uq_investigation_artifact")
        )
        await self.session.execute(statement)

    async def has_document(self, investigation_id: UUID, document_id: UUID) -> bool:
        return (
            await self.session.scalar(
                select(InvestigationArtifact.id).where(
                    InvestigationArtifact.investigation_id == investigation_id,
                    InvestigationArtifact.document_id == document_id,
                )
            )
            is not None
        )

    async def list_document_ids(self, investigation_id: UUID) -> list[UUID]:
        result = await self.session.scalars(
            select(InvestigationArtifact.document_id)
            .where(
                InvestigationArtifact.investigation_id == investigation_id,
                InvestigationArtifact.document_id.is_not(None),
            )
            .distinct()
        )
        return [document_id for document_id in result if document_id is not None]
