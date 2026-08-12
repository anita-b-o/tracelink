# Arquitectura de TraceLink

## Estado actual

La Fase 8 conserva el monorepo Docker-first y el backend como monolito modular. El workflow de
Investigation ejecuta connectors públicos, persiste Sources/Documents y encadena extracción y
resolución de entidades con extracción/validación de relaciones en jobs Celery separados. El
frontend ofrece dashboard y workspace evidence-first con tablas paginadas, timeline, React Flow,
Ask/reportes grounded y review candidato-específico.

```text
Navegador ── cookies HttpOnly + CSRF ── Next.js /api gateway
                                           │ red privada
                                           ▼
                                      FastAPI
                                    /          \
                         PostgreSQL + outbox   Redis ── Celery
```

## Límites del sistema

- **Frontend:** presentación y estado de interacción. No contiene reglas de investigación.
- **API:** contratos HTTP, validación de entrada y composición de casos de uso.
- **Dominio:** reglas, enums, normalización y grafo persistente sin depender de FastAPI, Celery ni
  proveedores externos. El detalle está en [data-model.md](data-model.md).
- **Persistencia:** SQLAlchemy, PostgreSQL, Redis y migraciones Alembic.
- **Research connectors:** adaptadores detrás de protocolos y un registry común; su seguridad y
  operación están en [research-connectors.md](research-connectors.md).
- **Document processing:** extracción y retrieval usan configuraciones de chunking separadas. El
  pipeline Celery añade embeddings y PostgreSQL ejecuta retrieval híbrido aislado por Investigation.
- **Grounding:** providers fake u OpenAI opt-in reciben contexto estructurado; citas y tenancy se
  validan fuera del modelo. Ver [rag.md](rag.md) y [grounded-reports.md](grounded-reports.md).
- **Tenancy:** `Investigation.user_id` es la raíz; autorización reusable genera filtros SQL y
  oculta recursos ajenos con 404.
- **Jobs:** una outbox transaccional elimina el corte commit/publish. Un dispatcher separado entrega
  a Celery at-least-once con IDs estables, leases y recuperación.

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

## Despliegue y decisiones diferidas

El target de referencia es Render con Next público, FastAPI privado, workers, PostgreSQL 17 y Redis
administrados. Kubernetes, microservicios, RBAC empresarial y deploy automático permanecen fuera de
alcance. Fake providers quedan para development/test o `DEMO_MODE` explícito; production falla al
iniciar ante una configuración insegura. Vector search permanece exacta hasta que volumen o
latencia justifiquen ANN.

El detalle del workflow, sus locks y sus políticas está en
[investigation-workflow.md](investigation-workflow.md).
