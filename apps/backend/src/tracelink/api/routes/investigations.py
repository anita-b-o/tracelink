from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.api.schemas.investigations import InvestigationCreate, InvestigationRead
from tracelink.infrastructure.database import get_session
from tracelink.repositories.investigations import InvestigationRepository

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


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
