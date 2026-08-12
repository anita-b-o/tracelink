# Backup y restore

`scripts/backup.sh` genera un dump PostgreSQL custom-format, SHA-256 y manifest con herramientas,
revisión Alembic y extensiones requeridas. No contiene credenciales.

```bash
DATABASE_URL='postgresql://...' BACKUP_DIR=/secure/backups ./scripts/backup.sh
```

Guardar dump, manifest y checksum en storage cifrado con retención definida fuera de la app.
Realizar al menos un backup diario y antes de migraciones; probar restore trimestralmente.

El restore exige una URL destino distinta y confirmación explícita:

```bash
RESTORE_DATABASE_URL='postgresql://target...' RESTORE_CONFIRM=RESTORE \
  ./scripts/restore.sh /secure/backups/tracelink-TIMESTAMP.dump
```

El script verifica checksum si existe manifest, crea `vector`/`pg_trgm`, restaura con
`--exit-on-error` y confirma extensiones. Después ejecutar `alembic current`, comparar con el
manifest, aplicar sólo migraciones esperadas y hacer smoke autenticado. Nunca probar un restore
sobre production.

