# Research connectors

## Arquitectura

La Fase 3 incorpora adaptadores de fuentes públicas sin extracción de entidades. Los connectors
reciben DTOs Pydantic y producen `ConnectorOutput`; nunca retornan modelos SQLAlchemy.
`ResearchArtifactService` convierte esos artefactos en `Source` y `Document` dentro de la
transacción que completa el `ResearchTask`.

Los contratos se dividen en `ResearchConnector`, `SearchConnector`, `FetchConnector` y
`WebSearchProvider`. `ConnectorRegistry` resuelve por nombre o task type y rechaza mappings
duplicados. Para agregar un connector se implementa el protocolo, se registra en la composición y
se agregan fixtures sin Internet; el worker no requiere nuevas ramas.

## Connectors disponibles

- `url_ingestion`: entrada manual mediante `POST /api/investigations/{id}/sources/url`.
- `public_html`: descarga HTML, XHTML o texto plano y extrae title, texto visible, canonical,
  description, language, fecha ISO y hasta 100 links.
- `rdap`: consulta el bootstrap DNS de IANA y el servicio autoritativo. Guarda el JSON canónico
  completo como Document.
- `web_search`: usa un provider neutral, limita resultados y persiste Sources sin descargarlos. En
  `test` usa un fake determinista; sin provider real queda `skipped`.

`WEB_SEARCH` y `PUBLIC_MENTIONS` usan búsqueda; `DOMAIN_LOOKUP` usa RDAP sólo para un dominio puro;
`IDENTIFY_ENTITY` permanece diferido hasta Fase 4.

## HTTP, SSRF y uso responsable

Existe un `httpx.AsyncClient` reutilizable por proceso/loop. Los redirects se siguen manualmente y
se valida cada destino. Las respuestas se leen en streaming con límite de bytes. Sólo se
reintentan timeouts, 429, 502, 503 y 504, hasta tres intentos y con backoff acotado.

La normalización admite sólo HTTP/HTTPS, rechaza credenciales, aplica IDNA/lowercase al hostname,
quita fragmentos y puertos default, hace equivalentes el path vacío y `/`, y conserva query y
trailing slash no raíz.

Antes de cada request se resuelven A/AAAA. Si cualquier dirección no es global, la URL se rechaza.
Esto bloquea loopback, RFC1918, link-local, shared space, reserved, multicast, unspecified y
metadata cloud. La regla se repite tras redirects. No hay evasión, proxies ambientales, CAPTCHA
bypass ni browser automation.

El connector usa User-Agent identificable, limita la tasa y no realiza crawling. Antes de habilitar
una fuente específica en producción deben revisarse sus términos y robots.

## Cache, rate limiting y deduplicación

Redis conserva sólo respuestas exitosas durante `RESEARCH_CACHE_TTL_SECONDS`. La key contiene una
versión, connector y SHA-256 del input/configuración; consultas y URLs no aparecen en claro. Un hit
evita tráfico. Un error de cache degrada a miss; un error del rate limiter bloquea el request.

El rate limiter usa Lua atómico y ventanas de un segundo por connector y host/provider. Si no hay
capacidad espera al próximo bucket. Redirects y retries consumen cuota.

`Source.normalized_url` y `url_hash` forman la identidad. Un advisory lock PostgreSQL serializa
`get_or_create` sin borrar Sources legacy. Una Source puede tener versiones de Document; el
contenido se deduplica por `(source_id, content_hash)`. URLs distintas conservan Documents
separados para no perder procedencia.

Sólo se guardan status, final URL, longitud, ETag, Last-Modified y metadata normalizada. Cookies,
Authorization, headers completos y bodies nunca llegan a logs o resultados de task.

## Errores y observabilidad

Los errores públicos tienen códigos estables para timeout, rate limit, fetch, URL insegura,
content type y tamaño. El worker persiste código, mensaje sanitizado y resumen pequeño.

Los logs JSON incluyen IDs de investigación/task, connector, host, status, duración, cache hit y
retries. No incluyen API keys, query completa, URL completa ni contenido.
