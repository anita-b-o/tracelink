from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.domain.models import Document, JsonObject, Source
from tracelink.domain.normalization import sha256_text
from tracelink.domain.validation import require_non_empty
from tracelink.repositories.documents import DocumentRepository
from tracelink.services.errors import DomainNotFoundError


class DocumentService:
    def __init__(self, session: AsyncSession, repository: DocumentRepository) -> None:
        self.session = session
        self.repository = repository

    async def create(
        self,
        *,
        source_id: UUID,
        mime_type: str,
        raw_text: str,
        metadata: JsonObject | None = None,
    ) -> Document:
        if await self.session.get(Source, source_id) is None:
            raise DomainNotFoundError("source not found")
        mime = require_non_empty(mime_type.strip(), "mime_type")
        content_hash = sha256_text(raw_text)
        existing = await self.repository.find_by_content_hash(content_hash, source_id=source_id)
        if existing:
            return existing[0]
        return await self.repository.create(
            source_id=source_id,
            mime_type=mime,
            raw_text=raw_text,
            content_hash=content_hash,
            metadata=metadata,
        )
