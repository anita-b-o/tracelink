from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.core.config import Settings
from tracelink.domain.models import RetrievalChunk
from tracelink.repositories.documents import DocumentRepository
from tracelink.repositories.investigation_artifacts import InvestigationArtifactRepository
from tracelink.repositories.retrieval import RetrievalRepository
from tracelink.services.embedding_providers import EmbeddingProvider
from tracelink.services.errors import DomainNotFoundError
from tracelink.services.retrieval_chunking import (
    RETRIEVAL_CHUNKER_VERSION,
    RetrievalChunkSpec,
    chunk_document_for_retrieval,
)

logger = logging.getLogger(__name__)


class RetrievalIndexingService:
    def __init__(
        self, session: AsyncSession, settings: Settings, provider: EmbeddingProvider
    ) -> None:
        self.session = session
        self.settings = settings
        self.provider = provider
        self.repository = RetrievalRepository(session)

    def _matches(
        self,
        chunks: list[RetrievalChunk],
        specs: list[RetrievalChunkSpec],
        document_content_hash: str,
    ) -> bool:
        if len(chunks) != len(specs):
            return False
        for chunk, spec in zip(chunks, specs, strict=True):
            if (
                chunk.chunk_index != spec.index
                or chunk.content_hash != spec.content_hash
                or chunk.start_offset != spec.start_offset
                or chunk.end_offset != spec.end_offset
                or chunk.metadata_.get("document_content_hash") != document_content_hash
                or chunk.metadata_.get("chunk_size") != self.settings.rag_chunk_size
                or chunk.metadata_.get("overlap") != self.settings.rag_chunk_overlap
                or chunk.metadata_.get("chunker_version") != RETRIEVAL_CHUNKER_VERSION
            ):
                return False
        return True

    async def index(self, investigation_id: UUID, document_id: UUID) -> tuple[int, int]:
        if not await InvestigationArtifactRepository(self.session).has_document(
            investigation_id, document_id
        ):
            raise DomainNotFoundError("document is not associated with the investigation")
        document = await DocumentRepository(self.session).get_by_id(document_id)
        if document is None:
            raise DomainNotFoundError("document not found")

        specs = chunk_document_for_retrieval(
            document.raw_text,
            chunk_size=self.settings.rag_chunk_size,
            overlap=self.settings.rag_chunk_overlap,
        )
        chunks = await self.repository.list_chunks(document_id)
        if not self._matches(chunks, specs, document.content_hash):
            chunks = await self.repository.replace_chunks(
                document_id,
                specs,
                document_content_hash=document.content_hash,
                chunk_size=self.settings.rag_chunk_size,
                overlap=self.settings.rag_chunk_overlap,
                chunker_version=RETRIEVAL_CHUNKER_VERSION,
            )

        embedded_ids = await self.repository.embedded_chunk_ids(
            [chunk.id for chunk in chunks],
            provider=self.provider.provider_name,
            model=self.provider.model_name,
        )
        missing = [chunk for chunk in chunks if chunk.id not in embedded_ids]
        cached = await self.repository.cached_vectors(
            {chunk.content_hash for chunk in missing},
            provider=self.provider.provider_name,
            model=self.provider.model_name,
            dimensions=self.provider.dimensions,
        )
        generated = 0
        batch_size = self.settings.embedding_batch_size
        for start in range(0, len(missing), batch_size):
            batch = missing[start : start + batch_size]
            uncached = [chunk for chunk in batch if chunk.content_hash not in cached]
            if uncached:
                vectors = await self.provider.embed_texts([chunk.chunk_text for chunk in uncached])
                if len(vectors) != len(uncached):
                    raise ValueError("embedding provider returned a mismatched batch")
                for chunk, vector in zip(uncached, vectors, strict=True):
                    if len(vector) != self.provider.dimensions:
                        raise ValueError("embedding provider returned an incompatible dimension")
                    cached[chunk.content_hash] = vector
                    generated += 1
            for chunk in batch:
                await self.repository.add_embedding(
                    chunk_id=chunk.id,
                    vector=cached[chunk.content_hash],
                    provider=self.provider.provider_name,
                    model=self.provider.model_name,
                    dimensions=self.provider.dimensions,
                    content_hash=chunk.content_hash,
                )
            await self.session.flush()
        logger.info(
            "document retrieval indexing completed",
            extra={
                "investigation_id": str(investigation_id),
                "document_id": str(document_id),
                "embedding_provider": self.provider.provider_name,
                "embedding_model": self.provider.model_name,
                "retrieval_chunk_count": len(chunks),
                "embedding_generated_count": generated,
            },
        )
        return len(chunks), generated
