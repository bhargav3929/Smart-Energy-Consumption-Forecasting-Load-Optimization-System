"""Deterministic energy maths: load profiles, tiered + ToU bill, peak shaving, carbon."""
import math
import re

PEAK_HOURS = (18, 19, 20, 21)
OFF_HOURS = (22, 23, 0, 1, 2, 3, 4, 5)
DAYS = 30
PEAK_CO2_MULT = 1.20   # evening peak is served by dirtier marginal plants
OFF_CO2_MULT = 0.90

COOLING_RE = re.compile(r"\b(ac|a/c|hvac|air[- ]?condition\w*|split|cooler|cooling|chiller)\b", re.I)
HEATING_RE = re.compile(r"\b(geyser|water heaters?|heaters?|heating)\b", re.I)

TARIFFS = {
    "IN": {
        "currency": "₹", "label": "India tiered + ToU (illustrative)",
        "slabs": [(100, 3.5), (200, 5.0), (400, 7.0), (None, 8.5)],
        "peak_surcharge": 3.0, "off_discount": 1.5, "fixed": 120.0, "co2_kg_per_kwh": 0.82,
    },
    "DEFAULT": {
        "currency": "$", "label": "Generic tiered + ToU (illustrative)",
        "slabs": [(300, 0.11), (700, 0.14), (None, 0.18)],
        "peak_surcharge": 0.08, "off_discount": 0.03, "fixed": 10.0, "co2_kg_per_kwh": 0.40,
    },
}


def get_tariff(country_code: str):
    return TARIFFS["IN"] if (country_code or "").upper() == "IN" else TARIFFS["DEFAULT"]


def classify(name: str) -> str:
    if COOLING_RE.search(name):
        return "cooling"
    if HEATING_RE.search(name):
        return "heating"
    return "base"


def _truthy(v):
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "y", "t", "on")


def normalize_rows(rows):
    """Validate user rows. Returns (clean_rows, errors)."""
    clean, errors = [], []
    if not isinstance(rows, list) or not rows:
        return [], ["Add at least one appliance row."]
    if len(rows) > 40:
        return [], ["Too many rows (max 40)."]
    for i, r in enumerate(rows, 1):
        if not isinstance(r, dict):
            errors.append(f"Row {i}: invalid format.")
            continue
        name = str(r.get("name") or r.get("appliance") or "").strip()[:60]
        try:
            watts = float(r.get("watts"))
            hours = float(r.get("hours_per_day", r.get("hours")))
            ph = r.get("peak_hour", 18)
            ph = 18 if ph in (None, "") else int(float(ph))
        except (TypeError, ValueError):
            errors.append(f"Row {i} ({name or 'unnamed'}): watts, hours/day and run hour must be numbers.")
            continue
        if not name:
            errors.append(f"Row {i}: appliance name is required.")
        elif not (0 < watts <= 200000):
            errors.append(f"Row {i} ({name}): power must be between 1 and 200000 W.")
        elif not (0 <= hours <= 24):
            errors.append(f"Row {i} ({name}): hours/day must be between 0 and 24.")
        elif not (0 <= ph <= 23):
            errors.append(f"Row {i} ({name}): run hour must be 0-23.")
        else:
            clean.append({"name": name, "watts": watts, "hours_per_day": hours, "peak_hour": ph,
                          "shiftable": _truthy(r.get("shiftable", False))})
    return clean, errors


# ---------- weather ----------
def compute_factors(temps, solar):
    """temps: hourly °C list (168 pts). solar: hourly W/m² list."""
    t = [x for x in temps if x is not None]
    s = [x for x in solar if x is not None]
    if not t:
        return {"cooling": 1.0, "heating": 1.0, "avg_temp": None}
    mean_t = sum(t) / len(t)
    day_solar = [x for x in s if x > 50]
    mean_solar = sum(day_solar) / len(day_solar) if day_solar else 0.0
    cooling = min(1.6, max(0.7, 0.80 + 0.06 * (mean_t - 22) + 0.05 * (mean_solar / 800)))
    heating = min(1.5, 1 + 0.03 * (18 - mean_t)) if mean_t < 18 else 1.0
    return {"cooling": round(cooling, 3), "heating": round(heating, 3), "avg_temp": round(mean_t, 1),
            "max_temp": round(max(t), 1), "min_temp": round(min(t), 1), "avg_solar": round(mean_solar, 0)}


# ---------- profiles ----------
def _hour_rates(tariff):
    return [tariff["peak_surcharge"] if h in PEAK_HOURS else (-tariff["off_discount"] if h in OFF_HOURS else 0.0) for h in range(24)]


def _eff_hours(a, kind, factors, scale):
    mult = 1.0
    if kind == "cooling":
        mult = factors["cooling"] * scale
    elif kind == "heating":
        mult = factors["heating"]
    return min(24.0, a["hours_per_day"] * mult)


