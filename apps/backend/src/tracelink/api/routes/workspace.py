from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.base import Executable

from tracelink.api.routes.relationships import evidence_read, relationship_read
from tracelink.api.schemas.relationships import (
    GraphEdgeRead,
    GraphNodeRead,
    InvestigationGraphRead,
    RelationshipCandidateRead,
    RelationshipDetailRead,
    RelationshipEvidenceRead,
)
from tracelink.api.schemas.sources import (
    DocumentDetailRead,
    DocumentSummaryRead,
    SourceSummaryRead,
)
from tracelink.domain.enums import (
    AssertionStatus,
    EntityType,
    RelationshipType,
)
from tracelink.domain.models import (
    Document,
    Entity,
    EntityMention,
    Evidence,
    Investigation,
    InvestigationArtifact,
    Relationship,
    RelationshipCandidate,
    RetrievalChunk,
    Source,
)
from tracelink.infrastructure.database import get_session

investigation_router = APIRouter()
resource_router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


async def require_investigation(session: AsyncSession, investigation_id: UUID) -> None:
    if await session.get(Investigation, investigation_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="investigation not found")


def source_summary(source: Source, document_count: int = 0) -> SourceSummaryRead:
    return SourceSummaryRead(
        id=source.id,
        type=source.type,
        publisher=source.publisher,
        url=source.url,
        title=source.title,
        published_at=source.published_at,
        retrieved_at=source.retrieved_at,
        document_count=document_count,
    )


def candidate_read(
    item: RelationshipCandidate, source: Source | None = None
) -> RelationshipCandidateRead:
    raw_codes = item.signals.get("reason_codes", [])
    reason_codes = [str(value) for value in raw_codes] if isinstance(raw_codes, list) else []
    return RelationshipCandidateRead(
        id=item.id,
        investigation_id=item.investigation_id,
        document_id=item.document_id,
        source_entity=item.source_entity,
        target_entity=item.target_entity,
        type=item.type,
        claim_kind=item.claim_kind,
        confidence=item.confidence,
        score=item.score,
        status=item.status,
        extraction_method=item.extraction_method,
        signals=item.signals,
        temporal_start=item.temporal_start,
        temporal_end=item.temporal_end,
        evidence_preview=item.supporting_text,
        reason_codes=reason_codes,
        source=source_summary(source) if source else None,
        created_at=item.created_at,
        reviewed_at=item.reviewed_at,
    )


