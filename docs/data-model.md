# Modelo de datos de TraceLink

## Alcance

El núcleo persistente y auditable incluye connectors, entities y relaciones derivadas de Fase 5. El
grafo de entidades, fuentes y documentos es compartido; associations, mentions, evidence y findings
pertenecen a una investigación. Todavía no existen autenticación, RAG ni Findings automáticos.

Todos los identificadores son UUID generados por la aplicación. Los timestamps usan zona horaria y
los objetos extensibles se almacenan en JSONB. Los campos `metadata` aparecen como `metadata_` en
los modelos SQLAlchemy porque `metadata` está reservado por la API declarativa.

## Entidades

| Tabla | Propósito | Reglas principales |
| --- | --- | --- |
| `investigations` | Caso de investigación y consulta original | título y consulta no vacíos; inicia en `DRAFT` |
| `research_tasks` | Plan ejecutable simulado dentro de un caso | tipo único por investigación; attempts no negativo; fechas ordenadas; resultado JSON y último error |
| `entities` | Nodo canónico del grafo | nombre canónico y forma normalizada; nombres iguales no implican identidad |
| `entity_aliases` | Nombre alternativo de una entidad | único por entidad y alias normalizado; no repite el nombre canónico |
| `investigation_artifacts` | Source y Document usados por un caso | triple Investigation/Source/Document único, incluido NULL |
| `entity_mentions` | Aparición extraída antes o después de resolver | fingerprint único por Investigation/Document; confidence y offsets válidos |
| `entity_resolution_candidates` | Match explicable y revisable | único por mention/candidate; score 0..1 y status controlado |
| `relationship_candidates` | Claim extraído antes de validar | fingerprint por Investigation/Document; score, método, span y decisión explicables |
| `relationships` | Arista validada entre entidades | sin self-reference; confidence 0..1; única por extremos canonicalizados y tipo |
| `sources` | Identidad estable de una URL pública | URL normalizada y SHA-256 indexados; writes serializados por advisory lock |
| `documents` | Contenido textual recuperado | SHA-256 de UTF-8; único por source y hash |
| `evidence` | Evidencia que respalda un nodo o una relación | Source/Document/Artifact coherentes; offsets y fingerprint deduplicable |
| `findings` | Conclusión de una investigación | confidence y relevance opcional 0..1 |
| `retrieval_chunks` | Unidad reproducible de recuperación | offsets, hash, metadata de chunker y `tsvector` generado |
| `embedding_records` | Vector asociado a un RetrievalChunk | `vector(1536)`; provider/model/dimensions; sin mezcla de espacios |
| `investigation_reports` | Reporte grounded auditable | fingerprint cacheable, estado Celery, provider/model y contenido JSONB |

Cuando evidence referencia un document, el servicio verifica que el documento pertenezca al
source declarado. Esta regla cruza tablas y se valida en dominio; las claves foráneas mantienen la
existencia individual de ambos registros.

## Enums

- Investigation: `DRAFT`, `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`, `PARTIAL`.
- ResearchTask: `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`.
- Entity: `PERSON`, `COMPANY`, `ORGANIZATION`, `DOMAIN`, `ADDRESS`, `DOCUMENT`.
- Relationship: `DIRECTOR_OF`, `OWNER_OF`, `EMPLOYEE_OF`, `RELATED_TO`,
  `SHARES_ADDRESS_WITH`, `OWNS_DOMAIN`, `MENTIONED_IN`, `SUBSIDIARY_OF`, `PARTNER_OF`.
- Assertion status para relationships y findings: `CONFIRMED`, `PROBABLE`, `POSSIBLE`,
  `UNVERIFIED`, `CONTRADICTED`.

`ResearchTask.type` usa la taxonomía cerrada `IDENTIFY_ENTITY`, `WEB_SEARCH`, `DOMAIN_LOOKUP` y
`PUBLIC_MENTIONS`. `ResearchTask.source_type` continúa nullable; `Source.type` sigue siendo string
hasta incorporar connectors reales.

## Normalización y deduplicación

Los nombres conservan canonical/normalized y agregan `comparison_key` por tipo. COMPANY y
ORGANIZATION equivalen designadores legales sólo en esa clave; DOMAIN aplica IDNA; ADDRESS y PERSON
son conservadores. Candidate generation usa exact/alias y trigram indexado, sin vector search.

Los aliases se deduplican por `(entity_id, normalized_alias)`. Las relationships se deduplican por
`(source_entity_id, target_entity_id, type)` y los tipos simétricos ordenan UUID antes del write.
Candidates y Evidence usan fingerprints SHA-256 estables. La URL normalizada descarta
fragmentos, puertos default y casing del host sin reordenar query ni cambiar trailing slashes no
raíz. Los nuevos fetches reutilizan la Source bajo advisory lock; filas legacy no se eliminan. El
contenido se deduplica por `(source_id, content_hash)` sin perder procedencia entre URLs.

La columna `embedding` usa `vector(1536)`. Distintos provider/model pueden coexistir si respetan la
dimensión, pero cada query selecciona exactamente un espacio. Los embeddings son datos derivados.

## Borrado y cascadas

| Registro eliminado | Acción |
| --- | --- |
| Investigation | cascade a research tasks, evidence y findings del caso |
| Entity | cascade a aliases; restrict si participa en relationships o evidence |
| Relationship | restrict si tiene evidence |
| Source | restrict si tiene documents o evidence |
| Document | restrict si tiene evidence; cascade a embeddings derivados |

Entidades, relaciones, fuentes y documentos no se eliminan al borrar una investigación. La API de
Fase 1 no expone operaciones de borrado.

## Índices principales

- estados de investigations, tasks, relationships y findings;
- `(research_task.investigation_id, research_task.type)` único para idempotencia del planner;
- `(entity.type, entity.normalized_name)`, normalized name y normalized aliases;
- comparison keys exactas y GIN trigram para entities/aliases;
- artifact triple, mention fingerprint y mention/candidate únicos;
- ambos extremos de relationships y el par origen/destino;
- `(sources.url_hash, sources.normalized_url)`, type y retrieved_at;
- `documents.content_hash` y claves foráneas de evidence;
- `(document_id, chunk_index)` único en embedding records.
