# Viva Notes — Smart Energy Consumption Forecasting & Load Optimization System

## 1. Project overview (plain English)
Electricity is cheaper at some hours than others. Many utilities charge extra during the evening "peak" (here 18:00–22:00) and less at night. This project takes a list of appliances (power in watts, hours used per day, usual start hour, and whether the use can be moved), fetches the real 7-day weather for the city, and then:
1. forecasts daily and 30-day energy use (hot weather → more cooling),
2. computes the monthly bill under a tiered + Time-of-Use tariff,
3. builds a schedule that moves flexible loads (EV charger, geyser, washing machine, pumps…) out of the peak window,
4. reports peak-kW reduction, money saved and CO₂ avoided,
5. asks an AI model (Groq) to write friendly, tailored advice — or uses fixed rules if no key is set.

## 2. Architecture & data flow
```
Browser (HTML/CSS/JS, SVG chart)
   │  POST /api/forecast  (NDJSON stream: start → node → result | error)
   ▼
Starlette (app/main.py) ── SQLite smart_energy.db (WAL): settings, rate_limit, forecasts
   ▼
app/pipeline.py
  Node 1  Appliance Log & City Gatekeeper   (4 s)  validate rows + Open-Meteo geocoding → lat/lon/country/timezone
  Node 2  7-Day Weather Telemetry           (5 s)  Open-Meteo hourly temperature + solar radiation → cooling_degree_factor
  Node 3  Bill & Peak-Load Shaving Engine          app/energy.py: hourly kW curves, tiered+ToU bill, shifting, CO₂
  Node 4  Groq Load-Optimization Strategist (18 s) one JSON call, max_tokens=900, model fallback chain, rules fallback
  Node 5  Report & SQLite Persistence              save forecast, return everything for the 3 UI tabs
```
Step by step:
1. The user picks a preset / edits the table / uploads a CSV. The browser sends city + rows.
2. The server reserves one request in the rate-limit table (15 per rolling hour). If the city is unknown or the input invalid, the request is refunded.
3. Node 2 turns a week of temperatures into a **cooling_degree_factor** = clamp(0.80 + 0.06·(avg °C − 22) + 0.05·(solar/800), 0.7, 1.6). Cooling appliances run `hours × factor` hours (capped at 24).
4. Node 3 spreads each appliance's hours over a 24-slot kW curve starting at its start hour, sums them (baseline), then optimizes.
5. Shiftable loads that touch 18–22h are re-placed (greedy, biggest first) into the slot that avoids the peak window, keeps the total curve low and is cheapest. Non-shiftable cooling gets **pre-cooling**: 40% of its peak-hour energy moves to 16–18h (with a 5% loss penalty).
6. The bill = tiered slab charge on total kWh + (peak kWh × surcharge) − (off-peak kWh × credit) + fixed charge. Carbon uses a grid factor (India 0.82 kg/kWh) with evening-peak ×1.2 and night ×0.9.
7. The result streams back; the UI draws the baseline-vs-optimized chart, schedule, comparison and report.

## 3. Ten likely viva questions

**1. What problem does the project solve?**
It helps households and small facilities cut their electricity bill and peak demand by shifting flexible appliances away from expensive evening hours, using real weather to make the forecast realistic.

**2. Why is the main calculation not done by AI?**
Bills and kWh must be exact and repeatable, so Node 3 is plain deterministic Python. The AI (Node 4) only writes advice text, and the system still works without it.

**3. How does weather change the forecast?**
Open-Meteo gives hourly temperature and solar radiation for 7 days. Hotter/sunnier weeks raise the `cooling_degree_factor`, so ACs run longer; cold weeks raise a heating factor for geysers/heaters.

**4. What is a Time-of-Use (ToU) tariff?**
A tariff where price depends on the hour. Here 18:00–22:00 adds a surcharge per kWh and 22:00–06:00 gives a credit, on top of tiered slab pricing where higher usage costs more per unit.

**5. How are loads shifted?**
Only appliances marked "shiftable" that overlap the peak window move. A greedy search tries every start hour that avoids the peak, and picks the one that keeps total peak kW low and the ToU cost lowest, with a small bias to stay near the original time.

**6. What is pre-cooling?**
Air conditioning can't simply be moved, so we cool the room a little extra at 16:00–18:00 and reduce running during the peak. We model it as moving 40% of peak-hour energy earlier, with 5% extra loss.

**7. Which AI model is used and what if it fails?**
Groq only: `openai/gpt-oss-120b` first, then `qwen/qwen3.8-27b`, then `llama-3.3-70b-versatile`. If no key is set or all calls fail/time out (18 s), deterministic energy-audit rules produce the advice. The debug panel shows the model and a "(fallback)" badge.

**8. How is the 15-per-hour limit enforced?**
Server-side in SQLite: each request inserts a timestamp; entries older than 3600 s are deleted; if 15 remain, the request is rejected (HTTP 429). A failed city lookup deletes the row (refund).

**9. Why stream NDJSON?**
Each pipeline step sends a JSON line as soon as it finishes, so the UI shows live progress, a 0.1 s timer and per-node timings without waiting for the whole run.

**10. What are the limitations?**
Tariffs are illustrative, not real utility rates; usage is modeled as steady daily patterns; the weather effect is a simple linear factor; the CO₂ peak/off-peak multipliers are assumptions. Outputs are educational estimates, not financial advice.

## 4. Standard project contract (added)
- **Settings** live in `.env` (template: `.env.example`, read by `app/config.py`): port `8005` (= 8000 + project number 5), Groq models, upload limit. Every setting has a default in code.
- **Standard routes:** `GET /health`, `GET /api/info`, `GET /api/samples`, `GET /api/samples/{id}` (saved result, instant, no AI call), `GET/POST /api/keys`, `DELETE /api/keys/groq`. Errors are always `{"error": "...", "code": "..."}`.
- **Groq only:** `app/groq_client.py` has timeouts, up to 3 attempts per model with exponential backoff on 429/5xx/timeouts, a fallback model (`GROQ_FALLBACK_MODEL`) and plain-English errors. A key must start with `gsk_` and not be the placeholder; otherwise the app treats it as "no key" and uses the deterministic rules.
- **Key safety:** keys can only be saved from the same machine (no `X-Forwarded-For`), and the full key is never sent back to the browser (masked `gsk_…abcd`).
- **Samples:** `samples/*.csv` are the four presets; `samples/results/*.json` are saved outputs of real pipeline runs (`scripts/generate_samples.py`). Re-run that script with a Groq key saved to refresh them with AI advice.
- **Hourly limit:** the 15 forecasts/hour sliding window stays; failed runs are refunded.
- **Windows safety:** the server runs through `python -m uvicorn`, and all dependencies are pure Python (no blocked compiled DLLs).
- **Hosted-demo support:** the same code can run behind a signed-ticket gate (`app/tickets.py`) with per-ticket run counts and 24-hour private history. It is off by default and not needed for the student version.
