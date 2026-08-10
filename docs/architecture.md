# Arquitectura de TraceLink

## Estado actual

La Fase 2 conserva el monorepo Docker-first y el backend como monolito modular. El core domain
persistente ahora incluye un workflow de Investigation ejecutable con tareas de research
simuladas. El frontend sigue limitado al estado de servicios.

```text
Navegador
   │
   ├── Next.js :3000
   │      └── consulta de disponibilidad
   │
   └── FastAPI :8000
          ├── PostgreSQL 17 + pgvector (estado y resultados)
          └── Redis 7 ── Celery worker ── FakeResearchExecutor
```

## Límites del sistema

- **Frontend:** presentación y estado de interacción. No contiene reglas de investigación.
- **API:** contratos HTTP, validación de entrada y composición de casos de uso.
- **Dominio:** reglas, enums, normalización y grafo persistente sin depender de FastAPI, Celery ni
  proveedores externos. El detalle está en [data-model.md](data-model.md).
- **Persistencia:** SQLAlchemy, PostgreSQL, Redis y migraciones Alembic.
- **Research connectors:** adaptadores de fuentes públicas detrás de una interfaz común; se
  incorporarán en la Fase 3.
- **Document processing y AI:** extracción, resolución, embeddings y generación grounded; se
  incorporarán sólo cuando sus etapas sean ejecutables y auditables.
- **Jobs:** Celery actúa como límite asíncrono y ejecuta ResearchTasks simuladas. El lifecycle async
  de SQLAlchemy se concentra en un runner por proceso worker.

El backend seguirá siendo un único artefacto desplegable. Los módulos se separarán por
responsabilidad y no como microservicios. PostgreSQL será la fuente de verdad; Redis se limita a
broker, resultados transitorios, coordinación y cache.

## Operación local

Compose es la interfaz canónica de desarrollo. Las imágenes de desarrollo usan bind mounts y hot
reload; las etapas de producción generan artefactos sin herramientas de test. Los healthchecks
distinguen proceso vivo de dependencias listas:

- `/api/health/live` no toca infraestructura.
- `/api/health/ready` verifica PostgreSQL y Redis y devuelve el estado de cada componente.
- El worker responde a un `inspect ping` dirigido a su hostname.

La configuración entra por variables de entorno validadas con Pydantic. Los logs del backend y el
worker son JSON, incorporan IDs de correlación y no incluyen la consulta original ni secretos.

## Decisiones diferidas

Permisos, connectors reales, estrategia RAG y entity resolution continúan diferidos. El executor
de Fase 2 sólo produce resultados simulados y no crea datos del grafo. El esquema vectorial no fija
dimensión ni índice hasta seleccionar el modelo de embeddings en su milestone correspondiente.

El detalle del workflow, sus locks y sus políticas está en
[investigation-workflow.md](investigation-workflow.md).
