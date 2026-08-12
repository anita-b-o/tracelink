# Observabilidad

Los logs son JSON. Cada request acepta o crea `X-Request-ID`, lo devuelve al cliente y lo propaga a
outbox/Celery. Cuando aplica se agregan `investigation_id`, `research_task_id` y `celery_task_id`.
Eventos de login, refresh/reuse, logout, rate limit y acceso oculto se registran sin contenido.

`GET /metrics` requiere `Authorization: Bearer $METRICS_BEARER_TOKEN` y expone Prometheus:
requests, latencia, errores, estados de investigaciones, outcomes Celery, outbox/stuck jobs,
fallos de connectors, llamadas LLM, batches de embeddings y cache hit/miss. Las labels son rutas,
métodos, status y nombres acotados; nunca UUID, email, query ni documento.

Sentry es opcional con `SENTRY_DSN`; sin DSN no inicializa. Mantener PII deshabilitada y traces en
0 por defecto. Cookies, Authorization y cuerpos deben permanecer fuera de eventos. El frontend no
requiere Sentry para funcionar; si se habilita, usar un DSN público separado y el mismo criterio de
scrubbing.

Alertas mínimas recomendadas: readiness fallando, tasa 5xx, outbox failed/lease vencido,
ResearchTask/Report RUNNING obsoleto, worker sin heartbeat y saturación de conexiones DB/Redis.

