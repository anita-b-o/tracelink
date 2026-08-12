from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.core.config import Settings
from tracelink.domain.rag import RetrievalFilters, RetrievalHit
from tracelink.observability.metrics import EMBEDDING_BATCHES
from tracelink.services.embedding_providers import EmbeddingProvider

logger = logging.getLogger(__name__)


def hybrid_score(
    semantic_score: float,
    lexical_score: float,
    *,
    semantic_weight: float,
    lexical_weight: float,
    evidence_boost: float = 0.0,
) -> float:
    return min(
        1.0,
        semantic_weight * max(0.0, semantic_score)
        + lexical_weight * max(0.0, lexical_score)
        + max(0.0, evidence_boost),
    )


class HybridRetriever:
    def __init__(
        self, session: AsyncSession, settings: Settings, provider: EmbeddingProvider
    ) -> None:
        self.session = session
        self.settings = settings
        self.provider = provider

    async def search(
        self,
        investigation_id: UUID,
        query: str,
        *,
        filters: RetrievalFilters | None = None,
        top_k: int | None = None,
    ) -> list[RetrievalHit]:
        selected_filters = filters or RetrievalFilters()
        selected_top_k = min(top_k or self.settings.rag_top_k, 50)
        try:
            vectors = await self.provider.embed_texts([query])
        except Exception:
            EMBEDDING_BATCHES.labels(self.provider.provider_name, "failure").inc()
            raise
        EMBEDDING_BATCHES.labels(self.provider.provider_name, "success").inc()
        if len(vectors) != 1 or len(vectors[0]) != self.provider.dimensions:
            raise ValueError("embedding provider returned an incompatible query vector")

        clauses = [
            "ia.investigation_id = :investigation_id",
            "e.provider = :provider",
            "e.model = :model",
            "e.dimensions = :dimensions",
        ]
        parameters: dict[str, object] = {
            "investigation_id": investigation_id,
            "provider": self.provider.provider_name,
            "model": self.provider.model_name,
            "dimensions": self.provider.dimensions,
            "query": query,
            "query_vector": "[" + ",".join(str(value) for value in vectors[0]) + "]",
            "semantic_weight": self.settings.rag_semantic_weight,
            "lexical_weight": self.settings.rag_lexical_weight,
            "top_k": selected_top_k,
        }
        if selected_filters.source_ids:
            clauses.append("s.id = ANY(:source_ids)")
            parameters["source_ids"] = list(selected_filters.source_ids)
        if selected_filters.document_ids:
            clauses.append("d.id = ANY(:document_ids)")
            parameters["document_ids"] = list(selected_filters.document_ids)
        if selected_filters.published_from is not None:
            clauses.append("s.published_at >= :published_from")
            parameters["published_from"] = selected_filters.published_from
        if selected_filters.published_to is not None:
            clauses.append("s.published_at <= :published_to")
            parameters["published_to"] = selected_filters.published_to
        if selected_filters.entity_ids:
            clauses.append(
                "EXISTS (SELECT 1 FROM entity_mentions em_filter "
                "WHERE em_filter.investigation_id = ia.investigation_id "
                "AND em_filter.document_id = d.id "
                "AND em_filter.entity_id = ANY(:entity_ids) "
                "AND (em_filter.start_offset IS NULL OR "
                "(em_filter.start_offset < rc.end_offset "
                "AND em_filter.end_offset > rc.start_offset)))"
            )
            parameters["entity_ids"] = list(selected_filters.entity_ids)
        if selected_filters.relationship_types:
            clauses.append(
                "EXISTS (SELECT 1 FROM evidence ev_filter "
                "JOIN relationships rel_filter ON rel_filter.id = ev_filter.relationship_id "
                "WHERE ev_filter.investigation_id = ia.investigation_id "
                "AND ev_filter.document_id = d.id "
                "AND rel_filter.type::text = ANY(:relationship_types) "
                "AND (ev_filter.start_offset IS NULL OR "
                "(ev_filter.start_offset < rc.end_offset "
                "AND ev_filter.end_offset > rc.start_offset)))"
            )
            parameters["relationship_types"] = list(selected_filters.relationship_types)

        # Every interpolated clause above is a fixed server-side SQL fragment; all
        # user-controlled values remain bound parameters.
        sql_template = """
            WITH scored AS (
                SELECT
                    rc.id AS chunk_id,
                    rc.document_id,
                    s.id AS source_id,
                    rc.chunk_index,
                    rc.chunk_text,
                    rc.start_offset,
                    rc.end_offset,
                    s.url AS source_url,
                    s.title AS source_title,
                    s.published_at,
                    GREATEST(0.0, 1.0 - (e.embedding <=> CAST(:query_vector AS vector)))
                        AS semantic_score,
                    ts_rank_cd(
                        rc.search_vector,
                        websearch_to_tsquery('simple', :query),
                        32
                    ) AS lexical_score,
                    CASE WHEN EXISTS (
                        SELECT 1 FROM evidence ev_boost
                        WHERE ev_boost.investigation_id = ia.investigation_id
                          AND ev_boost.document_id = d.id
                          AND (ev_boost.start_offset IS NULL OR
                            (ev_boost.start_offset < rc.end_offset
                             AND ev_boost.end_offset > rc.start_offset))
                    ) THEN 0.05 ELSE 0.0 END AS evidence_boost,
                    COALESCE((
                        SELECT array_agg(DISTINCT em.entity_id)
                        FROM entity_mentions em
                        WHERE em.investigation_id = ia.investigation_id
                          AND em.document_id = d.id
                          AND em.entity_id IS NOT NULL
                          AND (em.start_offset IS NULL OR
                            (em.start_offset < rc.end_offset AND em.end_offset > rc.start_offset))
                    ), ARRAY[]::uuid[]) AS matched_entity_ids,
                    COALESCE((
                        SELECT array_agg(DISTINCT rel.type::text)
                        FROM evidence ev
                        JOIN relationships rel ON rel.id = ev.relationship_id
                        WHERE ev.investigation_id = ia.investigation_id
                          AND ev.document_id = d.id
                          AND (ev.start_offset IS NULL OR
                            (ev.start_offset < rc.end_offset AND ev.end_offset > rc.start_offset))
                    ), ARRAY[]::text[]) AS matched_relationship_types
                FROM retrieval_chunks rc
                JOIN embedding_records e ON e.retrieval_chunk_id = rc.id
                JOIN documents d ON d.id = rc.document_id
                JOIN sources s ON s.id = d.source_id
                JOIN investigation_artifacts ia
                  ON ia.document_id = d.id AND ia.source_id = s.id
                WHERE __FILTERS__
            )
            SELECT *, LEAST(
                1.0,
                :semantic_weight * semantic_score
                + :lexical_weight * lexical_score
                + evidence_boost
            ) AS combined_score
            FROM scored
            ORDER BY combined_score DESC, semantic_score DESC, lexical_score DESC, chunk_id
            LIMIT :top_k
            """
        # The replacement values are fixed server-side fragments, never user input.
        statement = text(  # nosec B608
            sql_template.replace("__FILTERS__", " AND ".join(clauses))
        )
        rows = (await self.session.execute(statement, parameters)).mappings().all()
        hits = [
            RetrievalHit(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                source_id=row["source_id"],
                chunk_index=row["chunk_index"],
                chunk_text=row["chunk_text"],
                start_offset=row["start_offset"],
                end_offset=row["end_offset"],
                source_url=row["source_url"],
                source_title=row["source_title"],
                published_at=row["published_at"],
                semantic_score=float(row["semantic_score"]),
                lexical_score=float(row["lexical_score"]),
                evidence_boost=float(row["evidence_boost"]),
                combined_score=float(row["combined_score"]),
                matched_entity_ids=tuple(row["matched_entity_ids"]),
                matched_relationship_types=tuple(row["matched_relationship_types"]),
            )
            for row in rows
        ]
        logger.info(
            "hybrid retrieval completed",
            extra={
                "investigation_id": str(investigation_id),
                "retrieval_top_k": selected_top_k,
                "embedding_provider": self.provider.provider_name,
                "embedding_model": self.provider.model_name,
                "result_count": len(hits),
            },
        )
        for hit in hits:
            logger.debug(
                "hybrid retrieval result",
                extra={
                    "investigation_id": str(investigation_id),
                    "document_id": str(hit.document_id),
                    "retrieval_chunk_id": str(hit.chunk_id),
                    "semantic_score": round(hit.semantic_score, 6),
                    "lexical_score": round(hit.lexical_score, 6),
                    "combined_score": round(hit.combined_score, 6),
                },
            )
        return hits
