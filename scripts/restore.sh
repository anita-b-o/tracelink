#!/usr/bin/env bash
set -euo pipefail

archive="${1:-}"
if [[ -z "$archive" || ! -f "$archive" ]]; then
  echo "Usage: RESTORE_DATABASE_URL=... RESTORE_CONFIRM=RESTORE $0 backup.dump" >&2
  exit 2
fi
if [[ -z "${RESTORE_DATABASE_URL:-}" ]]; then
  echo "RESTORE_DATABASE_URL is required" >&2
  exit 2
fi
if [[ "${RESTORE_CONFIRM:-}" != "RESTORE" ]]; then
  echo "Set RESTORE_CONFIRM=RESTORE to confirm replacement of the target database" >&2
  exit 2
fi

manifest="$archive.manifest.json"
if [[ -f "$manifest" ]]; then
  expected="$(sed -n 's/.*"sha256":"\([0-9a-f]*\)".*/\1/p' "$manifest")"
  actual="$(sha256sum "$archive" | awk '{print $1}')"
  [[ -n "$expected" && "$expected" == "$actual" ]] || { echo "Checksum mismatch" >&2; exit 3; }
fi

psql "$RESTORE_DATABASE_URL" -v ON_ERROR_STOP=1 -c 'CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;'
pg_restore --clean --if-exists --no-owner --no-acl --exit-on-error --dbname="$RESTORE_DATABASE_URL" "$archive"
psql "$RESTORE_DATABASE_URL" -v ON_ERROR_STOP=1 -c 'SELECT extname FROM pg_extension WHERE extname IN ('"'"'vector'"'"','"'"'pg_trgm'"'"') ORDER BY extname;'
echo "Restore completed and extensions verified"
