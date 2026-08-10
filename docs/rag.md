# RAG grounded de TraceLink

## Alcance

Fase 6 agrega recuperación y síntesis grounded dentro de una Investigation. No incorpora agentes
multi-hop, replanning, UI ni conocimiento externo. PostgreSQL sigue siendo la fuente de verdad y
Redis sólo transporta jobs Celery.

## Chunking e embeddings

El chunking de retrieval es independiente del de extracción. Usa caracteres, `1600` de tamaño y
`200` de overlap por defecto, conserva offsets sobre `Document.raw_text` y prefiere límites de
párrafo, oración y palabra. Su identidad incluye SHA-256 del texto, content hash del documento,
configuración y `character-boundary-v1`. `token_count` queda NULL porque no se agrega tokenizer.

`EmbeddingProvider` expone provider, model, dimensions y `embed_texts`. El fake aplica feature
hashing determinista y normalizado. El adaptador OpenAI es opt-in y usa
`text-embedding-3-small`; ambos producen 1536 dimensiones. `embedding_records` referencia al chunk
y nunca duplica su texto. Retrieval siempre filtra provider/model/dimensions.

`index_document_for_retrieval` reconcilia chunks idempotentemente, reutiliza vectores por content
hash y modelo, procesa batches de 32 y persiste de forma redelivery-safe. Un cambio de fingerprint
reemplaza chunks y elimina embeddings viejos por cascade.

## Providers y coste

Fake es el default hermético. OpenAI requiere seleccionar el provider y configurar
`OPENAI_API_KEY`; la ausencia de credenciales no afecta tests. El LLM usa Structured Outputs,
`store=false` y no solicita razonamiento. Límites de top-k, batches y contexto evitan enviar
documentos completos. Fase 6 no cachea respuestas Q&A ni usa un LLM para retrieval.

