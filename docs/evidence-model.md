# Modelo de Evidence

Fase 6 consume este modelo sin debilitarlo: el contexto grounded incluye sólo Evidence de la
Investigation consultada y cada citation se vuelve a validar contra Evidence o
InvestigationArtifact. Evidence supporting/contradicting se conserva como lados separados.

Cada Relationship producida por el pipeline tiene al menos una Evidence creada atómicamente. La
ruta auditable es:

```text
Relationship → Evidence → InvestigationArtifact → Investigation
                        └→ Source → Document → start_offset/end_offset
Relationship → source Entity / target Entity
```

Evidence usa `SUPPORTING`, `CONTRADICTING` o `TEMPORAL_UPDATE`. Guarda Document y offsets en lugar
de copiar texto; la API reconstruye un preview acotado. `locator` permite referencias estructuradas
como RDAP y metadata conserva IDs de candidate, claim kind y método sin documentos ni reasoning.

El fingerprint incluye Investigation, Document, Relationship, tipo, offsets y extracto normalizado.
Una constraint por Investigation impide duplicación al reprocesar. Las claves compuestas verifican
que Document pertenezca al Source y al InvestigationArtifact declarado.

`Evidence.created_at` es tiempo de observación de TraceLink. `Source.published_at` no se usa como
inicio de la relación. La validez sólo proviene de expresiones explícitas y conserva precisión ISO
parcial (`YYYY`, `YYYY-MM`, `YYYY-MM-DD`) en RelationshipCandidate y Relationship.
