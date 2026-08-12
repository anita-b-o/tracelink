#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL is required" >&2
  exit 2
fi

backup_dir="${BACKUP_DIR:-./backups}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup_dir"
archive="$backup_dir/tracelink-$timestamp.dump"
manifest="$archive.manifest.json"

pg_dump --format=custom --no-owner --no-acl --file="$archive" "$DATABASE_URL"
checksum="$(sha256sum "$archive" | awk '{print $1}')"
postgres_version="$(pg_dump --version | sed 's/"/\\"/g')"
alembic_revision="${ALEMBIC_REVISION:-unknown}"
if command -v alembic >/dev/null 2>&1; then
  alembic_revision="$(alembic current 2>/dev/null | head -n1 | awk '{print $1}')"
fi
printf '{"created_at":"%s","archive":"%s","sha256":"%s","postgres_tools":"%s","alembic_revision":"%s","requires_extensions":["vector","pg_trgm"]}\n' \
  "$timestamp" "$(basename "$archive")" "$checksum" "$postgres_version" "$alembic_revision" > "$manifest"
echo "Backup created: $archive"
echo "Manifest: $manifest"
