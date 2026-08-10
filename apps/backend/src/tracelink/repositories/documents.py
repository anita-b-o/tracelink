from __future__ import annotations

import builtins
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.domain.models import Document, JsonObject


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        source_id: UUID,
        mime_type: str,
        raw_text: str,
        content_hash: str,
        metadata: JsonObject | None = None,
    ) -> Document:
        document = Document(
            source_id=source_id,
            mime_type=mime_type,
            raw_text=raw_text,
            content_hash=content_hash,
            metadata_=metadata or {},
        )
        self.session.add(document)
        await self.session.flush()
        await self.session.refresh(document)
        return document

    async def get_by_id(self, document_id: UUID) -> Document | None:
        return await self.session.get(Document, document_id)

    async def list(self, *, limit: int = 50, offset: int = 0) -> list[Document]:
        result = await self.session.scalars(
            select(Document)
            .order_by(Document.created_at.desc(), Document.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result)

    async def find_by_content_hash(
        self, content_hash: str, *, source_id: UUID | None = None
    ) -> builtins.list[Document]:
        statement = select(Document).where(Document.content_hash == content_hash)
        if source_id is not None:
            statement = statement.where(Document.source_id == source_id)
        result = await self.session.scalars(
            statement.order_by(Document.created_at.desc(), Document.id.desc())
        )
        return list(result)
