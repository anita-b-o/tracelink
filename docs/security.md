# Seguridad

## Controles HTTP

Las mutaciones requieren cookie CSRF y `X-CSRF-Token` iguales mediante comparación constante, más
un `Origin` exactamente incluido en `CORS_ALLOWED_ORIGINS`. Las cookies son `SameSite=Lax`,
host-only y `Secure` en staging/production. CORS admite credenciales pero nunca `*`.

Next y FastAPI emiten CSP con `frame-ancestors 'none'`, `object-src 'none'`, `base-uri 'self'` y
`form-action 'self'`, además de `nosniff`, Referrer-Policy y Permissions-Policy. HSTS se activa sólo
en production. `ALLOWED_HOSTS` limita Host.

## Límites y abuso

El backend limita cuerpos JSON a 256 KiB aun sin `Content-Length`; URL a 4096, preguntas/consultas
a 2000, filtros a 500, páginas a 100, offset a 10000 y grafo a 250 nodos. Connectors mantienen el
límite de respuesta de 5 MB y la protección SSRF/revalidación de redirects.

Redis aplica ventanas atómicas con `Retry-After`: login 5/min por IP+email, register 3/h por IP,
refresh 30/min por sesión+IP, Ask 20/min, reportes 6/h, URL ingestion 20/h y start 10/h por usuario.
Si Redis falla, esos endpoints devuelven 503.

## Configuración y secretos

`APP_ENV` es `development`, `test`, `staging` o `production`; `ENVIRONMENT` sólo es alias temporal.
Staging/production fallan al iniciar ante CORS no HTTPS, wildcard, cookies inseguras, secretos de
auth iguales/débiles, registro no decidido, seed E2E o modos fake. Providers fake requieren
`DEMO_MODE=true` explícito. Claves de backend nunca usan prefijo `NEXT_PUBLIC_`.

Los logs no deben incluir passwords, cookies, JWT, consultas ni documentos. Los eventos de
seguridad usan email hasheado/truncado y request ID. Los errores de producción devuelven mensajes
seguros y un `error_id` correlacionable.

## Verificación

CI ejecuta Ruff/mypy/pytest, ESLint/TypeScript/Vitest/build, `pip-audit`, `npm audit`, Bandit y
gitleaks. Semgrep se omite: Bandit más tests focalizados cubren el código Python actual sin sumar
otro motor de reglas de bajo rendimiento marginal.

