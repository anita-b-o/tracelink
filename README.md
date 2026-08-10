# TraceLink

TraceLink será un sistema web de investigación OSINT asistida por IA para due diligence de
empresas y personas. Su principio central es que cada entidad, relación y conclusión debe poder
rastrearse hasta evidencia pública o aportada legalmente por el usuario.

Este repositorio contiene únicamente la **Fase 0**: el entorno técnico ejecutable. Todavía no
incluye investigaciones, usuarios, conectores, extracción de entidades, RAG ni llamadas a LLM.

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
PostgreSQL usa una imagen con pgvector disponible; la extensión y las tablas se crearán mediante
migraciones en la Fase 1.

## Requisitos

- Docker 24 o superior con Docker Compose v2.
- Para desarrollo nativo opcional: Node.js 22, npm 11.6.2 y Python 3.12.

## Inicio rápido con Docker

```bash
cp .env.example .env
docker compose up --build --wait
```

Servicios disponibles:

- Frontend: <http://localhost:3000>
- API: <http://localhost:8000>
- OpenAPI: <http://localhost:8000/docs>
- Liveness: <http://localhost:8000/api/health/live>
- Readiness: <http://localhost:8000/api/health/ready>

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
alembic current
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

## Limitaciones actuales

- No existe modelo de dominio ni autenticación.
- Alembic está configurado, pero no hay migraciones de negocio.
- Celery arranca sin tareas registradas.
- pgvector está disponible en PostgreSQL, pero todavía no se crea ni utiliza la extensión.
- No hay conectores, procesamiento documental, IA, RAG, grafo ni workflows E2E.

Consultá [la arquitectura](docs/architecture.md) para los límites definidos para las próximas
fases.
