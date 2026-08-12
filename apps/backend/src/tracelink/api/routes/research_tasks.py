from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.api.authorization import AuthorizationService
from tracelink.api.dependencies import CurrentUser
from tracelink.api.schemas.research_tasks import ResearchTaskRead
from tracelink.core.config import get_settings
from tracelink.infrastructure.database import get_session
from tracelink.services.audit import AuditService
from tracelink.services.errors import DomainConflictError, DomainNotFoundError
from tracelink.services.investigation_workflow import InvestigationWorkflowService
from tracelink.services.outbox import enqueue_task

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/{research_task_id}", response_model=ResearchTaskRead)
async def get_research_task(
    research_task_id: UUID, session: Session, current_user: CurrentUser
) -> object:
    return await AuthorizationService(session, current_user.id).research_task(research_task_id)


@router.post(
    "/{research_task_id}/retry",
    response_model=ResearchTaskRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_research_task(
    research_task_id: UUID,
    session: Session,
    current_user: CurrentUser,
) -> object:
    await AuthorizationService(session, current_user.id).research_task(research_task_id)
    settings = get_settings()
    try:
        research_task = await InvestigationWorkflowService(session, settings).retry(
            research_task_id
        )
        await enqueue_task(
            session,
            "tracelink.execute_research_task",
            [str(research_task.id), settings.fake_research_mode],
        )
        await AuditService(session).record(
            user_id=current_user.id,
            action="research_task.retry",
            resource_type="research_task",
            resource_id=research_task.id,
        )
        await session.commit()
        await session.refresh(research_task)
        response = ResearchTaskRead.model_validate(research_task)
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DomainConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return response
