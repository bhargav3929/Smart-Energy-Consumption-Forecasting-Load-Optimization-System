# Smart Energy Consumption Forecasting & Load Optimization System

This app helps a household or small building cut its electricity bill. You give it a list of appliances (or pick a ready-made example) and a city. It downloads the real 7-day weather for that city, forecasts how many units (kWh) you will use, works out your monthly bill under a tiered + time-of-use tariff, and tells you which appliances to move out of the expensive **18:00–22:00 evening peak**. It also shows the money, peak kW and CO₂ you save. It is made for final-year students and anyone who wants to understand smart-grid demand-side management.

> Disclaimer: Predicted electricity bills and load-shifting schedules are educational estimates based on weather and tariff models and do not constitute professional utility or financial advice.

## What you need

- **Python 3.10 or newer** — download from <https://www.python.org/downloads/> (on Windows, tick "Add python.exe to PATH").
- **A free Groq key** (optional but recommended) — get one in about 1 minute, no card needed: <https://console.groq.com/keys>. Without a key the app still works and uses built-in energy-audit rules instead of AI advice.
- An internet connection (for the weather and for installing packages the first time).

## Run it (one command)

- **macOS / Linux:** `chmod +x start.sh && ./start.sh`
- **Windows:** double-click `start.bat`

The script creates a private Python environment, installs the packages, creates a `.env` file for you, starts the server and opens your browser at **http://127.0.0.1:8005**. Running it again is fast and safe. Close the terminal window (or press Ctrl+C) to stop.

## Add your Groq key

Click **API Keys** in the app, paste your key (it starts with `gsk_`), press **Test Key**, then **Save**. Or open the `.env` file and set `GROQ_API_KEY=gsk_...`, then restart.

## How to use it

1. Click one of the four **presets** (for example "3BHK Smart Household — Hyderabad"). Press **View saved result for this preset** to see a finished forecast instantly.
2. Press **Run Forecast & Optimize** to run it live. You can watch the 5 steps finish one by one.
3. Open the three tabs: **Monthly Bill & Peak Schedule**, **Scenario & Facility Compare** and **Load Reduction Report**.
4. Now try your own data: edit the appliance table, or upload a CSV/JSON file, then type your city and run again.
5. Open **Forecast History** to reopen or delete earlier forecasts.

Your own CSV looks like this (`peak_hour` is the hour 0–23 when the appliance normally starts):

```
appliance,watts,hours_per_day,peak_hour,shiftable
Air Conditioner,1500,8,21,false
EV Charger,3300,4,19,true
```

You can download a sample file from the app. Ready-made examples are also in the `samples/` folder. The free plan allows **15 forecasts per hour**; the counter at the top shows how many are left.

## How it works

Input → 5 steps → AI advice → report:

1. **Gatekeeper** (`app/pipeline.py`) checks your appliance rows and finds the city's coordinates (Open-Meteo, no key needed).
2. **Weather** (`app/pipeline.py`, `app/energy.py`) downloads 7 days of temperature and sunshine and turns them into a cooling/heating factor.
3. **Bill & peak engine** (`app/energy.py`) builds a 24-hour load curve, applies the tariff, and moves shiftable loads out of the 18:00–22:00 peak.
4. **Groq strategist** (`app/groq_client.py`) asks the Groq AI for tailored advice. It retries when Groq is busy and falls back to a second model, then to built-in rules, so you always get an answer.
5. **Report** (`app/db.py`) saves the forecast in a local SQLite file and sends everything to the page.

The bill and kWh numbers are calculated by plain Python, not by the AI, so they are repeatable.

## Project structure

```
Smart-Energy-Consumption-Forecasting-Load-Optimization-System/
├── start.sh / start.bat     one-command start
├── run.py                   alternative launcher (python run.py)
├── requirements.txt         pinned, pure-Python packages
├── .env.example             settings template (copied to .env on first run)
├── VIVA_NOTES.md            explanation and viva questions
├── app/
│   ├── main.py              web server and API routes
│   ├── config.py            settings read from .env
│   ├── pipeline.py          the 5-step forecast pipeline
│   ├── energy.py            load curves, tariff, peak shifting, CO₂
│   ├── groq_client.py       Groq calls with retry and fallback
│   ├── db.py                SQLite: key, hourly limit, history
│   ├── presets.py           the four example facilities
│   └── static/              index.html, app.js, style.css
├── samples/                 example appliance logs (.csv)
│   └── results/             saved forecast for each example (.json)
└── scripts/generate_samples.py   re-creates the samples from real runs
```

## Troubleshooting

- **Port already in use:** another program is using 8005. Close it, or change `PORT=` in `.env` (and open that port in the browser), then start again.
- **"The AI service is busy right now":** Groq's free tier is overloaded. Wait a minute and run again. The app already retried and your forecast still completes with the built-in rules.
- **"Your Groq key was rejected":** open **API Keys** and paste a fresh key from <https://console.groq.com/keys>.
- **Python not found:** install Python 3.10+ from <https://www.python.org/downloads/> and tick "Add python.exe to PATH", then run the start script again.
- **Install failed on a slow connection:** check your internet and run the start script again; it continues where it stopped.
- **"Could not find a city":** check the spelling of the city name.
- **"Hourly limit reached":** the 15-per-hour limit resets on a rolling basis; the message says how many minutes are left.
