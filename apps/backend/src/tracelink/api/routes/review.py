from collections.abc import Awaitable, Callable
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.api.routes.workspace import candidate_read
from tracelink.api.schemas.entities import EntityResolutionCandidateRead
from tracelink.api.schemas.relationships import RelationshipCandidateRead
from tracelink.domain.models import RelationshipCandidate
from tracelink.infrastructure.database import get_session
from tracelink.services.errors import DomainConflictError, DomainNotFoundError
from tracelink.services.review import (
    EntityCandidateReviewService,
    RelationshipCandidateReviewService,
)

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


async def execute_review(
    session: AsyncSession, operation: Callable[[], Awaitable[object]]
) -> object:
    try:
        result = await operation()
        await session.commit()
        return result
    except DomainNotFoundError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DomainConflictError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/entity-resolution-candidates/{candidate_id}/accept",
    response_model=EntityResolutionCandidateRead,
)
async def accept_entity_candidate(candidate_id: UUID, session: Session) -> object:
    return await execute_review(
        session, lambda: EntityCandidateReviewService(session).accept(candidate_id)
    )


@router.post(
    "/entity-resolution-candidates/{candidate_id}/reject",
    response_model=EntityResolutionCandidateRead,
)
async def reject_entity_candidate(candidate_id: UUID, session: Session) -> object:
    return await execute_review(
        session, lambda: EntityCandidateReviewService(session).reject(candidate_id)
    )


async def relationship_response(
    session: AsyncSession, candidate: RelationshipCandidate
) -> RelationshipCandidateRead:
    await session.refresh(candidate, ["source_entity", "target_entity", "document"])
    return candidate_read(candidate)


@router.post(
    "/relationship-candidates/{candidate_id}/accept",
    response_model=RelationshipCandidateRead,
)
async def accept_relationship_candidate(candidate_id: UUID, session: Session) -> object:
    candidate = cast(
        RelationshipCandidate,
        await execute_review(
            session, lambda: RelationshipCandidateReviewService(session).accept(candidate_id)
        ),
    )
    return await relationship_response(session, candidate)


@router.post(
    "/relationship-candidates/{candidate_id}/reject",
    response_model=RelationshipCandidateRead,
)
async def reject_relationship_candidate(candidate_id: UUID, session: Session) -> object:
    candidate = cast(
        RelationshipCandidate,
        await execute_review(
            session, lambda: RelationshipCandidateReviewService(session).reject(candidate_id)
        ),
    )
    return await relationship_response(session, candidate)
