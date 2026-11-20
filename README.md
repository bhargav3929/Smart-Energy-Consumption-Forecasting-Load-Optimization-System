# Smart Energy Consumption Forecasting & Load Optimization System

A local workbench that takes a list of appliances (or a preset facility), pulls the real 7-day weather for your city, and tells you:

- how many kWh you will use per day and per 30 days (weather-adjusted),
- what your monthly bill will be under a tiered + Time-of-Use (ToU) tariff,
- which appliances to move out of the expensive **18:00–22:00 peak window**, and how much money, peak kW and CO₂ that saves.

Open `http://127.0.0.1:8005` — the workbench loads directly (no landing page).

## Highlights
- 5-node streaming pipeline (NDJSON): gatekeeper → weather → bill & peak-shaving engine → Groq strategist → SQLite report.
- **Groq only** (`openai/gpt-oss-120b`, falling back to `qwen/qwen3.8-27b`, then `llama-3.3-70b-versatile`). No key? Deterministic energy-audit rules take over.
- Server-side rate limit: **15 forecasts / hour** (SQLite, WAL), auto-refunded if the city can't be found.
- Three ways to provide data: 4 one-click presets, an editable appliance table, or a CSV/JSON upload (`appliance,watts,hours_per_day,peak_hour,shiftable`).
- Interactive 24-hour baseline-vs-optimized SVG chart, scenario/facility comparison, printable report, forecast history.
- Pure-Python dependencies only: `starlette`, `uvicorn`, `httpx`, `python-dotenv`, `python-multipart`.

## Setup (plain English)
1. Install Python 3.10 or newer.
2. Open a terminal in this folder.
3. Create a virtual environment and install packages (one time).
4. Start the server and open <http://127.0.0.1:8005>.
5. (Optional) Click **API Keys**, paste a free Groq key (`gsk_...`) from <https://console.groq.com/keys>, press **Test Key**, then **Save**. You can also put `GROQ_API_KEY=...` in a `.env` file (see `.env.example`).

Double-click `start.bat` (Windows) or run `./start.sh` (macOS/Linux) to do steps 3–4 automatically. The server always runs through `python -m uvicorn` (never `uvicorn.exe`).

Port **8005** is dedicated to this project so it never collides with 8001–8004.

## Appliance CSV format
```
appliance,watts,hours_per_day,peak_hour,shiftable
Air Conditioner,1500,8,21,false
EV Charger,3300,4,19,true
```
`peak_hour` is the hour (0–23) your appliance normally starts running. A sample file can be downloaded from the app.

## Launch commands

**Windows (PowerShell, one line):**
```powershell
python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt; .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8005
```

**macOS / Linux:**
```bash
python3 -m venv .venv && ./.venv/bin/python -m pip install -r requirements.txt && ./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8005
```

> Disclaimer: Predicted electricity bills and load-shifting schedules are educational estimates based on weather and tariff models and do not constitute professional utility or financial advice.

Run the command:

Windows (PowerShell):
python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt; .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8005

macOS / Linux (Terminal):
python3 -m venv .venv && ./.venv/bin/python -m pip install -r requirements.txt && ./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8005
