"""Starlette app (pure Python, no pydantic). Default port: 8005 -> http://127.0.0.1:8005"""
import csv
import io
import json
from pathlib import Path

from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

load_dotenv()

from . import db, energy, groq_client  # noqa: E402
from .pipeline import run_pipeline  # noqa: E402
from .presets import PRESETS  # noqa: E402

HOST, PORT = "127.0.0.1", 8005
STATIC = Path(__file__).parent / "static"

db.init()


def _mask(k: str) -> str:
    return (k[:4] + "…" + k[-4:]) if len(k) > 10 else ("•" * len(k))


def _status_payload():
    key, src = db.get_groq_key()
    return {"quota": db.quota_status(), "has_key": bool(key), "key_source": src, "key_masked": _mask(key) if key else ""}


async def _json_body(request):
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


async def index(request):
    return FileResponse(STATIC / "index.html")


async def status(request):
    return JSONResponse(_status_payload())


async def presets(request):
    return JSONResponse(PRESETS)


async def save_settings(request):
    body = await _json_body(request)
    key = str(body.get("groq_api_key", "")).strip()
    if key and not key.startswith("gsk_"):
        return JSONResponse({"ok": False, "message": "Groq keys start with gsk_"}, status_code=400)
    db.set_setting("GROQ_API_KEY", key)
    return JSONResponse({"ok": True, **_status_payload()})


async def test_key(request):
    body = await _json_body(request)
    key = str(body.get("groq_api_key", "")).strip() or db.get_groq_key()[0]
    return JSONResponse(await groq_client.test_key(key))


async def parse_log(request):
    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        return JSONResponse({"detail": "No file uploaded."}, status_code=400)
    raw = (await upload.read())[:512_000]
    text = raw.decode("utf-8-sig", errors="replace").strip()
    try:
        if text[:1] in "[{":
            data = json.loads(text)
            rows = data.get("appliances", []) if isinstance(data, dict) else data
        else:
            rows = list(csv.DictReader(io.StringIO(text)))
    except Exception as e:
        return JSONResponse({"detail": f"Could not parse file: {e}"}, status_code=400)
    norm = []
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict):
            r = {str(k).strip().lower(): v for k, v in r.items()}
            norm.append({"name": r.get("appliance") or r.get("name"), "watts": r.get("watts"),
                         "hours_per_day": r.get("hours_per_day", r.get("hours")),
                         "peak_hour": r.get("peak_hour", 18), "shiftable": r.get("shiftable", False)})
    clean, errors = energy.normalize_rows(norm)
    if errors and not clean:
        return JSONResponse({"detail": " ".join(errors)}, status_code=400)
    return JSONResponse({"appliances": clean, "warnings": errors})


async def forecast(request):
    body = await _json_body(request)
    ticket = db.consume()
    if ticket is None:
        q = db.quota_status()
        return JSONResponse({"error": f"Hourly limit reached (15/15 used). Resets in {q['reset_in'] // 60 + 1} min.", "quota": q},
                            status_code=429)

    async def gen():
        try:
            async for ev in run_pipeline(body):
                if ev["type"] == "error" and ev.get("refund"):
                    db.refund(ticket)
                if ev["type"] in ("error", "result"):
                    ev["quota"] = db.quota_status()
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except Exception as e:  # unexpected: refund and report
            db.refund(ticket)
            yield json.dumps({"type": "error", "node": 0, "name": "Pipeline", "message": f"{type(e).__name__}: {e}",
                              "quota": db.quota_status()}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


async def history(request):
    return JSONResponse(db.list_forecasts())


def _fid(request):
    try:
        return int(request.path_params["fid"])
    except (KeyError, ValueError):
        return None


async def history_item(request):
    fid = _fid(request)
    d = db.get_forecast(fid) if fid is not None else None
    if not d:
        return JSONResponse({"detail": "Forecast not found"}, status_code=404)
    d["id"] = fid
    return JSONResponse(d)


async def history_delete(request):
    fid = _fid(request)
    if fid is None or not db.delete_forecast(fid):
        return JSONResponse({"detail": "Forecast not found"}, status_code=404)
    return JSONResponse({"ok": True})


routes = [
    Route("/", index),
    Route("/api/status", status),
    Route("/api/presets", presets),
    Route("/api/settings", save_settings, methods=["POST"]),
    Route("/api/test-key", test_key, methods=["POST"]),
    Route("/api/parse-log", parse_log, methods=["POST"]),
    Route("/api/forecast", forecast, methods=["POST"]),
    Route("/api/history", history),
    Route("/api/history/{fid}", history_item, methods=["GET"]),
    Route("/api/history/{fid}", history_delete, methods=["DELETE"]),
    Mount("/static", app=StaticFiles(directory=STATIC), name="static"),
]

app = Starlette(routes=routes)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
