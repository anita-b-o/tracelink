# Extracción de relaciones

## Candidate y relación final

La extracción nunca crea una `Relationship` directamente. Primero persiste un
`RelationshipCandidate` ligado a Investigation, Document, entidades, span, método y fingerprint.
La validación devuelve `AUTO_ACCEPT`, `POSSIBLE`, `REJECT` o `CONTRADICT`; sólo una aceptación
automática o una contradicción validada materializa la arista y su Evidence en la misma transacción.

Los claims distinguen `AFFIRMS`, `NEGATES` y `ENDS`. No se guarda razonamiento libre: los motivos
son reason codes y señales JSON estructuradas. `MENTIONED_IN` permanece reservado porque
`EntityMention` ya modela esa procedencia sin crear Entities DOCUMENT redundantes.

## Tipos, dirección y compatibilidad

Son dirigidas `DIRECTOR_OF`, `OWNER_OF`, `EMPLOYEE_OF`, `OWNS_DOMAIN`, `SUBSIDIARY_OF` y el tipo
reservado `MENTIONED_IN`. Son simétricas `RELATED_TO`, `PARTNER_OF` y
`SHARES_ADDRESS_WITH`; sus UUID se ordenan antes de persistir y PostgreSQL exige ese orden.

- `DIRECTOR_OF`: PERSON → COMPANY u ORGANIZATION.
- `OWNER_OF`: PERSON o COMPANY → COMPANY o DOMAIN.
- `EMPLOYEE_OF`: PERSON → COMPANY u ORGANIZATION.
- `OWNS_DOMAIN`: PERSON, COMPANY u ORGANIZATION → DOMAIN.
- `SUBSIDIARY_OF`: COMPANY → COMPANY.
- `SHARES_ADDRESS_WITH`: COMPANY u ORGANIZATION en ambos extremos.
- `PARTNER_OF`: PERSON, COMPANY u ORGANIZATION en ambos extremos.
- `RELATED_TO` no restringe tipos.

Los extractores deterministas cubren patrones textuales fuertes, registrants RDAP públicos y
direcciones resueltas compartidas. Un registrar RDAP no se interpreta como owner. El provider
opcional recibe texto y mentions resueltas y devuelve output Pydantic estricto; Fase 5 sólo incluye
el fake usado en tests.

## Confidence y contradicción

El score combina confidence del extractor (40%), fuerza del método (25%), evidencia exacta (15%),
resolución de endpoints (10%), calidad de Source (5%) y consistencia temporal (5%). Fuentes
independientes agregan hasta 0.10. El default de calidad ausente es 0.5. Los thresholds son 0.90
para auto aceptación y 0.65 para posible.

Fuentes distintas sólo corroboran si también difieren content hash y publisher/hostname. Una
afirmación y negación contradicen cuando sus períodos explícitos se solapan o ambas declaran estado
actual. `ENDS` cierra temporalidad sin contradecir por sí solo. La contradicción conserva candidates
y Evidence supporting/contradicting y marca la Relationship `CONTRADICTED`.

## Idempotencia y ejecución

Candidates y Evidence tienen fingerprints SHA-256 estables. Relationships son únicas por endpoints
y tipo. Cada job toma advisory lock transaccional por Investigation/Document y luego por identidad
de relación; los upserts y constraints permiten que workers concurrentes converjan sin locks Redis.
`process_document_entities` publica `process_document_relationships` después del commit únicamente
si hay dos entidades resueltas distintas. Los errores transitorios se reintentan; output inválido no.
