from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.api.schemas.research_tasks import ResearchTaskRead
from tracelink.core.config import get_settings
from tracelink.infrastructure.database import get_session
from tracelink.jobs.dispatcher import (
    DispatchError,
    ResearchTaskDispatcher,
    get_research_task_dispatcher,
)
from tracelink.repositories.research_tasks import ResearchTaskRepository
from tracelink.services.errors import DomainConflictError, DomainNotFoundError
from tracelink.services.investigation_workflow import InvestigationWorkflowService

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]
Dispatcher = Annotated[ResearchTaskDispatcher, Depends(get_research_task_dispatcher)]


@router.get("/{research_task_id}", response_model=ResearchTaskRead)
async def get_research_task(research_task_id: UUID, session: Session) -> object:
    research_task = await ResearchTaskRepository(session).get_by_id(research_task_id)
    if research_task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="research task not found")
    return research_task


@router.post(
    "/{research_task_id}/retry",
    response_model=ResearchTaskRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_research_task(
    research_task_id: UUID, session: Session, dispatcher: Dispatcher
) -> object:
    try:
        research_task = await InvestigationWorkflowService(session, get_settings()).retry(
            research_task_id
        )
        await session.commit()
        await session.refresh(research_task)
        response = ResearchTaskRead.model_validate(research_task)
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DomainConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    try:
        await dispatcher.dispatch(research_task.id)
    except DispatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="research task could not be queued; retry investigation start",
        ) from exc
    return response
