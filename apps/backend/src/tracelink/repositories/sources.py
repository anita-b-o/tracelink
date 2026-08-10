from __future__ import annotations

import builtins
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.domain.models import JsonObject, Source
from tracelink.domain.normalization import sha256_text
from tracelink.domain.validation import require_non_empty


class SourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        source_type: str,
        url: str,
        publisher: str | None = None,
        title: str | None = None,
        published_at: datetime | None = None,
        retrieved_at: datetime | None = None,
        metadata: JsonObject | None = None,
    ) -> Source:
        stored_url = require_non_empty(url.strip(), "url")
        values: dict[str, object] = {
            "type": require_non_empty(source_type.strip(), "source_type"),
            "publisher": publisher,
            "url": stored_url,
            "url_hash": sha256_text(stored_url),
            "title": title,
            "published_at": published_at,
            "metadata_": metadata or {},
        }
        if retrieved_at is not None:
            values["retrieved_at"] = retrieved_at
        source = Source(**values)
        self.session.add(source)
        await self.session.flush()
        await self.session.refresh(source)
        return source

    async def get_by_id(self, source_id: UUID) -> Source | None:
        return await self.session.get(Source, source_id)

    async def list(self, *, limit: int = 50, offset: int = 0) -> list[Source]:
        result = await self.session.scalars(
            select(Source)
            .order_by(Source.retrieved_at.desc(), Source.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result)

    async def find_by_url(self, url: str) -> builtins.list[Source]:
        stored_url = require_non_empty(url.strip(), "url")
        result = await self.session.scalars(
            select(Source)
            .where(Source.url_hash == sha256_text(stored_url), Source.url == stored_url)
            .order_by(Source.retrieved_at.desc(), Source.id.desc())
        )
        return list(result)
