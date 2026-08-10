# Entity extraction

## Pipeline

Fase 4 procesa exclusivamente `PERSON`, `COMPANY`, `ORGANIZATION`, `DOMAIN` y `ADDRESS`:

```text
ResearchTask / URL ingestion
  -> Source + Document + InvestigationArtifact
  -> process_document_entities (Celery)
  -> preprocessing y chunks
  -> extractores deterministas + provider opcional
  -> EntityMention
  -> entity resolution
```

`Document.raw_text` conserva el contenido físico global. El preprocessing crea una vista reproducible,
normaliza finales de línea y caracteres de control y mantiene un mapa hacia los offsets originales. El
chunker usa caracteres, prefiere límites de párrafo/oración/whitespace, conserva un overlap pequeño y
no acepta tamaños menores a 500. Los defaults son 4000 caracteres y 300 de overlap.

Cada `EntityMention` pertenece a una Investigation y un Document. Guarda surface y forma normalizada,
offsets globales cuando el extractor los aporta, chunk, método, confidence, metadata estructurada y un
fingerprint estable. Puede existir con `entity_id = NULL`: baja confidence, tipo conflictivo o datos
inválidos nunca fuerzan una Entity.

## Extractores y providers

Los extractores deterministas reconocen dominios IDNA válidos, sociedades con designador legal,
organizaciones con palabras indicadoras, personas con honorífico y direcciones de formatos simples.
Las reglas de PERSON/ADDRESS son deliberadamente prudentes; no intentan NER general ni parsing postal
completo.

`EntityExtractionProvider.extract(text, allowed_types, context)` recibe un chunk y devuelve
`ExtractedEntityCandidate` validado por Pydantic. El DTO sólo admite tipo, surface, candidato canónico,
confidence, offsets, attributes y señales enumeradas; no acepta texto libre como fuente de verdad ni
chain-of-thought. `FakeEntityExtractionProvider` permite responses, aliases, homónimos, duplicados,
conflictos, baja confidence y fallos deterministas. No hay adapter LLM comercial en esta fase.

Para agregar un extractor, devolvé el mismo DTO y registralo en la agregación determinista. Para agregar
un provider, implementá el protocolo, validá el structured output antes de retornarlo e inyectalo en
`DocumentEntityProcessingService`; sin provider, el pipeline determinista sigue operativo.

## Idempotencia y fallos

El fingerprint combina tipo, forma normalizada y locator. Detecciones repetidas en overlaps o por varios
métodos se agregan, conservando métodos y confidence máxima. La constraint única
`(investigation_id, document_id, fingerprint)` es la defensa final. Un advisory lock transaccional por
Investigation/Document serializa workers; un segundo procesamiento reutiliza las mentions existentes.

El job Celery usa late ack y retries acotados para fallos de base/provider. Una falla no cambia el estado
de la Investigation ni persiste output parcial. Los logs contienen IDs, tipo, decisión, score y método,
nunca documento, prompt o respuesta completa.
