from typing import NoReturn
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tracelink.domain.models import (
    Document,
    Entity,
    EntityMention,
    EntityResolutionCandidate,
    Evidence,
    Investigation,
    InvestigationArtifact,
    InvestigationReport,
    Relationship,
    RelationshipCandidate,
    ResearchTask,
    Source,
)


class AuthorizationService:
    def __init__(self, session: AsyncSession, user_id: UUID) -> None:
        self.session = session
        self.user_id = user_id

    @staticmethod
    def _missing() -> NoReturn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resource not found")

    async def investigation(self, resource_id: UUID) -> Investigation:
        item = await self.session.scalar(
            select(Investigation).where(
                Investigation.id == resource_id, Investigation.user_id == self.user_id
            )
        )
        if item is None:
            self._missing()
        return item

    async def research_task(self, resource_id: UUID) -> ResearchTask:
        item = await self.session.scalar(
            select(ResearchTask)
            .join(Investigation, Investigation.id == ResearchTask.investigation_id)
            .where(ResearchTask.id == resource_id, Investigation.user_id == self.user_id)
        )
        if item is None:
            self._missing()
        return item

    async def entity(self, resource_id: UUID) -> Entity:
        item = await self.session.scalar(
            select(Entity)
            .options(selectinload(Entity.aliases))
            .join(EntityMention, EntityMention.entity_id == Entity.id)
            .join(Investigation, Investigation.id == EntityMention.investigation_id)
            .where(Entity.id == resource_id, Investigation.user_id == self.user_id)
            .distinct()
        )
        if item is None:
            self._missing()
        return item

    async def relationship(self, resource_id: UUID) -> Relationship:
        item = await self.session.scalar(
            select(Relationship)
            .options(
                selectinload(Relationship.source_entity),
                selectinload(Relationship.target_entity),
            )
            .join(Evidence, Evidence.relationship_id == Relationship.id)
            .join(Investigation, Investigation.id == Evidence.investigation_id)
            .where(Relationship.id == resource_id, Investigation.user_id == self.user_id)
            .distinct()
        )
        if item is None:
            self._missing()
        return item

    async def source(self, resource_id: UUID) -> Source:
        item = await self.session.scalar(
            select(Source)
            .join(InvestigationArtifact, InvestigationArtifact.source_id == Source.id)
            .join(Investigation, Investigation.id == InvestigationArtifact.investigation_id)
            .where(Source.id == resource_id, Investigation.user_id == self.user_id)
            .distinct()
        )
        if item is None:
            self._missing()
        return item

    async def document(self, resource_id: UUID) -> Document:
        item = await self.session.scalar(
            select(Document)
            .join(InvestigationArtifact, InvestigationArtifact.document_id == Document.id)
            .join(Investigation, Investigation.id == InvestigationArtifact.investigation_id)
            .where(Document.id == resource_id, Investigation.user_id == self.user_id)
            .distinct()
        )
        if item is None:
            self._missing()
        return item

    async def evidence(self, resource_id: UUID) -> Evidence:
        item = await self.session.scalar(
            select(Evidence)
            .join(Investigation, Investigation.id == Evidence.investigation_id)
            .where(Evidence.id == resource_id, Investigation.user_id == self.user_id)
        )
        if item is None:
            self._missing()
        return item

    async def report(self, resource_id: UUID) -> InvestigationReport:
        item = await self.session.scalar(
            select(InvestigationReport)
            .join(Investigation, Investigation.id == InvestigationReport.investigation_id)
            .where(InvestigationReport.id == resource_id, Investigation.user_id == self.user_id)
        )
        if item is None:
            self._missing()
        return item

    async def entity_candidate(self, resource_id: UUID) -> EntityResolutionCandidate:
        item = await self.session.scalar(
            select(EntityResolutionCandidate)
            .join(Investigation, Investigation.id == EntityResolutionCandidate.investigation_id)
            .where(
                EntityResolutionCandidate.id == resource_id, Investigation.user_id == self.user_id
            )
        )
        if item is None:
            self._missing()
        return item

    async def relationship_candidate(self, resource_id: UUID) -> RelationshipCandidate:
        item = await self.session.scalar(
            select(RelationshipCandidate)
            .join(Investigation, Investigation.id == RelationshipCandidate.investigation_id)
            .where(RelationshipCandidate.id == resource_id, Investigation.user_id == self.user_id)
        )
        if item is None:
            self._missing()
        return item