@investigation_router.get("/{investigation_id}/sources", response_model=list[SourceSummaryRead])
async def list_investigation_sources(
    investigation_id: UUID,
    session: Session,
    q: str | None = None,
    source_type: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 26,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SourceSummaryRead]:
    await require_investigation(session, investigation_id)
    statement = (
        select(Source, func.count(func.distinct(Document.id)))
        .join(InvestigationArtifact, InvestigationArtifact.source_id == Source.id)
        .outerjoin(Document, Document.source_id == Source.id)
        .where(InvestigationArtifact.investigation_id == investigation_id)
        .group_by(Source.id)
    )
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                Source.title.ilike(pattern),
                Source.publisher.ilike(pattern),
                Source.url.ilike(pattern),
            )
        )
    if source_type:
        statement = statement.where(Source.type == source_type)
    rows = (
        await session.execute(
            statement.order_by(Source.retrieved_at.desc(), Source.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [source_summary(source, int(count)) for source, count in rows]


async def document_summaries(
    session: AsyncSession, investigation_id: UUID, statement: Executable
) -> list[DocumentSummaryRead]:
    rows = (await session.execute(statement)).all()
    output: list[DocumentSummaryRead] = []
    for document, source, chunks, mentions, evidence in rows:
        output.append(
            DocumentSummaryRead(
                id=document.id,
                source=source_summary(source),
                mime_type=document.mime_type,
                content_hash=document.content_hash,
                text_preview=document.raw_text[:300],
                content_length=len(document.raw_text),
                chunk_count=int(chunks),
                mention_count=int(mentions),
                evidence_count=int(evidence),
                created_at=document.created_at,
            )
        )
    return output


@investigation_router.get("/{investigation_id}/documents", response_model=list[DocumentSummaryRead])
async def list_investigation_documents(
    investigation_id: UUID,
    session: Session,
    q: str | None = None,
    mime_type: str | None = None,
    source_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 26,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DocumentSummaryRead]:
    await require_investigation(session, investigation_id)
    chunk_count = (
        select(func.count(RetrievalChunk.id))
        .where(RetrievalChunk.document_id == Document.id)
        .correlate(Document)
        .scalar_subquery()
    )
    mention_count = (
        select(func.count(EntityMention.id))
        .where(
            EntityMention.document_id == Document.id,
            EntityMention.investigation_id == investigation_id,
        )
        .correlate(Document)
        .scalar_subquery()
    )
    evidence_count = (
        select(func.count(Evidence.id))
        .where(
            Evidence.document_id == Document.id,
            Evidence.investigation_id == investigation_id,
        )
        .correlate(Document)
        .scalar_subquery()
    )
    statement = (
        select(Document, Source, chunk_count, mention_count, evidence_count)
        .join(Source, Source.id == Document.source_id)
        .join(InvestigationArtifact, InvestigationArtifact.document_id == Document.id)
        .where(InvestigationArtifact.investigation_id == investigation_id)
    )
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(Source.title.ilike(pattern), Document.raw_text.ilike(pattern))
        )
    if mime_type:
        statement = statement.where(Document.mime_type == mime_type)
    if source_id:
        statement = statement.where(Document.source_id == source_id)
    statement = (
        statement.order_by(Document.created_at.desc(), Document.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return await document_summaries(session, investigation_id, statement)


@resource_router.get("/sources/{source_id}", response_model=SourceSummaryRead)
async def get_source(source_id: UUID, session: Session) -> SourceSummaryRead:
    row = (
        await session.execute(
            select(Source, func.count(Document.id))
            .outerjoin(Document, Document.source_id == Source.id)
            .where(Source.id == source_id)
            .group_by(Source.id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="source not found")
    return source_summary(row[0], int(row[1]))


@resource_router.get("/documents/{document_id}", response_model=DocumentDetailRead)
async def get_document(
    document_id: UUID,
    session: Session,
    content_offset: Annotated[int, Query(ge=0)] = 0,
    content_limit: Annotated[int, Query(ge=1, le=5000)] = 2000,
) -> DocumentDetailRead:
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    source = await session.get(Source, document.source_id)
    assert source is not None
    investigation_id = await session.scalar(
        select(InvestigationArtifact.investigation_id)
        .where(InvestigationArtifact.document_id == document_id)
        .order_by(InvestigationArtifact.created_at)
        .limit(1)
    )
    chunks = await session.scalar(
        select(func.count(RetrievalChunk.id)).where(RetrievalChunk.document_id == document_id)
    )
    mentions = await session.scalar(
        select(func.count(EntityMention.id)).where(EntityMention.document_id == document_id)
    )
    evidence = await session.scalar(
        select(func.count(Evidence.id)).where(Evidence.document_id == document_id)
    )
    _ = investigation_id
    content = document.raw_text[content_offset : content_offset + content_limit]
    return DocumentDetailRead(
        id=document.id,
        source=source_summary(source),
        mime_type=document.mime_type,
        content_hash=document.content_hash,
        text_preview=document.raw_text[:300],
        content_length=len(document.raw_text),
        chunk_count=int(chunks or 0),
        mention_count=int(mentions or 0),
        evidence_count=int(evidence or 0),
        created_at=document.created_at,
        content_offset=content_offset,
        content=content,
        has_more=content_offset + len(content) < len(document.raw_text),
    )


@resource_router.get("/evidence/{evidence_id}", response_model=RelationshipEvidenceRead)
async def get_evidence(evidence_id: UUID, session: Session) -> RelationshipEvidenceRead:
    evidence = await session.get(Evidence, evidence_id)
    if evidence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="evidence not found")
    return await evidence_read(session, evidence)


@investigation_router.get(
    "/{investigation_id}/entities/{entity_id}/evidence",
    response_model=list[RelationshipEvidenceRead],
)
async def list_entity_evidence(
    investigation_id: UUID,
    entity_id: UUID,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 26,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RelationshipEvidenceRead]:
    await require_investigation(session, investigation_id)
    items = list(
        await session.scalars(
            select(Evidence)
            .where(Evidence.investigation_id == investigation_id, Evidence.entity_id == entity_id)
            .order_by(Evidence.created_at.desc(), Evidence.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return [await evidence_read(session, item) for item in items]


@investigation_router.get(
    "/{investigation_id}/relationships/{relationship_id}",
    response_model=RelationshipDetailRead,
)
async def get_investigation_relationship(
    investigation_id: UUID, relationship_id: UUID, session: Session
) -> RelationshipDetailRead:
    await require_investigation(session, investigation_id)
    relationship = await session.scalar(
        select(Relationship)
        .options(
            selectinload(Relationship.source_entity),
            selectinload(Relationship.target_entity),
        )
        .join(Evidence, Evidence.relationship_id == Relationship.id)
        .where(Relationship.id == relationship_id, Evidence.investigation_id == investigation_id)
        .distinct()
    )
    if relationship is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="relationship not found")
    evidence_items = list(
        await session.scalars(
            select(Evidence)
            .where(
                Evidence.investigation_id == investigation_id,
                Evidence.relationship_id == relationship_id,
            )
            .order_by(Evidence.created_at.desc())
            .limit(100)
        )
    )
    candidate_rows = (
        await session.execute(
            select(RelationshipCandidate, Source)
            .join(Document, Document.id == RelationshipCandidate.document_id)
            .join(Source, Source.id == Document.source_id)
            .options(
                selectinload(RelationshipCandidate.source_entity),
                selectinload(RelationshipCandidate.target_entity),
            )
            .where(
                RelationshipCandidate.investigation_id == investigation_id,
                RelationshipCandidate.source_entity_id == relationship.source_entity_id,
                RelationshipCandidate.target_entity_id == relationship.target_entity_id,
                RelationshipCandidate.type == relationship.type,
            )
            .order_by(RelationshipCandidate.created_at.desc())
            .limit(100)
        )
    ).all()
    base = relationship_read(relationship, len(evidence_items))
    return RelationshipDetailRead(
        **base.model_dump(),
        claims=[candidate_read(candidate, source) for candidate, source in candidate_rows],
        evidence=[await evidence_read(session, item) for item in evidence_items],
    )


@investigation_router.get("/{investigation_id}/graph", response_model=InvestigationGraphRead)
async def get_investigation_graph(
    investigation_id: UUID,
    session: Session,
    entity_type: EntityType | None = None,
    relationship_type: RelationshipType | None = None,
    relationship_status: AssertionStatus | None = None,
    q: str | None = None,
    focus_entity_id: UUID | None = None,
    max_nodes: Annotated[int, Query(ge=1, le=250)] = 250,
) -> InvestigationGraphRead:
    await require_investigation(session, investigation_id)
    mentioned_entity_ids = select(EntityMention.entity_id).where(
        EntityMention.investigation_id == investigation_id,
        EntityMention.entity_id.is_not(None),
    )
    relationship_source_ids = (
        select(Relationship.source_entity_id)
        .join(Evidence, Evidence.relationship_id == Relationship.id)
        .where(Evidence.investigation_id == investigation_id)
    )
    relationship_target_ids = (
        select(Relationship.target_entity_id)
        .join(Evidence, Evidence.relationship_id == Relationship.id)
        .where(Evidence.investigation_id == investigation_id)
    )
    investigation_entity_ids = mentioned_entity_ids.union(
        relationship_source_ids, relationship_target_ids
    )
    mention_count = (
        select(func.count(EntityMention.id))
        .where(
            EntityMention.investigation_id == investigation_id,
            EntityMention.entity_id == Entity.id,
        )
        .correlate(Entity)
        .scalar_subquery()
    )
    entity_statement = select(Entity, mention_count.label("mention_count")).where(
        Entity.id.in_(investigation_entity_ids),
        Entity.type != EntityType.DOCUMENT,
    )
    if entity_type:
        entity_statement = entity_statement.where(Entity.type == entity_type)
    if q and q.strip():
        entity_statement = entity_statement.where(Entity.canonical_name.ilike(f"%{q.strip()}%"))
    if focus_entity_id:
        neighbor_ids = (
            select(Relationship.source_entity_id)
            .join(Evidence, Evidence.relationship_id == Relationship.id)
            .where(
                Evidence.investigation_id == investigation_id,
                Relationship.target_entity_id == focus_entity_id,
            )
            .union(
                select(Relationship.target_entity_id)
                .join(Evidence, Evidence.relationship_id == Relationship.id)
                .where(
                    Evidence.investigation_id == investigation_id,
                    Relationship.source_entity_id == focus_entity_id,
                )
            )
        )
        entity_statement = entity_statement.where(
            or_(Entity.id == focus_entity_id, Entity.id.in_(neighbor_ids))
        )
    total_nodes = int(
        await session.scalar(select(func.count()).select_from(entity_statement.subquery())) or 0
    )
    entity_rows = (
        await session.execute(
            entity_statement.order_by(mention_count.desc(), Entity.canonical_name, Entity.id).limit(
                max_nodes
            )
        )
    ).all()
    node_ids = {entity.id for entity, _ in entity_rows}
    edge_rows: list[tuple[Relationship, int]] = []
    if node_ids:
        edge_statement = (
            select(Relationship, func.count(Evidence.id))
            .join(Evidence, Evidence.relationship_id == Relationship.id)
            .where(
                Evidence.investigation_id == investigation_id,
                Relationship.source_entity_id.in_(node_ids),
                Relationship.target_entity_id.in_(node_ids),
                Relationship.type != RelationshipType.MENTIONED_IN,
            )
            .group_by(Relationship.id)
        )
        if relationship_type:
            edge_statement = edge_statement.where(Relationship.type == relationship_type)
        if relationship_status:
            edge_statement = edge_statement.where(Relationship.status == relationship_status)
        edge_rows = [
            (relationship, int(count))
            for relationship, count in (
                await session.execute(
                    edge_statement.order_by(Relationship.confidence.desc(), Relationship.id).limit(
                        1000
                    )
                )
            ).all()
        ]
    return InvestigationGraphRead(
        nodes=[
            GraphNodeRead(
                id=entity.id,
                type=entity.type,
                label=entity.canonical_name,
                mention_count=int(count),
            )
            for entity, count in entity_rows
        ],
        edges=[
            GraphEdgeRead(
                id=relationship.id,
                source=relationship.source_entity_id,
                target=relationship.target_entity_id,
                type=relationship.type,
                status=relationship.status,
                confidence=relationship.confidence,
                evidence_count=count,
            )
            for relationship, count in edge_rows
        ],
        truncated=total_nodes > max_nodes,
        total_nodes=total_nodes,
    )
