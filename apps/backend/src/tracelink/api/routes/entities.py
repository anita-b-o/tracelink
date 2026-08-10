from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.api.schemas.entities import EntityCreate, EntityRead
from tracelink.infrastructure.database import get_session
from tracelink.repositories.entities import EntityRepository
from tracelink.services.entities import EntityService
from tracelink.services.errors import DomainConflictError

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("", response_model=EntityRead, status_code=status.HTTP_201_CREATED)
async def create_entity(payload: EntityCreate, session: Session) -> object:
    service = EntityService(EntityRepository(session))
    try:
        return await service.create(
            entity_type=payload.type,
            canonical_name=payload.canonical_name,
            aliases=payload.aliases,
            metadata=payload.metadata,
        )
    except DomainConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="entity conflicts with an existing alias",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.get("/{entity_id}", response_model=EntityRead)
async def get_entity(entity_id: UUID, session: Session) -> object:
    entity = await EntityRepository(session).get_by_id(entity_id)
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="entity not found")
    return entity
