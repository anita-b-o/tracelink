# Arquitectura de TraceLink

## Estado actual

La Fase 0 establece un monorepo Docker-first y un backend desplegable como monolito modular. No
implementa aún el dominio OSINT: su objetivo es verificar que el frontend, el API, el worker y los
almacenes de datos puedan desarrollarse y probarse juntos.

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
- **Dominio:** reglas y estados de investigación; se incorporará en la Fase 1 sin depender de
  FastAPI, Celery ni proveedores externos.
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

El modelo de datos, permisos, contratos de investigación, connectors, estrategia RAG y entity
resolution se definirán en sus milestones. Se evita anticiparlos con abstracciones vacías. Los
documentos específicos de esos componentes se crearán cuando exista una implementación que
documentar.
