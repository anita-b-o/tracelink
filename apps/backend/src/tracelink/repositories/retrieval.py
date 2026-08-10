from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.domain.models import EmbeddingRecord, RetrievalChunk
from tracelink.services.retrieval_chunking import RetrievalChunkSpec


class RetrievalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_chunks(self, document_id: UUID) -> list[RetrievalChunk]:
        result = await self.session.scalars(
            select(RetrievalChunk)
            .where(RetrievalChunk.document_id == document_id)
            .order_by(RetrievalChunk.chunk_index)
        )
        return list(result)

    async def replace_chunks(
        self,
        document_id: UUID,
        specs: list[RetrievalChunkSpec],
        *,
        document_content_hash: str,
        chunk_size: int,
        overlap: int,
        chunker_version: str,
    ) -> list[RetrievalChunk]:
        await self.session.execute(
            delete(RetrievalChunk).where(RetrievalChunk.document_id == document_id)
        )
        chunks = [
            RetrievalChunk(
                document_id=document_id,
                chunk_index=spec.index,
                chunk_text=spec.text,
                start_offset=spec.start_offset,
                end_offset=spec.end_offset,
                token_count=None,
                content_hash=spec.content_hash,
                metadata_={
                    "document_content_hash": document_content_hash,
                    "chunk_size": chunk_size,
                    "overlap": overlap,
                    "chunker_version": chunker_version,
                    "unit": "characters",
                },
            )
            for spec in specs
        ]
        self.session.add_all(chunks)
        await self.session.flush()
        return chunks

    async def embedded_chunk_ids(
        self, chunk_ids: list[UUID], *, provider: str, model: str
    ) -> set[UUID]:
        if not chunk_ids:
            return set()
        result = await self.session.scalars(
            select(EmbeddingRecord.retrieval_chunk_id).where(
                EmbeddingRecord.retrieval_chunk_id.in_(chunk_ids),
                EmbeddingRecord.provider == provider,
                EmbeddingRecord.model == model,
            )
        )
        return set(result)

    async def cached_vectors(
        self,
        content_hashes: set[str],
        *,
        provider: str,
        model: str,
        dimensions: int,
    ) -> dict[str, list[float]]:
        if not content_hashes:
            return {}
        rows = await self.session.execute(
            select(EmbeddingRecord.content_hash, EmbeddingRecord.embedding).where(
                EmbeddingRecord.content_hash.in_(content_hashes),
                EmbeddingRecord.provider == provider,
                EmbeddingRecord.model == model,
                EmbeddingRecord.dimensions == dimensions,
            )
        )
        return {content_hash: list(vector) for content_hash, vector in rows}

    async def add_embedding(
        self,
        *,
        chunk_id: UUID,
        vector: list[float],
        provider: str,
        model: str,
        dimensions: int,
        content_hash: str,
    ) -> None:
        statement = (
            insert(EmbeddingRecord)
            .values(
                retrieval_chunk_id=chunk_id,
                embedding=vector,
                provider=provider,
                model=model,
                dimensions=dimensions,
                content_hash=content_hash,
            )
            .on_conflict_do_nothing(constraint="uq_embedding_chunk_provider_model")
        )
        await self.session.execute(statement)
