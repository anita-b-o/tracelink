from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.domain.enums import InvestigationStatus
from tracelink.domain.models import Investigation
from tracelink.domain.normalization import clean_text
from tracelink.domain.validation import require_non_empty


class InvestigationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, title: str, original_query: str) -> Investigation:
        investigation = Investigation(
            title=require_non_empty(clean_text(title), "title"),
            original_query=require_non_empty(original_query.strip(), "original_query"),
            status=InvestigationStatus.DRAFT,
        )
        self.session.add(investigation)
        await self.session.flush()
        await self.session.refresh(investigation)
        return investigation

    async def get_by_id(self, investigation_id: UUID) -> Investigation | None:
        return await self.session.get(Investigation, investigation_id)

    async def get_by_id_for_update(self, investigation_id: UUID) -> Investigation | None:
        return cast(
            Investigation | None,
            await self.session.scalar(
                select(Investigation).where(Investigation.id == investigation_id).with_for_update()
            ),
        )

    async def list(self, *, limit: int = 50, offset: int = 0) -> list[Investigation]:
        result = await self.session.scalars(
            select(Investigation)
            .order_by(Investigation.created_at.desc(), Investigation.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result)

    async def update(
        self,
        investigation: Investigation,
        *,
        title: str | None = None,
        original_query: str | None = None,
    ) -> Investigation:
        if title is not None:
            investigation.title = require_non_empty(clean_text(title), "title")
        if original_query is not None:
            investigation.original_query = require_non_empty(
                original_query.strip(), "original_query"
            )
        await self.session.flush()
        await self.session.refresh(investigation)
        return investigation
