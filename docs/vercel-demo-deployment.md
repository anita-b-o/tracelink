# Demo gratuita en Vercel Hobby

## Estado y alcance

Esta adaptación está aislada de Docker/Compose, Celery, el dispatcher productivo, los entornos de
staging/production y los Blueprints de Render. No reemplaza ninguno de esos caminos.

La arquitectura elegida usa dos proyectos Vercel conectados al mismo repositorio:

```text
browser
  -> tracelink-demo-web.vercel.app/api/* (Next.js Route Handler, same-origin)
  -> tracelink-demo-api.vercel.app/api/* (una Vercel Function FastAPI)
  -> Neon PostgreSQL pooled + Upstash Redis TLS
```

No se usa Vercel Services. Vercel Queues fue evaluado primero, pero sigue en Beta, su flujo push
documentado se integra mediante un consumer Node.js y adoptarlo obligaría a crear otro puente entre
el outbox Python y el pipeline existente. Para esta demo el cambio no compensa el acoplamiento ni
la reescritura. Tampoco se usa Vercel Cron: en Hobby sólo puede ejecutarse una vez al día y no sirve
como dispatcher frecuente.

Referencias oficiales: [FastAPI en Vercel](https://vercel.com/docs/frameworks/backend/fastapi),
[Queues](https://vercel.com/docs/queues), [Cron en Hobby](https://vercel.com/docs/cron-jobs/usage-and-pricing)
y [límites Hobby](https://vercel.com/docs/plans/hobby).

## Procesamiento serverless degradado

`apps/backend/app.py` es solamente el entrypoint Vercel. Exporta la misma instancia `app` de
`tracelink.main`, con sus routers, middleware, auth, ownership, respuestas 404 cross-user,
observabilidad y servicios existentes. El adaptador activa `TRACELINK_SERVERLESS=true`; el lifespan
no inicia el loop de `demo_dispatcher.py` en ese modo.

Las mutaciones continúan escribiendo eventos en el outbox dentro de la transacción PostgreSQL. Los
GET de polling que la UI ya hace sobre una Investigation, sus tasks o reports ejecutan como máximo
un `dispatch_demo_once` antes de leer el estado. Se mantienen `FOR UPDATE SKIP LOCKED`, attempts,
backoff, lease y entrega at-least-once. Cada invocación tiene timeout interno de 240 segundos; si
Vercel termina una Function, el evento `PUBLISHING` vuelve a ser elegible al vencer el lease de 360
segundos.

Consecuencias explícitas:

- sin tráfico no se procesa trabajo; el outbox lo conserva hasta que alguien abra o refresque la
  investigación/reporte;
- una vista activa avanza normalmente un evento por request de polling;
- los trabajos pueden tardar varios polls y los superiores a 240 segundos se reintentan;
- no hay garantía de latencia ni SLA y no es una arquitectura productiva;
- no se inicia Celery, un worker, un dispatcher residente ni migrations desde una Function.

## Servicios y compatibilidad

### PostgreSQL: Neon Free

Crear un proyecto Neon Free con PostgreSQL 17 y conectar **sólo el endpoint pooled** al API como
`DATABASE_URL`. El código usa `NullPool` en modo serverless; PgBouncer de Neon se ocupa del pooling
externo. Neon Free soporta pooling, PostgreSQL 17, `vector` y `pg_trgm`. Alembic conserva el RAG con
pgvector; no se elimina ni sustituye.

Para migrations usar el connection string **direct/unpooled** fuera de Vercel Functions. Neon Free
publica actualmente 0,5 GB por proyecto y 100 CU-hours mensuales por proyecto, sin límite temporal
ni tarjeta requerida. Confirmar esos valores en Dashboard antes de crear el recurso.

Referencias: [Neon Free](https://neon.com/pricing), [PostgreSQL 17 sin tarjeta](https://neon.com/blog/postgres-17),
[pooling](https://neon.com/docs/connect/connection-pooling), [pgvector](https://neon.com/docs/ai/ai-concepts)
y [pg_trgm](https://neon.com/docs/changelog/2024-01-26).

### Redis: Upstash Redis Free

Redis sigue siendo obligatorio en esta demo para rate limiting de auth/API, rate limiting de
connectors, cache de research y readiness. Auth/session y el outbox canónico permanecen en
PostgreSQL; Redis no contiene jobs durables.

Crear una base regional Upstash Redis Free y copiar su connection string TLS de Redis (protocolo
TCP, `rediss://...`) a `REDIS_URL`. No reemplazarlo por las variables REST sin cambiar el cliente:
TraceLink usa `redis.asyncio` y scripts Lua `EVAL`. El plan Free publica actualmente 256 MB, 500.000
commands/mes y 10 GB/mes de bandwidth, sin tarjeta. TLS está siempre activo; encryption at rest y
SLA no están incluidos en Free.

Referencias: [precios Upstash Redis](https://upstash.com/pricing/redis),
[seguridad](https://upstash.com/docs/redis/features/security) e
[integración Vercel](https://upstash.com/docs/redis/howto/vercelintegration).

## Variables de los proyectos

Nunca usar prefijos `NEXT_PUBLIC_` para secretos.

### `tracelink-demo-api` (Root Directory: `apps/backend`)

| Variable | Valor/acción |
| --- | --- |
| `APP_ENV` | `demo` |
| `DEMO_MODE` | `true` |
| `DATABASE_URL` | Neon pooled URL; secreto |
| `REDIS_URL` | Upstash `rediss://...`; secreto |
| `AUTH_JWT_SECRET` | aleatorio, mínimo 32 bytes; secreto |
| `AUTH_TOKEN_PEPPER` | aleatorio, distinto, mínimo 32 bytes; secreto |
| `CORS_ALLOWED_ORIGINS` | origen HTTPS exacto del frontend |
| `ALLOWED_HOSTS` | hostname exacto del API; `127.0.0.1` se agrega automáticamente |
| `COOKIE_SECURE` | `true` |
| `REGISTRATION_ENABLED` | `true` |
| `OUTBOX_BATCH_SIZE` | `1` |
| `OUTBOX_MAX_ATTEMPTS` | `3` |
| `OUTBOX_LEASE_SECONDS` | `360` |
| `SERVERLESS_DISPATCH_TIMEOUT_SECONDS` | `240` |
| `EMBEDDING_PROVIDER` | `openai` |
| `EMBEDDING_MODEL` | `text-embedding-3-small` |
| `LLM_PROVIDER` | `openai` |
| `LLM_MODEL` | `gpt-5.6-luna` |
| `OPENAI_API_KEY` | cargar manualmente como secreto server-side |
| `METRICS_BEARER_TOKEN` | aleatorio; secreto |
| `SENTRY_DSN` | opcional; secreto |
| `SENTRY_TRACES_SAMPLE_RATE` | `0` si Sentry no se usa |

`TRACELINK_SERVERLESS` no se configura en Dashboard: lo fija el entrypoint Vercel antes de importar
la aplicación. No configurar `CELERY_BROKER_URL` ni `CELERY_RESULT_BACKEND` para esta demo; no se
inicia Celery.

### `tracelink-demo-web` (Root Directory: `apps/frontend`)

| Variable | Valor/acción |
| --- | --- |
| `APP_ENV` | `production` |
| `BACKEND_INTERNAL_URL` | URL HTTPS estable de `tracelink-demo-api` |
| `NEXT_PUBLIC_DEMO_MODE` | `true` |
| `NEXT_PUBLIC_VERCEL_DEMO_MODE` | `true` |
| `NEXT_PUBLIC_GRAPH_MAX_NODES` | `250` |
| `NEXT_PUBLIC_SENTRY_DSN` | opcional; no es la clave de OpenAI |
| `NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE` | `0` si Sentry no se usa |

Para Preview, agregar el origen preview exacto a `CORS_ALLOWED_ORIGINS` antes de probar auth. No
usar `*`. El proxy reenvía cookies `Set-Cookie`, `Origin` y `X-CSRF-Token`; el navegador continúa
viendo únicamente `/api` del frontend, por lo que los access/refresh tokens siguen en cookies
HttpOnly y CSRF no pasa a localStorage.

## Migrations explícitas

No hay migration hook en Functions. Antes del primer deploy que reciba tráfico:

1. crear la base Neon y obtener el connection string direct/unpooled;
2. desde un checkout confiable con las dependencias backend instaladas, entrar a `apps/backend`;
3. exportar temporalmente `DATABASE_URL` con la URL direct y ejecutar `alembic upgrade head`;
4. comprobar con SQL `SHOW server_version;` y
   `SELECT extname FROM pg_extension WHERE extname IN ('vector', 'pg_trgm');`;
5. borrar la variable local/historial pertinente y conservar sólo la URL pooled en Vercel.

Para despliegues futuros, repetir ese paso manual o moverlo a un job CI/release con exclusión mutua.
No ejecutar migrations en build si Preview y Production pueden construir concurrentemente.

## Orden manual en Vercel Dashboard

1. Confirmar que el uso es personal/no comercial: Hobby no permite uso comercial.
2. Crear Neon Free en una región cercana a `iad1`, elegir PostgreSQL 17 y ejecutar migrations.
3. Crear Upstash Redis Free regional con TLS. No seleccionar Pay as You Go, Fixed ni Prod Pack.
4. Importar el repositorio como proyecto `tracelink-demo-api`, Root Directory `apps/backend`.
5. Cargar las variables del API para Preview y Production, incluyendo los dos secretos auth
   distintos y `OPENAI_API_KEY`.
6. Hacer primero un Preview del API y probar `/api/health/live` y `/api/health/ready`.
7. Importar el mismo repositorio como `tracelink-demo-web`, Root Directory `apps/frontend`.
8. Cargar las variables frontend y apuntar `BACKEND_INTERNAL_URL` al alias estable del API.
9. Ajustar CORS/hosts a los dominios exactos y volver a desplegar previews si cambian.
10. Ejecutar smoke manual: register, login, crear/start Investigation, observar que los polls
    consumen el outbox, ingerir una URL pública, revisar Entities/Relationships/Evidence/Graph,
    probar Search/Ask y generar un Report.
11. Sólo después de aprobar Preview, promover manualmente cada deployment. No ejecutar
    `vercel --prod` como parte de este procedimiento automático.

## Capacidades y limitaciones Hobby

| Capability | Estado esperado |
| --- | --- |
| Register/login, cookies, CSRF y ownership | Nativo/funcional |
| Dashboard y creación de Investigation | Nativo/funcional |
| URL ingestion | Limitado por 240 s, SSRF controls y tráfico de polling |
| Entities, Relationships, Evidence, Graph | Funcional después de completar el outbox |
| Search | Funcional con pgvector/pg_trgm e indexado completo |
| Ask y Reports | Funcional con evidencia, outbox y crédito OpenAI; puede abstenerse/fallar explícitamente |
| `DOMAIN_LOOKUP` | Conserva RDAP real existente |
| `WEB_SEARCH` / `PUBLIC_MENTIONS` | `skipped`; no se configura provider real |
| Jobs sin visitas | Pendientes hasta el próximo request elegible |
| Job individual > 240 s | Timeout/reintento tras lease; no garantizado en Hobby |

Vercel Hobby incluye actualmente 4 CPU-hours, 360 GB-hours de memoria y 1 millón de invocaciones
mensuales para Functions; al agotar cuota el proyecto se pausa en lugar de comprar overage Hobby.
Las Functions Fluid de este proyecto se configuran a un máximo de 300 segundos. Los runtime logs
Hobby se conservan sólo una hora. El plan está restringido a uso personal/no comercial y no puede
conectar un proyecto Hobby a repositorios propiedad de una organización Git.

## Costos y guardrails

| Componente | Selección | Costo esperado | Riesgo de costo |
| --- | --- | --- | --- |
| Vercel | Hobby | USD 0 | pausa por cuota; no habilitar Pro/trial/add-ons |
| Neon | Free | USD 0 | no cambiar a Launch; 0,5 GB/100 CU-hours por proyecto |
| Upstash | Redis Free | USD 0 | no ingresar tarjeta ni elegir PAYG/Fixed/Prod Pack |
| OpenAI | API externa | variable y no USD 0 | tokens de embeddings, Ask, extracción y Reports |
| Sentry/dominio | opcional | depende de la cuenta | omitir para la demo USD 0 |

La API de OpenAI no tiene free tier compatible con `gpt-5.6-luna`; requiere una cuenta API con
billing/crédito disponible. Configurar project key exclusiva, límites/alertas de gasto y revisar el
Usage Dashboard. Según la documentación oficial actual, `gpt-5.6-luna` cuesta USD 1/M input tokens
y USD 6/M output tokens; `text-embedding-3-small`, USD 0,02/M input tokens. La clave debe cargarse
como environment variable server-side, nunca mostrarse ni hardcodearse.

Referencias: [modelos OpenAI](https://developers.openai.com/api/docs/models),
[text-embedding-3-small](https://developers.openai.com/api/docs/models/text-embedding-3-small) y
[autenticación de API](https://developers.openai.com/api/reference/overview#authentication).

## GO / NO-GO

**GO condicional** para una demo personal de bajo tráfico si todos los recursos se crean
explícitamente en Free/Hobby, OpenAI tiene un límite de gasto aceptado y los jobs representativos
terminan dentro de 240 segundos.

**NO-GO** para uso comercial, procesamiento autónomo sin visitantes, SLA, trabajos habituales de
más de 240 segundos, datos que superen 0,5 GB, repositorio Git propiedad de una organización sin
un camino permitido por Hobby, o requisito de encryption at rest/SLA en Redis sin pagar. En esos
casos conservar Render/Celery o usar infraestructura de workers separada; no degradar pgvector ni
activar providers fake.
