#!/usr/bin/env sh
set -eu

exec gunicorn app:app --bind 0.0.0.0:${PORT:-8080}
