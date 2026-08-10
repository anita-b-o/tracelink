# TraceLink

TraceLink será un sistema web de investigación OSINT asistida por IA para due diligence de
empresas y personas. Su principio central es que cada entidad, relación y conclusión debe poder
rastrearse hasta evidencia pública o aportada legalmente por el usuario.

El repositorio contiene la **Fase 2**: el core domain persistente y un workflow asíncrono de
investigación ejecutado por Celery con research deliberadamente simulado. Todavía no incluye
usuarios, conectores reales, scraping, extracción, RAG ni LLM.

## Arquitectura actual

El proyecto es un monorepo con un monolito modular como backend:

```text
apps/
  backend/       FastAPI, SQLAlchemy, Alembic y Celery
  frontend/      Next.js, React, TypeScript y Tailwind
infra/docker/    Imágenes de desarrollo y producción
docs/            Decisiones de arquitectura
compose.yaml     Stack local completo
```

Docker Compose levanta cinco servicios: `frontend`, `backend`, `worker`, `postgres` y `redis`.
PostgreSQL usa una imagen con pgvector. Alembic habilita la extensión y crea el modelo de dominio.

## Requisitos

- Docker 24 o superior con Docker Compose v2.
- Para desarrollo nativo opcional: Node.js 22, npm 11.6.2 y Python 3.12.

## Inicio rápido con Docker

```bash
cp .env.example .env
docker compose up --build --wait
docker compose exec backend alembic upgrade head
```

Servicios disponibles:

- Frontend: <http://localhost:3000>
- API: <http://localhost:8000>
- OpenAPI: <http://localhost:8000/docs>
- Liveness: <http://localhost:8000/api/health/live>
- Readiness: <http://localhost:8000/api/health/ready>
- Investigations: <http://localhost:8000/api/investigations>

Para ver logs o detener el entorno:

```bash
docker compose logs --follow
docker compose down
```

Usá `docker compose down --volumes` sólo cuando quieras borrar deliberadamente los datos locales
de PostgreSQL y Redis.

## Desarrollo nativo

El flujo soportado de referencia es Docker. Para ejecutar procesos fuera de contenedores, mantené
PostgreSQL y Redis activos con `docker compose up postgres redis --wait`.

Backend:

```bash
cd apps/backend
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps --editable .
uvicorn tracelink.main:app --reload
```

Frontend, en otra terminal:

```bash
cd apps/frontend
npm ci
npm run dev
```

Los valores predeterminados del backend apuntan a los puertos locales de PostgreSQL y Redis.

## Variables de entorno

`.env.example` contiene valores exclusivamente locales y no secretos de producción:

| Variable | Uso | Valor local predeterminado |
| --- | --- | --- |
| `FRONTEND_PORT` | Puerto público de Next.js | `3000` |
| `BACKEND_PORT` | Puerto público de FastAPI | `8000` |
| `POSTGRES_DB` | Base de datos local | `tracelink` |
| `POSTGRES_USER` | Usuario local | `tracelink` |
| `POSTGRES_PASSWORD` | Contraseña local | `tracelink_dev` |
| `NEXT_PUBLIC_API_URL` | URL del API visible para el navegador | `http://localhost:8000` |
| `CORS_ORIGINS` | Orígenes permitidos, separados por coma | `http://localhost:3000` |
| `LOG_LEVEL` | Nivel de logging del backend y worker | `INFO` |
| `RESEARCH_TASK_MAX_ATTEMPTS` | Máximo de ejecuciones de dominio por task | `3` |
| `FAKE_RESEARCH_DELAY_MS` | Delay base del executor simulado | `25` |
| `CELERY_TRANSPORT_MAX_RETRIES` | Retries acotados ante fallos de infraestructura | `3` |

`DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL` y `CELERY_RESULT_BACKEND` se configuran
directamente para los contenedores. Se pueden definir explícitamente al ejecutar el backend de
forma nativa.

## Checks

Backend:

```bash
cd apps/backend
ruff check .
ruff format --check .
mypy
pytest
alembic upgrade head
alembic check
```

Frontend:

```bash
cd apps/frontend
npm run lint
npm run typecheck
npm test
npm run build
```

Validación integrada:

```bash
docker compose config --quiet
docker compose up --build --detach --wait
curl --fail http://localhost:8000/api/health/ready
docker compose down
```

GitHub Actions ejecuta estos checks y un smoke test del stack. No realiza deploy.

## Troubleshooting

- Si un puerto ya está ocupado, cambialo en `.env` antes de levantar Compose.
- `docker compose ps` muestra qué servicio no alcanzó su healthcheck.
- `docker compose logs backend worker postgres redis` reúne los logs relevantes del backend.
- Si cambian dependencias, reconstruí con `docker compose build --no-cache`.

## Workflow y limitaciones

- El modelo y sus decisiones están documentados en [docs/data-model.md](docs/data-model.md).
- El workflow está documentado en
  [docs/investigation-workflow.md](docs/investigation-workflow.md).
- No existe autenticación ni asociación de registros a usuarios.
- Celery ejecuta únicamente Fake Research; PostgreSQL conserva estado, progreso y resultados.
- pgvector y `embedding_records` están preparados, pero no hay generación ni búsqueda vectorial.
- No hay conectores, procesamiento documental, IA, RAG ni datos falsos en el grafo.

Consultá [la arquitectura](docs/architecture.md) para los límites definidos para las próximas
fases.
