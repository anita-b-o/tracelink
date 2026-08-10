from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.api.schemas.rag import (
    AskRequest,
    CitationRead,
    GroundedAnswerRead,
    InvestigationReportRead,
    InvestigationReportSummaryRead,
    ReportCreate,
    SearchHitRead,
    SearchRequest,
)
from tracelink.core.config import get_settings
from tracelink.domain.enums import InvestigationReportStatus
from tracelink.domain.rag import RetrievalFilters
from tracelink.infrastructure.database import get_session
from tracelink.jobs.dispatcher import (
    DispatchError,
    ReportDispatcher,
    get_report_dispatcher,
)
from tracelink.repositories.investigations import InvestigationRepository
from tracelink.repositories.reports import InvestigationReportRepository
from tracelink.services.citations import InvalidCitationError
from tracelink.services.embedding_providers import EmbeddingProviderError, get_embedding_provider
from tracelink.services.errors import DomainConflictError, DomainNotFoundError
from tracelink.services.grounded_answers import GroundedAnswerService
from tracelink.services.grounded_reports import InvestigationReportService
from tracelink.services.hybrid_retrieval import HybridRetriever
from tracelink.services.llm_providers import LLMProviderError, get_llm_provider

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]
Reports = Annotated[ReportDispatcher, Depends(get_report_dispatcher)]


async def _require_investigation(investigation_id: UUID, session: AsyncSession) -> None:
    if await InvestigationRepository(session).get_by_id(investigation_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="investigation not found")


def _retrieval_filters(payload: SearchRequest) -> RetrievalFilters:
    return RetrievalFilters(
        source_ids=tuple(payload.filters.source_ids),
        document_ids=tuple(payload.filters.document_ids),
        entity_ids=tuple(payload.filters.entity_ids),
        relationship_types=tuple(item.value for item in payload.filters.relationship_types),
        published_from=payload.filters.published_from,
        published_to=payload.filters.published_to,
    )


@router.post("/investigations/{investigation_id}/search", response_model=list[SearchHitRead])
async def search_investigation(
    investigation_id: UUID, payload: SearchRequest, session: Session
) -> object:
    await _require_investigation(investigation_id, session)
    settings = get_settings()
    try:
        hits = await HybridRetriever(session, settings, get_embedding_provider(settings)).search(
            investigation_id,
            payload.query,
            filters=_retrieval_filters(payload),
            top_k=payload.top_k,
        )
    except EmbeddingProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return [
        SearchHitRead(
            chunk_id=hit.chunk_id,
            document_id=hit.document_id,
            source_id=hit.source_id,
            chunk_index=hit.chunk_index,
            chunk_text=hit.chunk_text,
            start_offset=hit.start_offset,
            end_offset=hit.end_offset,
            source_url=hit.source_url,
            source_title=hit.source_title,
            published_at=hit.published_at,
            semantic_score=hit.semantic_score,
            lexical_score=hit.lexical_score,
            evidence_boost=hit.evidence_boost,
            combined_score=hit.combined_score,
            matched_entity_ids=list(hit.matched_entity_ids),
            matched_relationship_types=list(hit.matched_relationship_types),
        )
        for hit in hits
    ]


@router.post("/investigations/{investigation_id}/ask", response_model=GroundedAnswerRead)
async def ask_investigation(
    investigation_id: UUID, payload: AskRequest, session: Session
) -> object:
    await _require_investigation(investigation_id, session)
    settings = get_settings()
    try:
        embeddings = get_embedding_provider(settings)
        result = await GroundedAnswerService(
            session,
            settings,
            HybridRetriever(session, settings, embeddings),
            get_llm_provider(settings),
        ).answer(investigation_id, payload.question)
    except EmbeddingProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except (LLMProviderError, InvalidCitationError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return GroundedAnswerRead(
        answer=result.answer,
        abstained=result.abstained,
        confidence=result.confidence,
        claims=result.claims,
        citations=[CitationRead.model_validate(item) for item in result.citations],
        limitations=result.limitations,
        contradictions=result.contradictions,
    )


@router.post(
    "/investigations/{investigation_id}/reports",
    response_model=InvestigationReportSummaryRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_report(
    investigation_id: UUID,
    payload: ReportCreate,
    response: Response,
    session: Session,
    dispatcher: Reports,
) -> object:
    settings = get_settings()
    try:
        embeddings = get_embedding_provider(settings)
        service = InvestigationReportService(
            session,
            settings,
            get_llm_provider(settings),
            HybridRetriever(session, settings, embeddings),
        )
        report = await service.request(investigation_id, payload.type, payload.subject_entity_id)
        await session.commit()
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DomainConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (EmbeddingProviderError, LLMProviderError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    if report.status is InvestigationReportStatus.COMPLETED:
        response.status_code = status.HTTP_200_OK
    elif report.status is InvestigationReportStatus.PENDING:
        try:
            task_id = await dispatcher.dispatch(report.id)
            report.active_celery_task_id = task_id
            await session.commit()
        except DispatchError as exc:
            await service.fail(report.id, code="DISPATCH_FAILED", message=str(exc))
            await session.commit()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="report task could not be queued",
            ) from exc
    await session.refresh(report)
    return report


@router.get(
    "/investigations/{investigation_id}/reports",
    response_model=list[InvestigationReportSummaryRead],
)
async def list_reports(
    investigation_id: UUID,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> object:
    await _require_investigation(investigation_id, session)
    return await InvestigationReportRepository(session).list_by_investigation(
        investigation_id, limit=limit, offset=offset
    )


@router.get("/reports/{report_id}", response_model=InvestigationReportRead)
async def get_report(report_id: UUID, session: Session) -> object:
    report = await InvestigationReportRepository(session).get(report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    return report
