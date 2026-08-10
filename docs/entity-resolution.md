# Entity resolution

## Normalización y candidatos

La forma original siempre queda en `canonical_name`, alias o `surface_form`. Cada tipo tiene un
normalizador explícito y una `comparison_key` separada:

- PERSON: NFKC, trim, whitespace, puntuación conservadora y casefold; conserva segundos nombres.
- COMPANY/ORGANIZATION: lo anterior y equivalencia comparativa de designadores legales (`S.A.`, `SA`,
  `Sociedad Anónima`, etc.) sin borrar la forma presentada.
- DOMAIN: hostname puro, lowercase, IDNA ASCII, sin trailing dot y con validación de labels.
- ADDRESS: whitespace/casing y un conjunto pequeño de abreviaturas seguras.

Candidate generation siempre filtra por tipo. Consulta `comparison_key` y aliases exactos o con
similitud trigram moderada mediante índices GIN de `pg_trgm`, limita el conjunto a 25 y calcula luego
similitud textual y overlap de tokens. Nunca recorre toda la tabla ni usa vectores.

## Decisiones y scoring

`EntityResolutionService` produce `MATCH_EXISTING`, `POSSIBLE_MATCH` o `CREATE_NEW`, con `score`,
`reason_code` y señales JSON estructuradas. El score base es 0.90 para canonical exacto, 0.93 para alias
exacto o una combinación acotada de similitud textual y tokens. Acuerdos de identificador/registro y
contexto suman; conflictos restan. El valor final se recorta a 0..1.

Defaults configurables:

- `>= ENTITY_RESOLUTION_AUTO_MATCH_THRESHOLD` (0.90): `MATCH_EXISTING`;
- `>= ENTITY_RESOLUTION_POSSIBLE_MATCH_THRESHOLD` (0.65): `POSSIBLE_MATCH`;
- menor: `CREATE_NEW`.

Un possible match crea una Entity provisional separada, enlaza la mention y persiste cada candidato
plausible como `PENDING`. Esto conserva ambas identidades hasta una futura revisión. Un auto-match queda
como `AUTO_MATCHED`. ACCEPT/REJECT y merge manual no se exponen todavía.

## Regla de seguridad PERSON

Nombre o alias exacto nunca basta para auto-mergear PERSON. El gate exige identificador público
coincidente, empresa/organización más rol, o ubicación más rol. Sin esa señal, la decisión queda en
`POSSIBLE_MATCH` y se crea una Entity provisional. Contextos contradictorios reducen el score y
mantienen a los homónimos separados.

## Aliases, provenance y concurrencia

Al resolver contra una Entity existente, el surface se agrega como alias sólo si su comparison key no
repite canonical ni alias. Constraints de alias cierran carreras.

La cadena auditable es `Investigation -> InvestigationArtifact -> Source -> Document -> EntityMention
-> Entity`. `EntityResolutionCandidate` agrega la decisión revisable sin depender de logs ni crear
Evidence general. El lock de documento evita reprocesamiento concurrente y otro advisory lock por
tipo/comparison key serializa creación/resolución global; homónimos PERSON sin contexto siguen siendo
entidades distintas por diseño.
