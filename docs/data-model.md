# Modelo de datos de TraceLink

## Alcance

El núcleo persistente y auditable incluye el workflow con connectors de Fase 3. El grafo de entidades,
fuentes y documentos es compartido entre investigaciones; evidence y findings pertenecen a una
investigación. Todavía no existen autenticación, conectores, extracción automática ni RAG.

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
| `relationships` | Arista dirigida entre entidades | sin self-reference; confidence 0..1; única por origen, destino y tipo |
| `sources` | Identidad estable de una URL pública | URL normalizada y SHA-256 indexados; writes serializados por advisory lock |
| `documents` | Contenido textual recuperado | SHA-256 de UTF-8; único por source y hash |
| `evidence` | Evidencia que respalda un nodo o una relación | requiere entity o relationship; confidence 0..1 |
| `findings` | Conclusión de una investigación | confidence y relevance opcional 0..1 |
| `embedding_records` | Reserva de esquema para chunks vectoriales | vector sin dimensión fija; chunk único por documento; sin búsqueda ni índice ANN |

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

Los nombres aplican Unicode NFKC, trim, colapso de whitespace y `casefold()`. No se quitan acentos,
no se translitera y no existe fuzzy matching. La búsqueda por nombre puede devolver varias
entidades porque dos personas o empresas distintas pueden compartir nombre.

Los aliases se deduplican por `(entity_id, normalized_alias)`. Las relationships se deduplican como
aristas dirigidas por `(source_entity_id, target_entity_id, type)`. La URL normalizada descarta
fragmentos, puertos default y casing del host sin reordenar query ni cambiar trailing slashes no
raíz. Los nuevos fetches reutilizan la Source bajo advisory lock; filas legacy no se eliminan. El
contenido se deduplica por `(source_id, content_hash)` sin perder procedencia entre URLs.

La columna `embedding` usa `vector` sin dimensión. La dimensión, modelo, métrica e índice se
definirán en la fase de RAG con datos y proveedor conocidos.

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
- ambos extremos de relationships y el par origen/destino;
- `(sources.url_hash, sources.normalized_url)`, type y retrieved_at;
- `documents.content_hash` y claves foráneas de evidence;
- `(document_id, chunk_index)` único en embedding records.
