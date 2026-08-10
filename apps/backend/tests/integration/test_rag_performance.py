from __future__ import annotations

import json
import time

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.core.config import Settings
from tracelink.domain.models import EmbeddingRecord, RetrievalChunk
from tracelink.repositories.documents import DocumentRepository
from tracelink.repositories.investigation_artifacts import InvestigationArtifactRepository
from tracelink.repositories.investigations import InvestigationRepository
from tracelink.repositories.sources import SourceRepository
from tracelink.services.documents import DocumentService
from tracelink.services.embedding_providers import FakeEmbeddingProvider
from tracelink.services.hybrid_retrieval import HybridRetriever
from tracelink.services.retrieval_indexing import RetrievalIndexingService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_rag_performance_baseline_100_documents(
    db_session: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings()
    provider = FakeEmbeddingProvider()
    investigation = await InvestigationRepository(db_session).create(
        "RAG performance baseline", "beneficial owner target marker"
    )
    source = await SourceRepository(db_session).create(
        source_type="FIXTURE",
        url="https://performance.example.test/corpus",
        title="Synthetic RAG performance corpus",
    )
    documents = DocumentService(db_session, DocumentRepository(db_session))
    artifacts = InvestigationArtifactRepository(db_session)
    indexer = RetrievalIndexingService(db_session, settings, provider)

    document_ids = []
    for index in range(100):
        sentence = (
            f"Document {index:03d} says target marker has beneficial owner Entity {index:03d}. "
        )
        document = await documents.create(
            source_id=source.id,
            mime_type="text/plain",
            raw_text=(sentence * 95).strip(),
        )
        await artifacts.associate(
            investigation_id=investigation.id,
            source_id=source.id,
            document_id=document.id,
        )
        document_ids.append(document.id)

    indexing_started = time.perf_counter()
    for document_id in document_ids:
        await indexer.index(investigation.id, document_id)
    indexing_seconds = time.perf_counter() - indexing_started

    retrieval_started = time.perf_counter()
    hits = await HybridRetriever(db_session, settings, provider).search(
        investigation.id, "beneficial owner target marker", top_k=10
    )
    retrieval_ms = (time.perf_counter() - retrieval_started) * 1000
    chunk_count = int(
        await db_session.scalar(select(func.count()).select_from(RetrievalChunk)) or 0
    )
    embedding_count = int(
        await db_session.scalar(select(func.count()).select_from(EmbeddingRecord)) or 0
    )
    query_vector = (await provider.embed_texts(["beneficial owner target marker"]))[0]
    plan = await db_session.scalar(
        text(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
            "SELECT rc.id FROM retrieval_chunks rc "
            "JOIN embedding_records e ON e.retrieval_chunk_id = rc.id "
            "JOIN investigation_artifacts ia ON ia.document_id = rc.document_id "
            "WHERE ia.investigation_id = :investigation_id "
            "AND e.provider = :provider AND e.model = :model AND e.dimensions = :dimensions "
            "ORDER BY e.embedding <=> CAST(:query_vector AS vector) LIMIT 10"
        ),
        {
            "investigation_id": investigation.id,
            "provider": provider.provider_name,
            "model": provider.model_name,
            "dimensions": provider.dimensions,
            "query_vector": "[" + ",".join(str(value) for value in query_vector) + "]",
        },
    )

    assert len(hits) == 10
    assert 400 <= chunk_count <= 600
    assert embedding_count == chunk_count
    with capsys.disabled():
        print(
            "RAG_BASELINE="
            + json.dumps(
                {
                    "documents": 100,
                    "chunks": chunk_count,
                    "indexing_seconds": round(indexing_seconds, 3),
                    "retrieval_top_10_ms": round(retrieval_ms, 3),
                    "explain": plan,
                },
                default=str,
                separators=(",", ":"),
            )
        )
