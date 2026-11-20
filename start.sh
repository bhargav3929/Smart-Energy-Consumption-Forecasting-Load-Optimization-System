#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  python3 -m venv .venv
  ./.venv/bin/python -m pip install -r requirements.txt
fi
echo "Smart Energy Forecasting -> http://127.0.0.1:8005"
./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8005
