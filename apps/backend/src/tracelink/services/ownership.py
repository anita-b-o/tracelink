from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.domain.models import Investigation


async def require_owned_investigation(session: AsyncSession, investigation_id: UUID) -> None:
    owner_id = await session.scalar(
        select(Investigation.user_id).where(Investigation.id == investigation_id)
    )
    if owner_id is None:
        raise ValueError("background job requires an owned investigation")
