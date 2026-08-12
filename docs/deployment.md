# Despliegue

## Target de referencia

El blueprint `render.yaml` define Render: Next como web service, FastAPI como private service,
Celery y outbox como workers, PostgreSQL 17 administrado con pgvector y Key Value administrado.
Auto-deploy está deshabilitado. Production nunca se despliega desde CI.

`compose.staging.yaml` valida los mismos artefactos production, sin bind mounts ni dev servers. Un
proxy/load balancer administrado termina TLS; Next es el único servicio público y reenvía `/api` al
backend privado. Debe preservar `X-Forwarded-*` y `X-Request-ID`.

`ALLOWED_HOSTS` debe enumerar el hostname privado real del API, el alias interno usado por Next y
`127.0.0.1`, reservado al healthcheck del contenedor. No se admite `*`.

## Release

1. Construir ambas etapas `production` y escanear dependencias.
2. Crear backup y verificar checksum.
3. Proveer secretos distintos para staging; decidir `REGISTRATION_ENABLED` explícitamente.
4. Ejecutar una sola vez `alembic upgrade head` como pre-deploy del backend.
5. Desplegar API, workers/outbox y web; comprobar readiness, worker y outbox.
6. Ejecutar smoke autenticado y revisar métricas/logs.

Rollback de aplicación: restaurar la imagen anterior. Downgrade de esquema sólo si la migración lo
permite y tras backup; preferir forward-fix. El blueprint no contiene secretos.

Staging real requiere cuenta Render, dominios y secretos administrados. Sin ellos su validación es
`BLOCKED`, no un PASS local. Consultar [release-checklist.md](release-checklist.md).
