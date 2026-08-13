# Demo pública gratuita en Render

## Arquitectura

`render.demo.yaml` es un Blueprint independiente para portfolio. No reemplaza a `render.yaml` ni a
la arquitectura normal de staging/production.

| Recurso | Tipo Render | Plan | Rol en demo |
| --- | --- | --- | --- |
| `tracelink-demo-web` | Web Service | `free` | Next.js público y proxy same-origin de `/api` |
| `tracelink-demo-api` | Web Service | `free` | FastAPI público y dispatcher demo serial |
| `tracelink-demo-db` | PostgreSQL 17 | `free` | Datos de aplicación y outbox persistente |
| `tracelink-demo-redis` | Key Value | `free` | Cache, rate limiting y readiness; datos efímeros |

Los Web Services free no pueden recibir tráfico privado desde otro Web Service free. Por eso Next
usa la URL HTTPS pública que Render asigna al API. PostgreSQL y Key Value sí usan sus connection
strings internas. Los nombres y el grupo de secretos son exclusivos de demo y no colisionan con
staging.

No hay Private Service, Background Worker ni Cron Job. Celery y el outbox productivos permanecen
intactos en el proyecto.

## Procesamiento degradado de trabajos

El API sólo inicia el dispatcher interno cuando se cumplen simultáneamente `APP_ENV=demo` y
`DEMO_MODE=true`. Cualquier otro emparejamiento hace fallar la validación de configuración; staging
y production no pueden activarlo accidentalmente.

Las rutas siguen escribiendo eventos en el outbox dentro de la misma transacción de PostgreSQL. El
dispatcher demo toma un evento por vez y ejecuta una allowlist cerrada de las tareas async existentes:

- research;
- extracción de entidades;
- extracción de relaciones;
- indexado para retrieval;
- generación de reports.

El evento se marca `PUBLISHED` después de completar, no antes. Los errores conservan attempts,
backoff y lease en PostgreSQL. Un reinicio puede producir una entrega at-least-once, por lo que se
mantienen los guards e idempotencia ya usados por Celery. Redis no contiene el estado canónico de
los trabajos.

Este modo es deliberadamente serial y de baja capacidad. Cuando el API duerme, se redespliega o se
reinicia, el dispatcher se pausa; los eventos pendientes continúan almacenados en PostgreSQL y se
retoman al despertar. No usar este modo para production.

## Provisionado

1. En Render, crear un Blueprint desde el repositorio y seleccionar expresamente
   `render.demo.yaml` como Blueprint Path. No vincular estos recursos también a `render.yaml`.
2. Revisar que los cuatro recursos indiquen plan `free` y que auto-deploy esté deshabilitado para
   ambos Web Services.
3. Cargar manualmente `OPENAI_API_KEY` cuando Render lo solicite por el campo `sync: false`. No
   guardar la clave en Git, logs, screenshots ni variables `NEXT_PUBLIC_*`.
4. Aplicar el Blueprint. El API ejecuta `alembic upgrade head` antes de iniciar Uvicorn, porque los
   pre-deploy commands no están disponibles en Web Services free.
5. Esperar a que `/api/health/ready` del API y `/` del frontend estén saludables. Abrir primero el
   frontend, registrar un usuario distinto por visitante y realizar un smoke autenticado.

Alembic habilita `vector` y `pg_trgm`; ambas extensiones están disponibles en Render PostgreSQL 17.
Los secretos JWT y pepper se generan en un grupo exclusivo y el token de métricas también se genera
en Render.

En una resincronización, Render no vuelve a pedir variables `sync: false`. Si se agrega o pierde la
clave, configurarla manualmente en Environment del servicio `tracelink-demo-api` y redesplegarlo.

## Funciones disponibles y limitadas

