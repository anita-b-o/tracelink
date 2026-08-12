# Runbook

## Backend down

Confirmar `/api/health/live`, logs por `request_id`, configuración y memoria. Si live funciona pero
ready no, seguir la dependencia indicada. Reiniciar sólo después de capturar causa.

## Worker u outbox down

Comprobar `celery inspect ping`, broker y health del dispatcher. Reiniciar el proceso; los eventos
pendientes siguen en PostgreSQL. Ejecutar `maintenance diagnose` y luego `recover --apply` sólo si
hay leases/trabajos obsoletos.

## Redis down

Readiness y endpoints rate-limited fallarán con 503; Celery deja de consumir/publicar. Restaurar
Redis administrado y verificar ping/reconnect. No desactivar rate limiting.

## PostgreSQL down

Detener despliegues/migraciones, verificar proveedor, conexiones y storage. Tras recuperar,
comprobar `alembic current`, readiness y outbox. Restaurar backup únicamente con aprobación y en un
destino controlado.

## Failed migration

No iniciar workers nuevos. Guardar logs y estado Alembic, restaurar imagen anterior. Usar downgrade
sólo si fue probado y no destruye datos; en caso contrario preparar forward-fix.

## Stuck tasks / high error rate

Ejecutar diagnóstico, revisar outbox, Celery outcomes y errores agrupados por ruta. Correlacionar
con request ID; no copiar cuerpos/documentos a tickets. Aplicar recovery explícito y verificar
idempotencia.

## Rollback

Congelar releases, confirmar backup, desplegar imagen anterior en web/API/worker/outbox y hacer
smoke. Si el schema es compatible no revertirlo. Documentar timestamps, versión, causa e impacto.

