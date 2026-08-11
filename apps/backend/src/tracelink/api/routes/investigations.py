import asyncio
from typing import Annotated, Literal, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tracelink.api.routes.relationships import relationship_read
from tracelink.api.routes.workspace import candidate_read, source_summary
from tracelink.api.schemas.entities import (
    EntityMentionDetailRead,
    EntityRead,
    EntityResolutionCandidateDetailRead,
    InvestigationEntityRead,
)
from tracelink.api.schemas.investigations import (
    InvestigationCreate,
    InvestigationProgressRead,
    InvestigationRead,
    InvestigationSummaryRead,
)
from tracelink.api.schemas.relationships import RelationshipCandidateRead, RelationshipRead
from tracelink.api.schemas.research_tasks import ResearchTaskRead
from tracelink.api.schemas.sources import UrlIngestionCreate
from tracelink.connectors.errors import (
    ConnectorError,
    ConnectorFetchError,
    ConnectorRateLimitError,
    ConnectorTimeoutError,
    ResponseTooLargeError,
    UnsafeUrlError,
    UnsupportedContentTypeError,
)
from tracelink.connectors.models import ConnectorContext, ResearchTaskResult
from tracelink.connectors.registry import ConnectorRegistry, get_connector_registry
from tracelink.core.config import get_settings
from tracelink.domain.enums import (
    AssertionStatus,
    EntityResolutionCandidateStatus,
    EntityType,
    FakeResearchMode,
    RelationshipCandidateStatus,
    RelationshipType,
)
from tracelink.domain.models import (
    Document,
    Entity,
    EntityMention,
    EntityResolutionCandidate,
    RelationshipCandidate,
    Source,
)
from tracelink.infrastructure.database import get_session
from tracelink.jobs.dispatcher import (
    DispatchError,
    ResearchTaskDispatcher,
    get_research_task_dispatcher,
)
from tracelink.repositories.investigations import InvestigationRepository
from tracelink.repositories.relationships import RelationshipRepository
from tracelink.services.errors import DomainConflictError, DomainNotFoundError
from tracelink.services.investigation_workflow import InvestigationWorkflowService
from tracelink.services.research_artifacts import ResearchArtifactService
from tracelink.services.workspace import investigation_summaries

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]
Dispatcher = Annotated[ResearchTaskDispatcher, Depends(get_research_task_dispatcher)]
Connectors = Annotated[ConnectorRegistry, Depends(get_connector_registry)]


