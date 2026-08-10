# Investigation workflow

## Alcance

La Fase 2 ejecuta un plan de investigación deliberadamente simulado. Valida estados,
persistencia, concurrencia, Celery, Redis, reintentos y cancelación sin consultar fuentes reales ni
crear entidades, relaciones o evidencia falsa.

PostgreSQL es la fuente de verdad del workflow. Redis transporta mensajes de Celery; el result
backend de Celery no reemplaza el resultado persistido en `research_tasks.result`.

## Estados y transiciones

Investigation admite estas transiciones:

```text
DRAFT   -> PENDING | CANCELLED
PENDING -> RUNNING | FAILED | CANCELLED
RUNNING -> COMPLETED | PARTIAL | FAILED | CANCELLED
FAILED  -> PENDING  (sólo por retry explícito)
PARTIAL -> PENDING  (sólo por retry explícito)
```

`COMPLETED` y `CANCELLED` son terminales. ResearchTask admite:

```text
PENDING -> RUNNING | CANCELLED
RUNNING -> COMPLETED | FAILED | CANCELLED
FAILED  -> PENDING  (sólo por retry explícito)
```

Las funciones de transición del dominio son el único mecanismo admitido para modificar estados.
Una transición inválida produce un conflicto de dominio y la API lo representa como HTTP 409.

`started_at` registra el primer comienzo y no se pierde al reintentar. `attempts` se incrementa
cuando un worker reclama una ejecución nueva, no por una redelivery del mismo mensaje.
`completed_at` se fija en estados terminales y se limpia al preparar un retry.

## Plan y ejecución

El planner crea una task de cada tipo: `IDENTIFY_ENTITY`, `WEB_SEARCH`, `DOMAIN_LOOKUP` y
`PUBLIC_MENTIONS`. Todas reutilizan `original_query`; `source_type` queda nulo. La combinación
`(investigation_id, type)` es única y el insert usa `ON CONFLICT DO NOTHING`, por lo que repetir el
planner no duplica trabajo.

El fake executor genera un objeto JSON con tipo, intento, resumen simulado e items vacíos. Sus
modos internos son `SUCCESS`, `FAIL_ONCE`, `ALWAYS_FAIL` y `SLOW`; no forman parte del contrato
HTTP. El delay base se configura con `FAKE_RESEARCH_DELAY_MS`.

El flujo normal es:

```text
POST /start -> lock Investigation -> plan + PENDING -> commit -> publish Celery
worker -> claim RUNNING -> fake executor -> COMPLETED/FAILED -> estado agregado
```

La aplicación Celery usa mensajes JSON, late acknowledgement, rechazo ante pérdida del worker y
prefetch de uno. Cada proceso worker mantiene un único `asyncio.Runner` para ejecutar los servicios
SQLAlchemy async y cerrar su engine al terminar.

## Idempotencia y concurrencia

`POST /start` toma un row lock de Investigation. Dos requests concurrentes quedan serializados y
la constraint única protege la creación aun ante un error de implementación. En `PENDING` o
`RUNNING`, repetir start vuelve a publicar únicamente tasks pendientes; en estados terminales
devuelve 409.

El claim guarda `active_celery_task_id`. Una entrega diferente no puede ejecutar una task que ya
está RUNNING. Una redelivery con el mismo ID puede continuar sin incrementar `attempts`. Las tasks
COMPLETED, FAILED o CANCELLED se ignoran.

La publicación ocurre después del commit para que el worker nunca observe trabajo inexistente. No
hay transactional outbox en esta fase: si Redis rechaza la publicación, la API devuelve 503 y la
task permanece PENDING; repetir `/start` recupera la publicación.

Todos los paths que bloquean más de una fila respetan el orden Investigation y luego ResearchTask,
reduciendo el riesgo de deadlocks entre cancelación, retry y finalización.

## Retry y fallos

El retry de dominio se solicita con `POST /api/research-tasks/{id}/retry`. Sólo admite tasks FAILED
y exige `attempts < RESEARCH_TASK_MAX_ATTEMPTS`. El default tres significa una ejecución inicial y
hasta dos ejecuciones posteriores. El retry conserva primer start, attempts y último error, limpia
resultado/completion/job activo y vuelve a PENDING.

Los retries de infraestructura son distintos: un error transitorio de conexión SQLAlchemy puede
usar `Task.retry` de Celery hasta `CELERY_TRANSPORT_MAX_RETRIES`, conservando el mismo intento de
dominio. Un fallo determinista del executor se persiste y no dispara retry automático.

## Cancelación, agregación y progreso

Cancelar marca la Investigation como CANCELLED y cancela inmediatamente sus tasks PENDING. Las
RUNNING consultan cooperativamente PostgreSQL durante el fake delay y antes de persistir. La
finalización vuelve a bloquear el aggregate; un resultado tardío nunca puede reemplazar CANCELLED.

La política agregada es única:

- antes del primer claim, trabajo pendiente implica PENDING;
- después del primer claim, cualquier trabajo no terminal mantiene RUNNING;
- todas completed producen COMPLETED;
- completed y failed terminales producen PARTIAL;
- sin éxitos y todas failed producen FAILED;
- CANCELLED siempre se conserva.

El progreso cuenta tasks terminales (`COMPLETED`, `FAILED`, `CANCELLED`) sobre el total y trunca a
porcentaje entero. Un plan sin tasks informa `percent=0`.

Los logs JSON admiten `investigation_id`, `research_task_id`, `celery_task_id`, `task_type` y
`status`. La consulta original no se registra.
