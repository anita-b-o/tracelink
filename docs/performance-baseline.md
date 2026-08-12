# Baseline de performance de Fase 8

Mediciones locales del 11 de agosto de 2026 sobre Compose E2E, PostgreSQL 17 + pgvector, Redis
7.4, providers fake y artefactos de producción. Son señales de regresión y no SLOs ni assertions
temporales de CI.

## API autenticada y concurrencia

`scripts/performance-smoke.py` inicia sesión por cookies + CSRF, crea cinco Investigations y mide
50 lecturas de dashboard con concurrencia máxima 10. También mide una lectura de detalle, grafo,
search híbrido, Ask fake y enqueue de reporte. Resultado de esta validación:

| Operación | Resultado local |
| --- | ---: |
| Dashboard, 50 requests / concurrencia 10 | p50 74,136 ms; p95 230,907 ms |
| Crear Investigation, cinco requests | p50 8,527 ms; p95 15,447 ms |
| Investigation detail | 10,153 ms |
| Graph, máximo 250 nodos | 17,560 ms |
| Hybrid search top-10 | 21,399 ms |
| Ask con fake provider | 26,508 ms |
| Report creation/enqueue | 31,991 ms; HTTP 202 |

Reproducción contra el stack E2E levantado:

```bash
docker run --rm --network tracelink-e2e_default \
  -v "$PWD/scripts:/scripts:ro" --entrypoint python \
  tracelink-e2e-backend /scripts/performance-smoke.py
```

El smoke sólo crea datos de test. No inicia workflows ni llama proveedores externos.

## Retrieval

El fixture reproducible de 100 Documents produjo 500 chunks/embeddings: indexing 1,903 s,
retrieval híbrido top-10 44,949 ms y `EXPLAIN (ANALYZE, BUFFERS)` 3,311 ms. Search permanece
exacto; ANN se reevaluará con 50.000 chunks por Investigation o p95 sostenido mayor a 200 ms.

## Revisión de índices

Los planes tenant-scoped en la base E2E usaron `uq_users_email`,
`ix_investigations_user_created`, `ix_entity_mentions_investigation_id`,
`uq_evidence_investigation_fingerprint` y las PK de Entities/Relationships. Ejecución observada:

| Query representativa | Execution Time |
| --- | ---: |
| Dashboard por owner | 0,067 ms |
| Entities por owner/Investigation | 0,275 ms |
| Relationships/Evidence por owner | 0,085 ms |
| Conjunto de nodos de graph | 0,088 ms |

Los volúmenes E2E son pequeños, pero los planes confirman que ownership se resuelve en SQL y que
los accesos principales alcanzan los índices esperados. No se añadieron índices especulativos más
allá de ownership, sesiones, auditoría y outbox.