def raise_workflow_http_error(exc: ValueError) -> NoReturn:
    if isinstance(exc, DomainNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, DomainConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    raise exc


def raise_connector_http_error(exc: ConnectorError) -> NoReturn:
    if isinstance(exc, UnsafeUrlError):
        status_code = status.HTTP_400_BAD_REQUEST
    elif isinstance(exc, UnsupportedContentTypeError):
        status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    elif isinstance(exc, ResponseTooLargeError):
        status_code = status.HTTP_413_CONTENT_TOO_LARGE
    elif isinstance(exc, ConnectorRateLimitError):
        status_code = status.HTTP_429_TOO_MANY_REQUESTS
    elif isinstance(exc, ConnectorTimeoutError):
        status_code = status.HTTP_504_GATEWAY_TIMEOUT
    elif isinstance(exc, ConnectorFetchError):
        status_code = status.HTTP_502_BAD_GATEWAY
    else:
        status_code = status.HTTP_400_BAD_REQUEST
    raise HTTPException(status_code=status_code, detail=exc.public_message) from exc


@router.post("", response_model=InvestigationRead, status_code=status.HTTP_201_CREATED)
async def create_investigation(payload: InvestigationCreate, session: Session) -> object:
    return await InvestigationRepository(session).create(payload.title, payload.original_query)


@router.get("", response_model=list[InvestigationSummaryRead])
async def list_investigations(
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> object:
    items = await InvestigationRepository(session).list(limit=limit, offset=offset)
    return await investigation_summaries(session, items)


@router.get("/{investigation_id}", response_model=InvestigationSummaryRead)
async def get_investigation(investigation_id: UUID, session: Session) -> object:
    investigation = await InvestigationRepository(session).get_by_id(investigation_id)
    if investigation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="investigation not found")
    return (await investigation_summaries(session, [investigation]))[0]


@router.post(
    "/{investigation_id}/sources/url",
    response_model=ResearchTaskResult,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_investigation_url(
    investigation_id: UUID,
    payload: UrlIngestionCreate,
    session: Session,
    connectors: Connectors,
) -> object:
    if await InvestigationRepository(session).get_by_id(investigation_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="investigation not found")
    await session.commit()
    connector = connectors.get_connector("url_ingestion")
    try:
        output = await connector.execute(
            payload.url,
            ConnectorContext(investigation_id=investigation_id),
        )
    except ConnectorError as exc:
        raise_connector_http_error(exc)
    if await InvestigationRepository(session).get_by_id(investigation_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="investigation not found")
    result = await ResearchArtifactService(session).persist(investigation_id, output)
    await session.commit()
    from tracelink.jobs.entities import process_document_entities

    for document_id in result.document_ids:
        await asyncio.to_thread(
            process_document_entities.apply_async,
            args=[str(investigation_id), str(document_id)],
        )
    return result


@router.post(
    "/{investigation_id}/start",
    response_model=InvestigationRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_investigation(
    investigation_id: UUID, session: Session, dispatcher: Dispatcher
) -> object:
    settings = get_settings()
    try:
        result = await InvestigationWorkflowService(session, settings).start(investigation_id)
        await session.commit()
        await session.refresh(result.investigation)
        response = InvestigationRead.model_validate(result.investigation)
    except (DomainNotFoundError, DomainConflictError) as exc:
        raise_workflow_http_error(exc)
    try:
        for research_task_id in result.pending_task_ids:
            await dispatcher.dispatch(
                research_task_id,
                mode=(
                    FakeResearchMode(settings.fake_research_mode)
                    if settings.fake_research_mode
                    else None
                ),
            )
    except DispatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="research tasks could not be queued; retry start",
        ) from exc
    return response


@router.post("/{investigation_id}/cancel", response_model=InvestigationRead)
async def cancel_investigation(investigation_id: UUID, session: Session) -> object:
    try:
        investigation = await InvestigationWorkflowService(session, get_settings()).cancel(
            investigation_id
        )
        await session.commit()
        await session.refresh(investigation)
        return InvestigationRead.model_validate(investigation)
    except (DomainNotFoundError, DomainConflictError) as exc:
        raise_workflow_http_error(exc)


@router.get("/{investigation_id}/tasks", response_model=list[ResearchTaskRead])
async def list_research_tasks(investigation_id: UUID, session: Session) -> object:
    try:
        return await InvestigationWorkflowService(session, get_settings()).list_tasks(
            investigation_id
        )
    except DomainNotFoundError as exc:
        raise_workflow_http_error(exc)


@router.get("/{investigation_id}/progress", response_model=InvestigationProgressRead)
async def get_investigation_progress(investigation_id: UUID, session: Session) -> object:
    try:
        return await InvestigationWorkflowService(session, get_settings()).progress(
            investigation_id
        )
    except DomainNotFoundError as exc:
        raise_workflow_http_error(exc)


async def _require_investigation(investigation_id: UUID, session: AsyncSession) -> None:
    if await InvestigationRepository(session).get_by_id(investigation_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="investigation not found")


@router.get("/{investigation_id}/entities", response_model=list[InvestigationEntityRead])
async def list_investigation_entities(
    investigation_id: UUID,
    session: Session,
    entity_type: EntityType | None = None,
    q: str | None = None,
    sort: Literal["recent", "mention_count"] = "recent",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> object:
    await _require_investigation(investigation_id, session)
    count = func.count(EntityMention.id)
    statement = (
        select(Entity, count.label("mention_count"))
        .join(EntityMention, EntityMention.entity_id == Entity.id)
        .options(selectinload(Entity.aliases))
        .where(EntityMention.investigation_id == investigation_id)
        .group_by(Entity.id)
    )
    if entity_type:
        statement = statement.where(Entity.type == entity_type)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(Entity.canonical_name.ilike(pattern), Entity.normalized_name.ilike(pattern))
        )
    ordering = (
        (count.desc(), Entity.canonical_name, Entity.id)
        if sort == "mention_count"
        else (Entity.created_at.desc(), Entity.id.desc())
    )
    rows = (await session.execute(statement.order_by(*ordering).limit(limit).offset(offset))).all()
    return [
        InvestigationEntityRead(
            **EntityRead.model_validate(entity).model_dump(), mention_count=int(mention_count)
        )
        for entity, mention_count in rows
    ]


@router.get("/{investigation_id}/entity-mentions", response_model=list[EntityMentionDetailRead])
async def list_investigation_entity_mentions(
    investigation_id: UUID,
    session: Session,
    entity_id: UUID | None = None,
    document_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> object:
    await _require_investigation(investigation_id, session)
    statement = (
        select(EntityMention, Document, Source)
        .join(Document, Document.id == EntityMention.document_id)
        .join(Source, Source.id == Document.source_id)
        .where(EntityMention.investigation_id == investigation_id)
    )
    if entity_id:
        statement = statement.where(EntityMention.entity_id == entity_id)
    if document_id:
        statement = statement.where(EntityMention.document_id == document_id)
    rows = (
        await session.execute(
            statement.order_by(EntityMention.created_at.desc(), EntityMention.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    output: list[EntityMentionDetailRead] = []
    for mention, document, source in rows:
        start = max((mention.start_offset or 0) - 120, 0)
        end = min((mention.end_offset or start) + 180, len(document.raw_text))
        output.append(
            EntityMentionDetailRead(
                id=mention.id,
                investigation_id=mention.investigation_id,
                document_id=mention.document_id,
                entity_id=mention.entity_id,
                entity_type=mention.entity_type,
                surface_form=mention.surface_form,
                normalized_form=mention.normalized_form,
                start_offset=mention.start_offset,
                end_offset=mention.end_offset,
                chunk_index=mention.chunk_index,
                extraction_method=mention.extraction_method,
                confidence=mention.confidence,
                metadata=mention.metadata_,
                created_at=mention.created_at,
                source=source_summary(source),
                document_title=source.title,
                context_preview=document.raw_text[start:end],
            )
        )
    return output


@router.get(
    "/{investigation_id}/resolution-candidates",
    response_model=list[EntityResolutionCandidateDetailRead],
)
async def list_investigation_resolution_candidates(
    investigation_id: UUID,
    session: Session,
    candidate_status: EntityResolutionCandidateStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> object:
    await _require_investigation(investigation_id, session)
    statement = (
        select(EntityResolutionCandidate, EntityMention, Document, Source)
        .join(EntityMention, EntityMention.id == EntityResolutionCandidate.mention_id)
        .join(Document, Document.id == EntityMention.document_id)
        .join(Source, Source.id == Document.source_id)
        .options(
            selectinload(EntityResolutionCandidate.candidate_entity).selectinload(Entity.aliases),
            selectinload(EntityResolutionCandidate.mention)
            .selectinload(EntityMention.entity)
            .selectinload(Entity.aliases),
        )
        .where(EntityResolutionCandidate.investigation_id == investigation_id)
    )
    if candidate_status:
        statement = statement.where(EntityResolutionCandidate.status == candidate_status)
    rows = (
        await session.execute(
            statement.order_by(
                EntityResolutionCandidate.created_at.desc(), EntityResolutionCandidate.id.desc()
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    output: list[EntityResolutionCandidateDetailRead] = []
    for candidate, mention, document, source in rows:
        start = max((mention.start_offset or 0) - 120, 0)
        end = min((mention.end_offset or start) + 180, len(document.raw_text))
        mention_read = EntityMentionDetailRead(
            id=mention.id,
            investigation_id=mention.investigation_id,
            document_id=mention.document_id,
            entity_id=mention.entity_id,
            entity_type=mention.entity_type,
            surface_form=mention.surface_form,
            normalized_form=mention.normalized_form,
            start_offset=mention.start_offset,
            end_offset=mention.end_offset,
            chunk_index=mention.chunk_index,
            extraction_method=mention.extraction_method,
            confidence=mention.confidence,
            metadata=mention.metadata_,
            created_at=mention.created_at,
            source=source_summary(source),
            document_title=source.title,
            context_preview=document.raw_text[start:end],
        )
        output.append(
            EntityResolutionCandidateDetailRead(
                id=candidate.id,
                investigation_id=candidate.investigation_id,
                mention_id=candidate.mention_id,
                candidate_entity_id=candidate.candidate_entity_id,
                score=candidate.score,
                status=candidate.status,
                signals=candidate.signals,
                created_at=candidate.created_at,
                reviewed_at=candidate.reviewed_at,
                mention=mention_read,
                provisional_entity=(
                    EntityRead.model_validate(mention.entity) if mention.entity else None
                ),
                candidate_entity=EntityRead.model_validate(candidate.candidate_entity),
            )
        )
    return output


@router.get("/{investigation_id}/relationships", response_model=list[RelationshipRead])
async def list_investigation_relationships(
    investigation_id: UUID,
    session: Session,
    relationship_type: RelationshipType | None = None,
    relationship_status: AssertionStatus | None = None,
    entity_id: UUID | None = None,
    sort: Literal["recent", "evidence_count", "confidence"] = "recent",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RelationshipRead]:
    await _require_investigation(investigation_id, session)
    items = await RelationshipRepository(session).list_by_investigation(
        investigation_id,
        limit=limit,
        offset=offset,
        relationship_type=relationship_type,
        relationship_status=relationship_status,
        entity_id=entity_id,
        sort=sort,
    )
    return [relationship_read(relationship, count) for relationship, count in items]


@router.get(
    "/{investigation_id}/relationship-candidates",
    response_model=list[RelationshipCandidateRead],
)
async def list_investigation_relationship_candidates(
    investigation_id: UUID,
    session: Session,
    candidate_status: RelationshipCandidateStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RelationshipCandidateRead]:
    await _require_investigation(investigation_id, session)
    statement = (
        select(RelationshipCandidate, Source)
        .join(Document, Document.id == RelationshipCandidate.document_id)
        .join(Source, Source.id == Document.source_id)
        .options(
            selectinload(RelationshipCandidate.source_entity),
            selectinload(RelationshipCandidate.target_entity),
        )
        .where(RelationshipCandidate.investigation_id == investigation_id)
    )
    if candidate_status:
        statement = statement.where(RelationshipCandidate.status == candidate_status)
    rows = (
        await session.execute(
            statement.order_by(
                RelationshipCandidate.created_at.desc(), RelationshipCandidate.id.desc()
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [candidate_read(item, source) for item, source in rows]
