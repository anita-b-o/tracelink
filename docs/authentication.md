# Autenticación y sesiones

TraceLink usa autenticación email/password y cookies same-origin. Next.js actúa como gateway en
`/api`; FastAPI permanece privado en staging/production. Ningún token se guarda en
`localStorage` ni se expone a JavaScript.

## Flujo

- `GET /api/auth/csrf` entrega una cookie CSRF legible.
- `POST /api/auth/register` y `POST /api/auth/login` crean una `AuthSession` y cookies host-only.
- La cookie access contiene un JWT HS256 de 10 minutos. La cookie refresh contiene un JWT de hasta
  30 días; su hash HMAC-SHA256 con pepper es lo único persistido.
- `POST /api/auth/refresh` bloquea la sesión con `FOR UPDATE`, rota el refresh y detecta reuse. El
  reuse revoca la sesión completa.
- `POST /api/auth/logout` revoca la sesión y elimina ambas cookies.
- `GET /api/auth/me` devuelve únicamente identidad no sensible.

Los JWT fijan algoritmo, issuer y audience y requieren `sub`, `sid`, `typ`, `jti`, `iat`, `nbf` y
`exp`. Passwords de 12–128 caracteres se procesan con Argon2id mediante `pwdlib`; emails se
normalizan con trim y casefold.

## Autorización

`Investigation.user_id` es la raíz de tenancy. Las dependencias de autorización componen consultas
SQL desde cada task, source, document, entity, relationship, evidence, report y candidato hasta una
investigación del usuario. Un recurso ajeno responde `404`; una sesión ausente o inválida, `401`;
CSRF u Origin inválido, `403`.

La migración conserva filas legacy con `user_id` nullable y agrega un constraint `NOT VALID` que
impide nuevos NULL. `python -m tracelink.maintenance bootstrap-dev-user` crea de forma idempotente
el usuario configurado y asigna sólo filas legacy en development/test. Se niega a ejecutarse en
staging/production: allí el dueño debe resolverse explícitamente antes de validar el constraint.

## Frontend

`AuthProvider` evita el flash de rutas protegidas. El cliente coordina un único refresh para 401
concurrentes, reintenta una vez y redirige a `/login?reason=session_expired` si falla. Las rutas
`/login` y `/register` son públicas; `/` e `/investigations/*` requieren sesión.

