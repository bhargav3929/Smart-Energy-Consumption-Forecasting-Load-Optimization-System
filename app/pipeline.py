"""5-node forecasting & load-optimization pipeline. Async generator of NDJSON-ready events."""
import asyncio
import json
import time
import uuid
from datetime import datetime

import httpx

from . import db, energy, groq_client
from .presets import PRESETS

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

NODES = {
    1: "Appliance Log & City Gatekeeper",
    2: "7-Day Weather & Cooling/Heating Telemetry",
    3: "Monthly Bill & Peak-Load Shaving Engine",
    4: "Groq Load-Optimization Strategist",
    5: "Report & SQLite Persistence",
}
TIMEOUT_N1, TIMEOUT_N2, TIMEOUT_N4 = 4.0, 5.0, 18.0


def _ms(t0):
    return round((time.perf_counter() - t0) * 1000)


async def _geocode(city):
    async with httpx.AsyncClient() as c:
        r = await c.get(GEOCODE_URL, params={"name": city, "count": 1, "language": "en", "format": "json"})
        r.raise_for_status()
        res = (r.json().get("results") or [])
    if not res:
        raise LookupError(f"Could not find a city called “{city}”. Check the spelling and try again.")
    g = res[0]
    return {"name": g.get("name", city), "admin1": g.get("admin1", ""), "country": g.get("country", ""),
            "country_code": g.get("country_code", ""), "lat": g["latitude"], "lon": g["longitude"],
            "timezone": g.get("timezone", "UTC")}


async def _weather(geo):
    async with httpx.AsyncClient() as c:
        r = await c.get(FORECAST_URL, params={
            "latitude": geo["lat"], "longitude": geo["lon"], "hourly": "temperature_2m,shortwave_radiation",
            "forecast_days": 7, "timezone": "auto"})
        r.raise_for_status()
        return r.json()["hourly"]


def _daily_summary(hourly):
    days = {}
    for t, v in zip(hourly["time"], hourly["temperature_2m"]):
        if v is not None:
            days.setdefault(t[:10], []).append(v)
    return [{"date": d, "avg": round(sum(v) / len(v), 1), "max": round(max(v), 1), "min": round(min(v), 1)}
            for d, v in days.items()]


def _rule_based(rep, factors, cur):
    sched = rep["schedule"]
    actions = []
    for s in sched:
        if s["action"] == "shift":
            actions.append({"appliance": s["appliance"], "action": f"Run {s['new_window']} instead of {s['original_window']}",
                            "reason": f"Moves {s['peak_kwh_day']} kWh/day out of the 18:00–22:00 peak tariff; saves about {cur}{s['monthly_saving']:.0f}/month."})
        elif s["action"] == "precool":
            actions.append({"appliance": s["appliance"], "action": "Pre-cool 16:00–18:00, then raise set-point during peak",
                            "reason": "Thermal mass of the room carries the comfort through the expensive evening hours."})
    if not actions:
        actions.append({"appliance": "All loads", "action": "No shiftable loads touch the peak window",
                        "reason": "Mark flexible appliances as shiftable to unlock more savings."})
    hot = factors["cooling"] > 1.1
    thermo = [
        "Set cooling to 24–25 °C; each extra °C trims cooling energy by roughly 6%." if hot
        else "Weather is mild: use fans or natural ventilation before running HVAC.",
        "Pre-cool to ~23 °C between 16:00 and 18:00, then let it drift up to 26 °C during 18:00–22:00.",
        "Keep refrigeration doors sealed and defrost regularly to hold compressor duty low.",
    ]
    tips = [
        "Run EV chargers, washing machines, geysers and pumps after 22:00 on a timer or smart plug.",
        "Stagger high-wattage loads so they never start at the same minute (lowers peak kW).",
        "Cook with lids on and batch microwave/induction use outside 18:00–22:00 where possible.",
        "Check your tariff slab each month; trimming a few kWh can drop you into a cheaper tier.",
    ]
    summary = (f"Shifting flexible loads cuts peak demand by {rep['peak_reduction_pct']}% "
               f"({rep['peak_shaved_kw']} kW) and saves about {cur}{rep['savings_month']:,.0f} per month "
               f"with roughly {rep['co2_saved_kg']} kg CO₂ avoided.")
    return {"summary": summary, "actions": actions[:6], "thermostat": thermo, "tips": tips}


