#!/bin/sh
set -eu

HOST="${LISTEN_HOST:-0.0.0.0}"
PORT="${LISTEN_PORT:-8080}"

exec /opt/rb-vecchi/venv/bin/gunicorn \
  --workers 1 \
  --threads 4 \
  --timeout 30 \
  --access-logfile - \
  --error-logfile - \
  --bind "${HOST}:${PORT}" \
  wsgi:app