def _profile(a, hours, start=None):
    kw = a["watts"] / 1000.0
    s = a["peak_hour"] if start is None else start
    arr = [0.0] * 24
    full = int(hours + 1e-9)
    frac = hours - full
    for i in range(full):
        arr[(s + i) % 24] += kw
    if frac > 1e-6:
        arr[(s + full) % 24] += kw * frac
    return arr


def _window(start, hours):
    n = max(1, math.ceil(hours - 1e-9))
    return f"{start:02d}:00–{(start + n) % 24:02d}:00"


def bill(month_kwh, peak_kwh, off_kwh, t):
    energy, prev, remaining = 0.0, 0, month_kwh
    for upto, rate in t["slabs"]:
        if remaining <= 0:
            break
        span = remaining if upto is None else min(remaining, upto - prev)
        energy += span * rate
        remaining -= span
        if upto is not None:
            prev = upto
    tou = peak_kwh * t["peak_surcharge"] - off_kwh * t["off_discount"]
    total = energy + tou + t["fixed"]
    return {"energy": round(energy, 2), "tou": round(tou, 2), "fixed": t["fixed"], "total": round(total, 2)}


def _sum(curves):
    return [sum(c[h] for c in curves) for h in range(24)]


def _co2(curve, ef):
    tot = 0.0
    for h, v in enumerate(curve):
        m = PEAK_CO2_MULT if h in PEAK_HOURS else (OFF_CO2_MULT if h in OFF_HOURS else 1.0)
        tot += v * ef * m
    return tot * DAYS


def analyze(appliances, factors, tariff, cooling_scale=1.0, optimize=True):
    rates = _hour_rates(tariff)
    items = []
    for a in appliances:
        kind = classify(a["name"])
        hrs = _eff_hours(a, kind, factors, cooling_scale)
        items.append({"a": a, "kind": kind, "hours": hrs, "base": _profile(a, hrs), "new": None, "start": a["peak_hour"],
                      "action": "keep", "pre": 0.0})
    base_curve = _sum([it["base"] for it in items])
    for it in items:
        it["new"] = list(it["base"])

    if optimize:
        # 1) shift shiftable loads that touch the peak window to the cheapest, flattest slot
        movable = [it for it in items if it["a"]["shiftable"] and any(it["base"][h] > 0 for h in PEAK_HOURS)]
        movable.sort(key=lambda it: -it["a"]["watts"])
        for it in movable:
            n = max(1, math.ceil(it["hours"] - 1e-9))
            if n > 18:
                continue
            others = [x["new"] for x in items if x is not it]
            rest = _sum(others) if others else [0.0] * 24
            best = None
            for s in range(24):
                if any(((s + i) % 24) in PEAK_HOURS for i in range(n)):
                    continue
                prof = _profile(it["a"], it["hours"], s)
                curve = [rest[h] + prof[h] for h in range(24)]
                tou = sum(prof[h] * rates[h] for h in range(24))
                dist = min((s - it["a"]["peak_hour"]) % 24, (it["a"]["peak_hour"] - s) % 24)
                cost = max(curve) * 50 + tou + dist * 0.01
                if best is None or cost < best[0]:
                    best = (cost, s, prof)
            if best:
                it["new"], it["start"], it["action"] = best[2], best[1], "shift"
        # 2) pre-cool: move 40% of remaining peak-hour cooling load into 16:00-18:00 (+5% loss)
        for it in items:
            if it["kind"] != "cooling" or it["action"] == "shift":
                continue
            peak_kwh = sum(it["new"][h] for h in PEAK_HOURS)
            if peak_kwh <= 0:
                continue
            moved = peak_kwh * 0.40
            per_peak = moved / len(PEAK_HOURS)
            for h in PEAK_HOURS:
                it["new"][h] -= per_peak
            for h in (16, 17):
                it["new"][h] += moved * 1.05 / 2
            it["action"], it["pre"] = "precool", moved

    opt_curve = _sum([it["new"] for it in items])
    daily_b, daily_o = sum(base_curve), sum(opt_curve)
    pk_b = sum(base_curve[h] for h in PEAK_HOURS) * DAYS
    pk_o = sum(opt_curve[h] for h in PEAK_HOURS) * DAYS
    off_b = sum(base_curve[h] for h in OFF_HOURS) * DAYS
    off_o = sum(opt_curve[h] for h in OFF_HOURS) * DAYS
    bill_b = bill(daily_b * DAYS, pk_b, off_b, tariff)
    bill_o = bill(daily_o * DAYS, pk_o, off_o, tariff)
    peak_b, peak_o = max(base_curve), max(opt_curve)

    schedule = []
    for it in sorted(items, key=lambda x: -sum(x["base"])):
        a = it["a"]
        saving = (sum(it["base"][h] * rates[h] for h in range(24)) - sum(it["new"][h] * rates[h] for h in range(24))) * DAYS
        in_peak = sum(it["base"][h] for h in PEAK_HOURS)
        if it["action"] == "shift":
            newwin = _window(it["start"], it["hours"])
        elif it["action"] == "precool":
            newwin = "16:00–18:00 pre-cool + reduced peak run"
        else:
            newwin = _window(a["peak_hour"], it["hours"]) if it["hours"] < 24 else "24h (always-on)"
        note = ""
        if it["action"] == "keep":
            note = "Not in peak window" if in_peak <= 0 else ("Fixed comfort/operational load" if not a["shiftable"] else "No feasible off-peak slot")
        schedule.append({
            "appliance": a["name"], "watts": a["watts"], "kind": it["kind"], "action": it["action"],
            "hours": round(it["hours"], 2), "original_window": _window(a["peak_hour"], it["hours"]) if it["hours"] < 24 else "24h (always-on)",
            "new_window": newwin, "daily_kwh": round(sum(it["base"]), 2), "peak_kwh_day": round(in_peak, 2),
            "monthly_saving": round(saving, 2), "note": note,
        })

    ef = tariff["co2_kg_per_kwh"]
    co2_b, co2_o = _co2(base_curve, ef), _co2(opt_curve, ef)
    return {
        "daily_kwh_baseline": round(daily_b, 2), "daily_kwh_optimized": round(daily_o, 2),
        "month_kwh": round(daily_b * DAYS, 1), "month_kwh_optimized": round(daily_o * DAYS, 1),
        "bill_baseline": bill_b["total"], "bill_optimized": bill_o["total"],
        "bill_breakdown_baseline": bill_b, "bill_breakdown_optimized": bill_o,
        "savings_month": round(bill_b["total"] - bill_o["total"], 2),
        "savings_pct": round((bill_b["total"] - bill_o["total"]) / bill_b["total"] * 100, 1) if bill_b["total"] else 0.0,
        "peak_kw_before": round(peak_b, 2), "peak_kw_after": round(peak_o, 2),
        "peak_shaved_kw": round(peak_b - peak_o, 2),
        "peak_reduction_pct": round((peak_b - peak_o) / peak_b * 100, 1) if peak_b else 0.0,
        "peak_window_kwh_before": round(pk_b / DAYS, 2), "peak_window_kwh_after": round(pk_o / DAYS, 2),
        "co2_before_kg": round(co2_b, 1), "co2_after_kg": round(co2_o, 1), "co2_saved_kg": round(co2_b - co2_o, 1),
        "baseline_curve": [round(v, 3) for v in base_curve], "optimized_curve": [round(v, 3) for v in opt_curve],
        "schedule": schedule,
        "per_appliance": [{"name": it["a"]["name"], "kwh_day": round(sum(it["base"]), 2),
                           "share_pct": round(sum(it["base"]) / daily_b * 100, 1) if daily_b else 0} for it in
                          sorted(items, key=lambda x: -sum(x["base"]))],
    }


