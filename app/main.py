"""Starlette app (pure Python, no pydantic). Default port: 8005 -> http://127.0.0.1:8005"""
import csv
import io
import json
import logging
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import config, db, energy, groq_client, tickets  # noqa: E402
from .pipeline import run_pipeline  # noqa: E402
from .presets import PRESETS  # noqa: E402

log = logging.getLogger("smart_energy")
ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).parent / "static"
SAMPLES = ROOT / "samples"
TICKET_HEADER = "X-LastSem-Ticket"

db.init()
db.purge_demo()
if config.DEMO_MODE and not config.DEMO_TICKET_SECRET:
    log.warning("DEMO_MODE is on but DEMO_TICKET_SECRET is empty: every ticket will be treated as invalid.")


# ---------- helpers ----------
def err(message: str, code: str, status: int, **extra):
    return JSONResponse({"error": message, "code": code, **extra}, status_code=status)


def _mask(k: str) -> str:
    return ("gsk_…" + k[-4:]) if k else ""


async def _json_body(request):
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


def _key():
    return db.get_groq_key(demo=config.DEMO_MODE)


def _check_ticket(request):
    """Returns (payload, None) or (None, error response). Only used in demo mode."""
    payload, code = tickets.verify_ticket(request.headers.get(TICKET_HEADER), config.DEMO_TICKET_SECRET, config.PROJECT_SLUG)
    if code:
        msgs = {
            "TICKET_REQUIRED": "Sign in on lastsem.com to try your own input.",
            "TICKET_INVALID": "This demo ticket isn't valid. Go back to lastsem.com and start again.",
            "TICKET_EXPIRED": "This demo ticket has expired. Go back to lastsem.com for a new one.",
        }
        return None, err(msgs[code], code, 401)
    return payload, None


def _tid(request) -> str:
    """Visitor id for history: the ticket id in demo mode, '' for the download version."""
    if not config.DEMO_MODE:
        return ""
    payload, _ = tickets.verify_ticket(request.headers.get(TICKET_HEADER), config.DEMO_TICKET_SECRET, config.PROJECT_SLUG)
    return payload["tid"] if payload else "-"  # '-' matches no stored history


def _is_local_request(request) -> bool:
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost"):
        return False
    return "x-forwarded-for" not in request.headers and "forwarded" not in request.headers


def _keys_guard(request, change: bool):
    if config.DEMO_MODE:
        return err("Not found.", "NOT_FOUND", 404)
    if change and not _is_local_request(request):
        return err("API keys can only be changed from the machine running the app.", "KEYS_LOCAL_ONLY", 403)
    return None


# ---------- pages & standard routes ----------
async def index(request):
    return FileResponse(STATIC / "index.html")


async def health(request):
    return JSONResponse({"status": "ok"})


async def info(request):
    key, _src = _key()
    demo = None
    max_mb = config.DEMO_MAX_UPLOAD_MB if config.DEMO_MODE else config.MAX_UPLOAD_MB
    if config.DEMO_MODE:
        payload, _ = tickets.verify_ticket(request.headers.get(TICKET_HEADER), config.DEMO_TICKET_SECRET, config.PROJECT_SLUG)
        left = max(0, int(payload.get("runs", 0)) - db.ticket_runs_used(payload["tid"])) if payload else 0
        demo = {"ticket_valid": bool(payload), "runs_left": left, "daily_cap_reached": db.daily_runs_used() >= config.DEMO_DAILY_CAP}
    return JSONResponse({
        "name": config.PROJECT_NAME, "slug": config.PROJECT_SLUG, "number": config.PROJECT_NUMBER, "version": config.VERSION,
        "mode": "demo" if config.DEMO_MODE else "local",
        "ai": {"provider": "groq", "ready": bool(key), "model": config.GROQ_MODEL},
        "limits": {"max_upload_mb": max_mb},
        "demo": demo,
    })


def _sample_list():
    out = []
    for p in PRESETS:
        out.append({"id": p["id"], "title": p["title"], "input_url": f"samples/{p['id']}.csv", "city": p["city"],
                    "has_saved_result": (SAMPLES / "results" / f"{p['id']}.json").is_file()})
    return out


async def samples(request):
    return JSONResponse({"samples": _sample_list()})


async def sample_one(request):
    sid = request.path_params["sid"]
    item = next((s for s in _sample_list() if s["id"] == sid), None)
    if not item:
        return err("That sample doesn't exist.", "NOT_FOUND", 404)
    f = SAMPLES / "results" / f"{sid}.json"
    result = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
    return JSONResponse({"id": sid, "title": item["title"], "input_url": item["input_url"], "result": result})


async def presets(request):
    return JSONResponse(PRESETS)


# ---------- keys (download version only) ----------
async def keys_get(request):
    if (g := _keys_guard(request, change=False)):
        return g
    key, src = _key()
    return JSONResponse({"groq": {"configured": bool(key), "source": src, "masked": _mask(key)}})


async def keys_post(request):
    if (g := _keys_guard(request, change=True)):
        return g
    body = await _json_body(request)
    key = str(body.get("groq_api_key", "")).strip()
    if not config.usable_key(key):
        return err("That doesn't look like a Groq key. Keys start with gsk_ and have no spaces.", "BAD_INPUT", 400)
    db.set_setting("GROQ_API_KEY", key)
    return JSONResponse({"saved": ["groq"]})


async def keys_delete(request):
    if (g := _keys_guard(request, change=True)):
        return g
    db.set_setting("GROQ_API_KEY", "")
    return JSONResponse({"removed": "groq"})


