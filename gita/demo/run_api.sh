#!/usr/bin/env bash
# Start the Gita RAG demo API on http://127.0.0.1:8000
# Uses system Python for the HTTP server (fast). RAG work runs in venv via ask_worker.py.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
# Prefer Homebrew/system python for the lightweight HTTP front door.
if command -v /opt/homebrew/bin/python3 >/dev/null 2>&1; then
  PY=/opt/homebrew/bin/python3
elif command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  PY=python
fi
export PYTHONUNBUFFERED=1
cd "$ROOT"
echo "HTTP server Python: $PY"
exec "$PY" api/stdlib_server.py "$@"
