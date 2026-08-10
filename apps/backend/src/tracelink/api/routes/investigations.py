from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.api.schemas.investigations import (
    InvestigationCreate,
    InvestigationProgressRead,
    InvestigationRead,
)
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
from tracelink.infrastructure.database import get_session
from tracelink.jobs.dispatcher import (
    DispatchError,
    ResearchTaskDispatcher,
    get_research_task_dispatcher,
)
from tracelink.repositories.investigations import InvestigationRepository
from tracelink.services.errors import DomainConflictError, DomainNotFoundError
from tracelink.services.investigation_workflow import InvestigationWorkflowService
from tracelink.services.research_artifacts import ResearchArtifactService

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


@router.get("", response_model=list[InvestigationRead])
async def list_investigations(
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> object:
    return await InvestigationRepository(session).list(limit=limit, offset=offset)


@router.get("/{investigation_id}", response_model=InvestigationRead)
async def get_investigation(investigation_id: UUID, session: Session) -> object:
    investigation = await InvestigationRepository(session).get_by_id(investigation_id)
    if investigation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="investigation not found")
    return investigation


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
    return await ResearchArtifactService(session).persist(output)


@router.post(
    "/{investigation_id}/start",
    response_model=InvestigationRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_investigation(
    investigation_id: UUID, session: Session, dispatcher: Dispatcher
) -> object:
    try:
        result = await InvestigationWorkflowService(session, get_settings()).start(investigation_id)
        await session.commit()
        await session.refresh(result.investigation)
        response = InvestigationRead.model_validate(result.investigation)
    except (DomainNotFoundError, DomainConflictError) as exc:
        raise_workflow_http_error(exc)
    try:
        for research_task_id in result.pending_task_ids:
            await dispatcher.dispatch(research_task_id)
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
