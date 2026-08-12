from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.api.authorization import AuthorizationService
from tracelink.api.dependencies import CurrentUser
from tracelink.api.schemas.entities import EntityRead
from tracelink.infrastructure.database import get_session

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/{entity_id}", response_model=EntityRead)
async def get_entity(entity_id: UUID, session: Session, current_user: CurrentUser) -> object:
    return await AuthorizationService(session, current_user.id).entity(entity_id)