def full_report(appliances, factors, tariff, presets):
    main = analyze(appliances, factors, tariff)
    neutral = {"cooling": 1.0, "heating": 1.0}
    unadj = analyze(appliances, neutral, tariff, optimize=False)
    main["daily_kwh_unadjusted"] = unadj["daily_kwh_baseline"]
    main["month_kwh_unadjusted"] = unadj["month_kwh"]
    main["bill_unadjusted"] = unadj["bill_baseline"]
    main["weather_extra_kwh_month"] = round(main["month_kwh"] - unadj["month_kwh"], 1)
    main["weather_extra_cost_month"] = round(main["bill_baseline"] - unadj["bill_baseline"], 2)

    base = analyze(appliances, factors, tariff, optimize=False)
    therm = analyze(appliances, factors, tariff, cooling_scale=0.88, optimize=True)
    scen = []
    for name, r in (("Baseline (as logged)", base), ("Load-shifted schedule", main),
                    ("Shifted + thermostat +2 °C", therm)):
        scen.append({"name": name, "daily_kwh": r["daily_kwh_optimized"] if r is not base else r["daily_kwh_baseline"],
                     "peak_kw": r["peak_kw_after"] if r is not base else r["peak_kw_before"],
                     "bill": r["bill_optimized"] if r is not base else r["bill_baseline"],
                     "co2_kg": r["co2_after_kg"] if r is not base else r["co2_before_kg"]})
    b0 = scen[0]["bill"]
    for s in scen:
        s["savings"] = round(b0 - s["bill"], 2)
        s["savings_pct"] = round((b0 - s["bill"]) / b0 * 100, 1) if b0 else 0.0
    bench = []
    for p in presets:
        pa, _ = normalize_rows(p["appliances"])
        r = analyze(pa, factors, tariff)
        bench.append({"name": p["short"], "daily_kwh": r["daily_kwh_baseline"], "bill": r["bill_baseline"],
                      "peak_kw": r["peak_kw_before"], "savings_pct": r["savings_pct"]})
    return main, scen, bench