| Función | Estado en demo |
| --- | --- |
| Register/login y sesiones | Funcional; auth, CSRF y cookies seguras siguen activos |
| Investigations y workspace | Funcional |
| URL ingestion | Funcional para URLs públicas permitidas por los controles SSRF |
| Entities, Relationships, Evidence y Graph | Funcional después de procesar documentos |
| Search y Ask | Funcional con documentos indexados y OpenAI disponible |
| Reports | Funcional de forma serial con evidencia suficiente y OpenAI disponible |
| `DOMAIN_LOOKUP` | Usa el conector RDAP real existente cuando la query es un dominio válido |
| `WEB_SEARCH` / `PUBLIC_MENTIONS` | `skipped`: no existe un provider real de búsqueda configurado |
| `IDENTIFY_ENTITY` | `skipped` con la limitación diferida que ya declara el backend |

No se crean providers nuevos ni se habilitan providers fake. Los providers de embeddings y LLM se
fijan en `openai`, y el API no arranca sin una clave no vacía. Ask y Reports pueden abstenerse o
fallar de forma explícita cuando no hay evidencia suficiente o OpenAI no está disponible.

## Cold starts y límites gratuitos

Render puede dormir un Web Service free después de 15 minutos sin tráfico. El primer acceso puede
tardar aproximadamente un minuto por servicio; al despertar primero Next y luego FastAPI, el inicio
completo puede tardar más. El cliente demo espera hasta 90 segundos por el API, mantiene el estado
de carga y ofrece un mensaje con retry manual. Las mutaciones no se reintentan automáticamente para
evitar duplicados.

Límites relevantes del free tier:

- los Web Services del workspace comparten 750 instance-hours por mes y pueden ser suspendidos al
  agotarlas;
- PostgreSQL tiene 1 GB, no ofrece backups y vence 30 días después de crearse; tras el período de
  gracia Render elimina la base si no se actualiza a un plan pago;
- sólo se permite una base PostgreSQL free y un Key Value free por workspace;
- Key Value no persiste en disco y pierde todos sus datos al reiniciarse;
- filesystem local, ancho de banda y pipeline minutes también tienen límites.

Consultar la documentación vigente de [recursos gratuitos](https://render.com/docs/free),
[Blueprints](https://render.com/docs/blueprint-spec) y
[extensiones PostgreSQL](https://render.com/docs/postgresql-extensions) antes de recrear la demo.

El costo esperado de infraestructura Render es USD 0 mientras todos los recursos permanezcan en
plan `free` y dentro de las cuotas. El consumo de la API de OpenAI se factura por separado en la
cuenta propietaria de `OPENAI_API_KEY`. Configurar alertas/límites de gasto en ambos proveedores.

## Seguridad conservada

- El API es público por necesidad del free tier, pero todos los recursos de usuario siguen
  requiriendo autenticación y ownership.
- CORS acepta únicamente el origen HTTPS exacto de `tracelink-demo-web`; TrustedHost acepta el
  hostname exacto del API y loopback para el healthcheck del contenedor.
- Permanecen activos CSRF, security headers, límites de body, rate limits y aislamiento cross-user.
- PostgreSQL y Key Value tienen bloqueado el acceso público mediante `ipAllowList: []`.
- `REGISTRATION_ENABLED=true` es intencional para la demo; no implica bypass de auth.
- El Blueprint no contiene secretos y auto-deploy permanece apagado.

## Apagar o eliminar la demo

Para una pausa temporal, suspender manualmente ambos Web Services desde Render. Para eliminarla:

1. exportar previamente cualquier dato que se quiera conservar; la DB free no tiene backups;
2. eliminar el Blueprint demo o sus dos Web Services desde el Dashboard;
3. eliminar `tracelink-demo-redis` y `tracelink-demo-db`, confirmando que sólo sean los recursos con
   prefijo `tracelink-demo-`;
4. borrar `OPENAI_API_KEY` del servicio y revocar/rotar esa clave en OpenAI si era exclusiva de la
   demo;
5. comprobar que los recursos staging/production continúen asociados únicamente a `render.yaml`.

Eliminar estos recursos borra definitivamente los datos de la demo y no modifica la configuración
versionada del proyecto.
