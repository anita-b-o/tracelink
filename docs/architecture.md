# Arquitectura de TraceLink

## Estado actual

La Fase 3 conserva el monorepo Docker-first y el backend como monolito modular. El workflow de
Investigation ejecuta connectors públicos desacoplados y persiste Sources/Documents. El frontend
sigue limitado al estado de servicios.

```text
Navegador
   │
   ├── Next.js :3000
   │      └── consulta de disponibilidad
   │
   └── FastAPI :8000
          ├── PostgreSQL 17 + pgvector (estado y resultados)
          └── Redis 7 ── Celery worker ── Connector Registry
```

## Límites del sistema

- **Frontend:** presentación y estado de interacción. No contiene reglas de investigación.
- **API:** contratos HTTP, validación de entrada y composición de casos de uso.
- **Dominio:** reglas, enums, normalización y grafo persistente sin depender de FastAPI, Celery ni
  proveedores externos. El detalle está en [data-model.md](data-model.md).
- **Persistencia:** SQLAlchemy, PostgreSQL, Redis y migraciones Alembic.
- **Research connectors:** adaptadores detrás de protocolos y un registry común; su seguridad y
  operación están en [research-connectors.md](research-connectors.md).
- **Document processing y AI:** extracción, resolución, embeddings y generación grounded; se
  incorporarán sólo cuando sus etapas sean ejecutables y auditables.
- **Jobs:** Celery enruta ResearchTasks hacia connectors o no-ops controlados. SQLAlchemy y el
  cliente HTTP comparten un lifecycle por proceso worker.

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

Permisos, provider comercial de búsqueda, RAG y entity resolution continúan diferidos. Los
connectors crean Sources/Documents pero no datos del grafo. El esquema vectorial no fija dimensión
ni índice hasta seleccionar el modelo de embeddings en su milestone correspondiente.

El detalle del workflow, sus locks y sus políticas está en
[investigation-workflow.md](investigation-workflow.md).
