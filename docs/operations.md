# Operaciones

## Procesos

Un release contiene Next web, FastAPI privado, Celery worker y dispatcher outbox. PostgreSQL es la
fuente de verdad; Redis presta broker, rate limiting y cache. Sólo el pre-deploy de FastAPI ejecuta
`alembic upgrade head`; workers verifican compatibilidad y nunca migran.

Liveness (`/api/health/live`) comprueba el proceso. Readiness (`/api/health/ready`) consulta DB y
Redis con timeout y no llama proveedores externos. El worker usa `celery inspect ping`; el
dispatcher actualiza `/tmp/tracelink-outbox-ready`.

## Outbox y recuperación

Los enqueues de research, ingestion, extracción, indexing y reportes se escriben en la misma
transacción del cambio de dominio. El dispatcher reclama con `FOR UPDATE SKIP LOCKED`, lease y task
ID estable. La entrega es at-least-once; consumidores son idempotentes. Reintenta con backoff,
abandona tras el máximo configurado y limpia publicados mayores a siete días.

Diagnóstico read-only:

```bash
cd apps/backend
python -m tracelink.maintenance diagnose
```

Recuperación explícita de ResearchTasks/Reports RUNNING obsoletos y leases vencidos:

```bash
python -m tracelink.maintenance recover --apply
```

## Ajustes de infraestructura

SQLAlchemy configura pool/overflow, timeout, recycle, connect timeout y statement timeout. Redis
usa connect/socket timeout, health checks y retries acotados. Celery usa prefetch 1, `acks_late`,
reject-on-worker-lost, reconnect, visibility timeout, límites soft/hard y reciclado de procesos.

Sources, Documents, Evidence y Reports se retienen indefinidamente hasta borrado explícito. Las
sesiones revocadas y outbox publicado son datos operacionales; outbox se limpia a siete días. La
retención de logs se configura en la plataforma (30 días recomendado) y debe excluir contenido.

