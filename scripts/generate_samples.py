"""Regenerate samples/*.csv and samples/results/*.json from REAL pipeline runs.
Run from the project root:  .venv/Scripts/python scripts/generate_samples.py
Uses your Groq key (saved in the app or in .env) and needs an internet connection."""
import asyncio
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.pipeline import run_pipeline  # noqa: E402
from app.presets import PRESETS  # noqa: E402


async def run_one(p):
    key, _ = db.get_groq_key()
    body = {"city": p["city"], "label": p["short"], "appliances": p["appliances"]}
    result = None
    async for ev in run_pipeline(body, key, tid="sample-gen"):
        if ev["type"] == "error":
            raise SystemExit(f"{p['id']}: {ev['message']}")
        if ev["type"] == "result":
            result = ev["data"]
    return result, key


async def main():
    db.init()
    (ROOT / "samples" / "results").mkdir(parents=True, exist_ok=True)
    for p in PRESETS:
        with open(ROOT / "samples" / f"{p['id']}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["appliance", "watts", "hours_per_day", "peak_hour", "shiftable"])
            for a in p["appliances"]:
                w.writerow([a["name"], a["watts"], a["hours_per_day"], a["peak_hour"], str(a["shiftable"]).lower()])
        result, key = await run_one(p)
        result.pop("id", None)
        (ROOT / "samples" / "results" / f"{p['id']}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print(p["id"], "->", result["strategist"]["source"], result["strategist"].get("model"))
    # remove the throw-away history rows this script created
    with db.db() as c:
        c.execute("DELETE FROM forecasts WHERE tid='sample-gen'")


if __name__ == "__main__":
    asyncio.run(main())
