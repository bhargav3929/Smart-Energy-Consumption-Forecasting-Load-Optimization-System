#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  python3 -m venv .venv
  ./.venv/bin/python -m pip install -r requirements.txt
fi
echo "Smart Energy Forecasting -> http://127.0.0.1:8005"
(sleep 2; { command -v xdg-open >/dev/null && xdg-open http://127.0.0.1:8005; } || { command -v open >/dev/null && open http://127.0.0.1:8005; } || true) >/dev/null 2>&1 &
./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8005
