#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
[ -z "$PY" ] && { echo "Python 3.10+ is needed. Install it from https://www.python.org/downloads/ and run ./start.sh again."; exit 1; }

[ -x .venv/bin/python ] || { echo "Setting up (first run only)..."; "$PY" -m venv .venv; }
[ -f .env ] || { cp .env.example .env; echo "Created .env. You can paste your free Groq key in the app."; }
echo "Installing requirements..."
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt || { echo "Install failed. Check your internet connection and run ./start.sh again."; exit 1; }

PORT=$(grep -E '^PORT=' .env | cut -d= -f2 | tr -d '[:space:]"'"'"); PORT=${PORT:-8005}
HOST=$(grep -E '^HOST=' .env | cut -d= -f2 | tr -d '[:space:]"'"'"); HOST=${HOST:-127.0.0.1}

(
  for i in $(seq 1 60); do
    if curl -fs "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
      (open "http://127.0.0.1:$PORT" 2>/dev/null || xdg-open "http://127.0.0.1:$PORT" 2>/dev/null) && break
    fi
    sleep 1
  done
) &

echo "Open http://127.0.0.1:$PORT  (Ctrl+C to stop)"
exec .venv/bin/python -m uvicorn app.main:app --host "$HOST" --port "$PORT"