def _clean_ai(d, fallback):
    out = dict(fallback)
    if not isinstance(d, dict):
        return out
    if isinstance(d.get("summary"), str) and d["summary"].strip():
        out["summary"] = d["summary"].strip()[:600]
    acts = []
    for a in (d.get("actions") or [])[:6]:
        if isinstance(a, dict):
            acts.append({"appliance": str(a.get("appliance", ""))[:80], "action": str(a.get("action", ""))[:240],
                         "reason": str(a.get("reason", ""))[:300]})
    if acts:
        out["actions"] = acts
    for k in ("thermostat", "tips"):
        raw = d.get(k) or (d.get("peak_avoidance_tips") if k == "tips" else None) or []
        v = [str(x)[:300] for x in raw if x][:5] if isinstance(raw, list) else []
        if v:
            out[k] = v
    return out


async def run_pipeline(body: dict, key: str = "", tid: str = ""):
    run_id = uuid.uuid4().hex[:8]
    total_t0 = time.perf_counter()
    nodes_dbg = []
    dbg = {"run_id": run_id, "nodes": nodes_dbg, "geocode_ms": None, "weather_ms": None, "groq_ms": None,
           "groq_model": None, "groq_fallback": False, "weather_source": None, "notes": []}
    yield {"type": "start", "run_id": run_id, "nodes": [{"id": i, "name": n} for i, n in NODES.items()]}

    def running(i):
        return {"type": "node", "id": i, "name": NODES[i], "status": "running"}

    def done(i, t0, detail=""):
        ms = _ms(t0)
        nodes_dbg.append({"id": i, "name": NODES[i], "ms": ms})
        return {"type": "node", "id": i, "name": NODES[i], "status": "done", "ms": ms, "detail": detail}

    def fail(i, t0, msg, refund=False):
        return {"type": "error", "node": i, "name": NODES[i], "message": msg, "ms": _ms(t0), "refund": refund}

    # ---- Node 1 ----
    t0 = time.perf_counter()
    yield running(1)
    city_in = str(body.get("city") or "").strip()[:80]
    rows, errs = energy.normalize_rows(body.get("appliances"))
    if not city_in:
        errs.append("Enter a city so we can fetch its weather.")
    if errs:
        yield fail(1, t0, " ".join(errs), refund=True)
        return
    try:
        g0 = time.perf_counter()
        geo = await asyncio.wait_for(_geocode(city_in), TIMEOUT_N1)
        dbg["geocode_ms"] = _ms(g0)
    except LookupError as e:
        yield fail(1, t0, str(e), refund=True)
        return
    except asyncio.TimeoutError:
        yield fail(1, t0, f"City lookup timed out after {TIMEOUT_N1}s. Please retry.", refund=True)
        return
    except Exception as e:
        yield fail(1, t0, f"City lookup failed: {type(e).__name__}. Check your internet connection.", refund=True)
        return
    tariff = energy.get_tariff(geo["country_code"])
    yield done(1, t0, f"{len(rows)} appliances · {geo['name']}, {geo['country']} ({geo['lat']:.2f}, {geo['lon']:.2f}) · {geo['timezone']}")

    # ---- Node 2 ----
    t0 = time.perf_counter()
    yield running(2)
    daily, hourly = [], None
    try:
        w0 = time.perf_counter()
        hourly = await asyncio.wait_for(_weather(geo), TIMEOUT_N2)
        dbg["weather_ms"] = _ms(w0)
        factors = energy.compute_factors(hourly["temperature_2m"], hourly["shortwave_radiation"])
        daily = _daily_summary(hourly)
        dbg["weather_source"] = "open-meteo"
    except Exception as e:
        factors = {"cooling": 1.0, "heating": 1.0, "avg_temp": None}
        dbg["weather_source"] = "neutral-fallback"
        dbg["notes"].append(f"Weather unavailable ({type(e).__name__}); neutral multipliers (1.0) used.")
    weather = {**factors, "daily": daily, "cooling_degree_factor": factors["cooling"], "source": dbg["weather_source"]}
    yield done(2, t0, (f"avg {factors['avg_temp']} °C · cooling_degree_factor {factors['cooling']}" if factors.get("avg_temp") is not None
                       else "weather unavailable → neutral factor 1.0"))

    # ---- Node 3 ----
    t0 = time.perf_counter()
    yield running(3)
    rep, scenarios, bench = energy.full_report(rows, factors, tariff, PRESETS)
    yield done(3, t0, f"{rep['daily_kwh_baseline']} kWh/day · peak {rep['peak_kw_before']}→{rep['peak_kw_after']} kW · save {tariff['currency']}{rep['savings_month']:,.0f}/mo")

    # ---- Node 4 ----
    t0 = time.perf_counter()
    yield running(4)
    cur = tariff["currency"]
    rules = _rule_based(rep, factors, cur)
    strategist = {**rules, "source": "rules", "model": None, "fallback": False}
    if key:
        compact = {
            "city": f"{geo['name']}, {geo['country']}", "avg_temp_c": factors.get("avg_temp"),
            "cooling_degree_factor": factors["cooling"], "currency": cur, "peak_tariff_window": "18:00-22:00",
            "daily_kwh": rep["daily_kwh_baseline"], "monthly_bill": rep["bill_baseline"], "peak_kw": rep["peak_kw_before"],
            "optimized_peak_kw": rep["peak_kw_after"], "monthly_saving": rep["savings_month"],
            "schedule": [{"appliance": s["appliance"], "watts": s["watts"], "action": s["action"], "daily_kwh": s["daily_kwh"],
                          "original_window": s["original_window"], "new_window": s["new_window"]} for s in rep["schedule"][:8]],
        }
        msgs = [
            {"role": "system", "content": "You are an energy-audit strategist. Reply with ONE JSON object only, no markdown."},
            {"role": "user", "content": (
                "Given this household/facility forecast, write tailored load-shifting advice. JSON keys: "
                "\"summary\" (2 sentences), \"actions\" (max 6 objects with \"appliance\",\"action\",\"reason\"), "
                "\"thermostat\" (max 3 short strings on set-point changes), \"tips\" (max 4 peak-tariff avoidance tips). "
                "Be specific, concise, and consistent with the numbers.\n" + json.dumps(compact, ensure_ascii=False))},
        ]
        g0 = time.perf_counter()
        res = await groq_client.chat_json(msgs, key, budget_s=TIMEOUT_N4, max_tokens=900)
        dbg["groq_ms"] = _ms(g0)
        if res["data"]:
            strategist = {**_clean_ai(res["data"], rules), "source": "groq", "model": res["model"], "fallback": res["fallback"]}
            dbg["groq_model"], dbg["groq_fallback"] = res["model"], res["fallback"]
        else:
            dbg["ai_code"] = res.get("code")
            dbg["notes"].append("Groq unavailable → deterministic rules: " + groq_client.MESSAGES.get(res.get("code"), ""))
            dbg["notes_tech"] = "; ".join(res["errors"])[:300]
    else:
        dbg["notes"].append("No Groq key configured → deterministic energy-audit rules used.")
    yield done(4, t0, (f"Groq · {strategist['model']}" + (" (fallback)" if strategist["fallback"] else "")) if strategist["source"] == "groq"
               else "Deterministic energy-audit rules")

    # ---- Node 5 ----
    t0 = time.perf_counter()
    yield running(5)
    label = str(body.get("label") or "").strip()[:100]
    data = {
        "created_at": time.time(), "title": f"{label or 'Custom appliance log'} · {geo['name']}",
        "generated": datetime.now().strftime("%d %b %Y, %H:%M"),
        "city": geo, "currency": cur, "tariff": {k: tariff[k] for k in ("label", "slabs", "peak_surcharge", "off_discount", "fixed", "co2_kg_per_kwh")},
        "appliances": rows, "weather": weather, "energy": {k: v for k, v in rep.items() if k not in ("schedule", "per_appliance")},
        "schedule": rep["schedule"], "per_appliance": rep["per_appliance"], "scenarios": scenarios, "benchmark": bench,
        "strategist": strategist, "debug": dbg,
    }
    fid = db.save_forecast(data, tid)
    data["id"] = fid
    dbg["total_ms"] = _ms(total_t0)
    yield done(5, t0, f"Saved forecast #{fid} to smart_energy.db")
    dbg["total_ms"] = _ms(total_t0)
    yield {"type": "result", "forecast_id": fid, "data": data}
