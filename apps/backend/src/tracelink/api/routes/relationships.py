from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.api.authorization import AuthorizationService
from tracelink.api.dependencies import CurrentUser
from tracelink.api.schemas.relationships import (
    RelationshipEntitySummary,
    RelationshipEvidenceRead,
    RelationshipRead,
)
from tracelink.domain.models import Document, Evidence, Investigation, Relationship, Source
from tracelink.infrastructure.database import get_session

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


def relationship_read(relationship: Relationship, evidence_count: int) -> RelationshipRead:
    return RelationshipRead(
        id=relationship.id,
        source_entity=RelationshipEntitySummary.model_validate(relationship.source_entity),
        target_entity=RelationshipEntitySummary.model_validate(relationship.target_entity),
        type=relationship.type,
        confidence=relationship.confidence,
        status=relationship.status,
        first_observed_at=relationship.first_observed_at,
        last_observed_at=relationship.last_observed_at,
        temporal_start=relationship.temporal_start,
        temporal_end=relationship.temporal_end,
        evidence_count=evidence_count,
    )


async def evidence_read(session: AsyncSession, evidence: Evidence) -> RelationshipEvidenceRead:
    preview = evidence.excerpt
    document_title = None
    if preview is None and evidence.document_id is not None:
        document = await session.get(Document, evidence.document_id)
        if document is not None:
            source_for_title = await session.get(Source, document.source_id)
            document_title = source_for_title.title if source_for_title else None
            if evidence.start_offset is not None and evidence.end_offset is not None:
                preview = document.raw_text[evidence.start_offset : evidence.end_offset]
            elif evidence.locator:
                preview = document.raw_text[:500]
    source = await session.get(Source, evidence.source_id)
    return RelationshipEvidenceRead(
        id=evidence.id,
        investigation_id=evidence.investigation_id,
        source_id=evidence.source_id,
        document_id=evidence.document_id,
        relationship_id=evidence.relationship_id,
        evidence_type=evidence.evidence_type,
        confidence=evidence.confidence,
        start_offset=evidence.start_offset,
        end_offset=evidence.end_offset,
        locator=evidence.locator,
        preview=preview[:500] if preview else None,
        source=(
            {
                "id": source.id,
                "type": source.type,
                "publisher": source.publisher,
                "url": source.url,
                "title": source.title,
                "published_at": source.published_at,
                "retrieved_at": source.retrieved_at,
                "document_count": 0,
            }
            if source
            else None
        ),
        document_title=document_title,
        metadata=evidence.metadata_,
        created_at=evidence.created_at,
    )


@router.get("/{relationship_id}", response_model=RelationshipRead)
async def get_relationship(
    relationship_id: UUID, session: Session, current_user: CurrentUser
) -> RelationshipRead:
    authorization = AuthorizationService(session, current_user.id)
    relationship = await authorization.relationship(relationship_id)
    evidence_count = int(
        await session.scalar(
            select(func.count(Evidence.id))
            .join(Investigation, Investigation.id == Evidence.investigation_id)
            .where(
                Evidence.relationship_id == relationship_id,
                Investigation.user_id == current_user.id,
            )
        )
        or 0
    )
    return relationship_read(relationship, evidence_count)


@router.get("/{relationship_id}/evidence", response_model=list[RelationshipEvidenceRead])
async def list_relationship_evidence(
    relationship_id: UUID,
    session: Session,
    current_user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> list[RelationshipEvidenceRead]:
    await AuthorizationService(session, current_user.id).relationship(relationship_id)
    items = list(
        await session.scalars(
            select(Evidence)
            .join(Investigation, Investigation.id == Evidence.investigation_id)
            .where(
                Evidence.relationship_id == relationship_id,
                Investigation.user_id == current_user.id,
            )
            .order_by(Evidence.created_at.desc(), Evidence.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return [await evidence_read(session, item) for item in items]
