# Retrieval híbrido

## Query e aislamiento

`HybridRetriever` une `investigation_artifacts`, Documents, Sources, RetrievalChunks y el embedding
activo en una única query. `investigation_id` forma parte del `WHERE`; no existe búsqueda global
con filtrado posterior en Python.

La parte semántica usa cosine similarity: `max(0, 1 - cosine_distance)`. La parte léxica usa
`websearch_to_tsquery('simple', query)` y `ts_rank_cd(..., 32)` sobre un `tsvector` generado y un
índice GIN. `simple` evita asumir idioma y no aplica stemming.

El score es `min(1, 0.70 * semantic + 0.30 * lexical + evidence_boost)`. `evidence_boost` vale 0.05
cuando Evidence del caso coincide con el chunk o documento. La API expone cada componente.
`top_k` default es 10 y tiene hard cap 50.

## Filtros

Los filtros aceptan Source IDs, Document IDs, Entity IDs, Relationship types y rango de
`Source.published_at`. Los valores de una lista se combinan con OR y categorías distintas con AND.
Mentions/Evidence con offsets deben solapar el chunk; sin offsets se consideran documentales.
Fechas nulas quedan fuera de un rango y `retrieved_at` nunca sustituye una fecha publicada.

## pgvector y performance

Fase 6 usa exact search. No hay HNSW/IVFFlat: con el volumen inicial y filtros relacionales, ANN no
ofrece todavía una ganancia demostrada y puede degradar recall post-filter. Reevaluar al superar
50.000 chunks por Investigation o p95 de retrieval de 200 ms. El baseline reproducible se obtiene
con `EXPLAIN (ANALYZE, BUFFERS)` y el fixture de integración; no se fijan límites temporales
frágiles en CI.

Baseline revalidado en Fase 8 (PostgreSQL 17 + pgvector, fake provider, 11 de agosto de 2026): 100
Documents produjeron 500 chunks/embeddings en 1,903 s; retrieval híbrido top-10 end-to-end tomó
44,949 ms. El `EXPLAIN (ANALYZE, BUFFERS)` aislado por Investigation examinó 500 filas vectoriales
y ejecutó en 3,311 ms, usando los índices de provider/model y
`investigation_id/document_id`. Los tiempos son orientativos, no umbrales de CI; el test
reproducible es `tests/integration/test_rag_performance.py`.
