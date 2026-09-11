# Research connectors

## Arquitectura

Los adaptadores de fuentes públicas siguen sin extraer entidades dentro del connector. Reciben DTOs
Pydantic y producen `ConnectorOutput`; nunca retornan modelos SQLAlchemy. Fase 4 procesa después los
Documents persistidos.
`ResearchArtifactService` convierte esos artefactos en `Source` y `Document`, crea la asociación
`InvestigationArtifact` dentro de la transacción y, tras el commit, se encola el job de entities por
cada Document.

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
- `web_search`: usa `WebSearchProvider`; la integración productiva inicial es Brave Search. Brave
  se usa únicamente para descubrir URLs transitoriamente en memoria: limita y deduplica resultados,
  valida SSRF y descarga secuencialmente hasta `WEB_SEARCH_FETCH_LIMIT` páginas con `public_html`.
  Sólo un fetch exitoso produce Source y Document; el título, descripción, URL final, canonical,
  content type y metadata HTTP provienen de la página original. `fake` requiere selección explícita y sólo se
  admite con `APP_ENV=test`; un provider ausente o un fallo externo hace fallar la task con código
  observable. El adapter usa el endpoint, header `X-Subscription-Token` y máximo de 20 resultados
  documentados en la [referencia oficial de Brave](https://api-dashboard.search.brave.com/api-reference/web/search/get).

`WEB_SEARCH` y `PUBLIC_MENTIONS` usan el mismo provider; el segundo encierra la consulta entre
comillas para buscar menciones exactas. `DOMAIN_LOOKUP` usa RDAP sólo para un dominio puro. El
planner ya no crea `IDENTIFY_ENTITY`: la extracción corre durablemente sobre cada Document nuevo
asociado a la investigación. Una task legacy de ese tipo queda `skipped` con semántica explícita de
pipeline documental, nunca con `fake_research`.

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

Redis conserva sólo respuestas exitosas de connectors que lo habilitan durante `RESEARCH_CACHE_TTL_SECONDS`. La key contiene una
versión, connector y SHA-256 del input/configuración; consultas y URLs no aparecen en claro. Un hit
evita tráfico. Un error de cache degrada a miss; un error del rate limiter bloquea el request.

El rate limiter usa Lua atómico y ventanas de un segundo por connector y host/provider. Si no hay
capacidad espera al próximo bucket. Redirects y retries consumen cuota.

`GenericWebSearchConnector` no habilita cache para Brave: no se guarda el payload ni una
representación de sus resultados. `Source.normalized_url` y `url_hash` forman la identidad, por lo
que `WEB_SEARCH` y `PUBLIC_MENTIONS` reutilizan la misma Source cuando encuentran la misma URL.
Un advisory lock PostgreSQL serializa `get_or_create` sin borrar Sources legacy. Una Source puede
tener versiones de Document; el contenido se deduplica por `(source_id, content_hash)`, y el
outbox de entity extraction es idempotente por Document.

Brave Search API is used for transient URL discovery. Persisted evidence is derived from fetched
source pages, not from Brave Search result content.

Sólo se guardan status, final URL, longitud, ETag, Last-Modified y metadata normalizada. Cookies,
Authorization, headers completos y bodies nunca llegan a logs o resultados de task.

## Errores y observabilidad

Los errores públicos tienen códigos estables para autenticación, timeout, rate limit y respuesta
inválida del provider, además de fetch, URL insegura, content type y tamaño. Las fallas de búsqueda
marcan la task `FAILED`; una búsqueda válida con cero resultados queda `COMPLETED`. Las fallas por
página se resumen por código y preservan las Sources ya encontradas. SSRF, 4xx, contenido no
soportado y tamaño excesivo se consideran skips controlados; timeout, rate limit, 5xx y red marcan
la task `FAILED` sin descartar los artefactos parciales.

Los logs JSON incluyen IDs de investigación/task, connector, host, status, duración, cache hit y
retries. No incluyen API keys, query completa, URL completa ni contenido.
