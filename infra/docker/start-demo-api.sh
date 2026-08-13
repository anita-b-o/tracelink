#!/bin/sh
set -eu

echo "Starting migrations"
alembic upgrade head
echo "Migrations complete"
echo "Starting uvicorn"
exec uvicorn tracelink.main:app --host 0.0.0.0 --port "${PORT:-8000}"
