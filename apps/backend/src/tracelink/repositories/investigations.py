from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.core.config import get_settings
from tracelink.domain.enums import InvestigationStatus
from tracelink.domain.models import Investigation, User
from tracelink.domain.normalization import clean_text
from tracelink.domain.validation import require_non_empty
from tracelink.services.auth import normalize_email, password_hash


class InvestigationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, title: str, original_query: str, *, user_id: UUID | None = None
    ) -> Investigation:
        if user_id is None:
            settings = get_settings()
            if settings.app_env not in {"development", "test"}:
                raise ValueError("user_id is required outside development/test")
            email = normalize_email(settings.dev_bootstrap_email)
            user = await self.session.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(
                    email=email,
                    password_hash=password_hash.hash(
                        settings.dev_bootstrap_password.get_secret_value()
                    ),
                    is_active=True,
                )
                self.session.add(user)
                await self.session.flush()
            user_id = user.id
        investigation = Investigation(
            user_id=user_id,
            title=require_non_empty(clean_text(title), "title"),
            original_query=require_non_empty(original_query.strip(), "original_query"),
            status=InvestigationStatus.DRAFT,
        )
        self.session.add(investigation)
        await self.session.flush()
        await self.session.refresh(investigation)
        return investigation

    async def get_by_id(
        self, investigation_id: UUID, *, user_id: UUID | None = None
    ) -> Investigation | None:
        statement = select(Investigation).where(Investigation.id == investigation_id)
        if user_id is not None:
            statement = statement.where(Investigation.user_id == user_id)
        return cast(Investigation | None, await self.session.scalar(statement))

    async def get_by_id_for_update(self, investigation_id: UUID) -> Investigation | None:
        return cast(
            Investigation | None,
            await self.session.scalar(
                select(Investigation).where(Investigation.id == investigation_id).with_for_update()
            ),
        )

    async def list(
        self, *, user_id: UUID | None = None, limit: int = 50, offset: int = 0
    ) -> list[Investigation]:
        statement = select(Investigation)
        if user_id is not None:
            statement = statement.where(Investigation.user_id == user_id)
        result = await self.session.scalars(
            statement.order_by(Investigation.created_at.desc(), Investigation.id.desc())
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