async def keys_test(request):
    if (g := _keys_guard(request, change=True)):
        return g
    body = await _json_body(request)
    key = str(body.get("groq_api_key", "")).strip() or _key()[0]
    return JSONResponse(await groq_client.test_key(key))


# ---------- feature routes ----------
async def status(request):
    key, src = _key()
    return JSONResponse({"has_key": bool(key), "key_source": src, "key_masked": _mask(key),
                         "demo_mode": config.DEMO_MODE})


async def parse_log(request):
    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        return err("Choose a CSV or JSON file to upload.", "BAD_INPUT", 400)
    limit_mb = config.DEMO_MAX_UPLOAD_MB if config.DEMO_MODE else config.MAX_UPLOAD_MB
    raw = await upload.read()
    if len(raw) > limit_mb * 1024 * 1024:
        return err(f"That file is larger than {limit_mb} MB.", "TOO_LARGE", 413)
    name = (getattr(upload, "filename", "") or "").lower()
    if name and not name.endswith((".csv", ".json", ".txt")):
        return err("Upload a .csv or .json file.", "BAD_INPUT", 400)
    text = raw.decode("utf-8-sig", errors="replace").strip()
    try:
        if text[:1] in "[{":
            data = json.loads(text)
            rows = data.get("appliances", []) if isinstance(data, dict) else data
        else:
            rows = list(csv.DictReader(io.StringIO(text)))
    except Exception as e:
        return err(f"Could not parse file: {e}", "BAD_INPUT", 400)
    norm = []
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict):
            r = {str(k).strip().lower(): v for k, v in r.items()}
            norm.append({"name": r.get("appliance") or r.get("name"), "watts": r.get("watts"),
                         "hours_per_day": r.get("hours_per_day", r.get("hours")),
                         "peak_hour": r.get("peak_hour", 18), "shiftable": r.get("shiftable", False)})
    clean, errors = energy.normalize_rows(norm)
    if errors and not clean:
        return err(" ".join(errors), "BAD_INPUT", 400)
    return JSONResponse({"appliances": clean, "warnings": errors})


async def forecast(request):
    body = await _json_body(request)
    ticket_payload = None
    if config.DEMO_MODE:
        ticket_payload, bad = _check_ticket(request)
        if bad:
            return bad
        tid = ticket_payload["tid"]
        if db.ticket_runs_used(tid) >= int(ticket_payload.get("runs", 0)):
            return err("The live runs on this demo ticket are used up. Buy the project to run it without limits.", "TICKET_USED_UP", 429)
        if db.daily_runs_used() >= config.DEMO_DAILY_CAP:
            return err("The demo has reached its daily limit. Please try again tomorrow.", "DAILY_CAP_REACHED", 429)
    tid = ticket_payload["tid"] if ticket_payload else ""

    key, _src = _key()
    if not key:
        msg = ("The demo's AI is not available right now. Please try again later." if config.DEMO_MODE
               else "Add your free Groq key (click API Keys) to run a forecast.")
        return err(msg, "AI_NOT_CONFIGURED", 503)

    async def gen():
        try:
            async for ev in run_pipeline(body, key, tid):
                if ev["type"] == "result" and ticket_payload:
                    db.record_demo_run(tid)  # count only after a successful run
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except Exception:  # unexpected failure: reported, and nothing is counted
            log.exception("pipeline failed")
            msg = "The forecast couldn't be completed. Please try again."
            yield json.dumps({"type": "error", "node": 0, "name": "Pipeline", "message": msg, "error": msg,
                              "code": "AI_FAILED"}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


async def history(request):
    return JSONResponse(db.list_forecasts(tid=_tid(request)))


def _fid(request):
    try:
        return int(request.path_params["fid"])
    except (KeyError, ValueError):
        return None


async def history_item(request):
    fid = _fid(request)
    d = db.get_forecast(fid, _tid(request)) if fid is not None else None
    if not d:
        return err("Forecast not found.", "NOT_FOUND", 404)
    d["id"] = fid
    return JSONResponse(d)


async def history_delete(request):
    fid = _fid(request)
    if fid is None or not db.delete_forecast(fid, _tid(request)):
        return err("Forecast not found.", "NOT_FOUND", 404)
    return JSONResponse({"ok": True})


async def not_found(request, exc):
    return err("Not found.", "NOT_FOUND", 404)


async def server_error(request, exc):
    log.exception("unhandled error")
    return err("Something went wrong on the server. Please try again.", "AI_FAILED", 500)


routes = [
    Route("/", index),
    Route("/health", health),
    Route("/api/info", info),
    Route("/api/samples", samples),
    Route("/api/samples/{sid}", sample_one),
    Route("/api/keys", keys_get, methods=["GET"]),
    Route("/api/keys", keys_post, methods=["POST"]),
    Route("/api/keys/test", keys_test, methods=["POST"]),
    Route("/api/keys/groq", keys_delete, methods=["DELETE"]),
    Route("/api/status", status),
    Route("/api/presets", presets),
    Route("/api/parse-log", parse_log, methods=["POST"]),
    Route("/api/forecast", forecast, methods=["POST"]),
    Route("/api/history", history),
    Route("/api/history/{fid}", history_item, methods=["GET"]),
    Route("/api/history/{fid}", history_delete, methods=["DELETE"]),
    Mount("/static", app=StaticFiles(directory=STATIC), name="static"),
]
if SAMPLES.is_dir():
    routes.append(Mount("/samples", app=StaticFiles(directory=SAMPLES), name="samples"))

app = Starlette(routes=routes, exception_handlers={404: not_found, 500: server_error})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.HOST, port=config.PORT)
