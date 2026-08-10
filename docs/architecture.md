# Arquitectura de TraceLink

## Estado actual

La Fase 1 conserva el monorepo Docker-first y el backend como monolito modular, e incorpora el
modelo persistente central. El frontend sigue limitado al estado de servicios y Celery no ejecuta
tareas de dominio.

```text
Navegador
   │
   ├── Next.js :3000
   │      └── consulta de disponibilidad
   │
   └── FastAPI :8000
          ├── PostgreSQL 17 + pgvector
          └── Redis 7 ── Celery worker
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
- **Jobs:** Celery actúa como límite asíncrono. En esta fase existe únicamente la aplicación y su
  worker, sin tareas de negocio.

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

La configuración entra por variables de entorno validadas con Pydantic. Los logs del backend son
JSON y no incluyen configuración ni secretos.

## Decisiones diferidas

Permisos, workflows ejecutables, connectors, estrategia RAG y entity resolution continúan
diferidos. El esquema vectorial no fija dimensión ni índice hasta seleccionar el modelo de
embeddings en su milestone correspondiente.
