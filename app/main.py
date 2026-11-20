"""FastAPI app. Default port: 8005 -> http://127.0.0.1:8005"""
import csv
import io
import json
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from . import db, energy, groq_client  # noqa: E402
from .pipeline import run_pipeline  # noqa: E402
from .presets import PRESETS  # noqa: E402

HOST, PORT = "127.0.0.1", 8005
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Smart Energy Consumption Forecasting & Load Optimization System")
db.init()
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _mask(k: str) -> str:
    return (k[:4] + "…" + k[-4:]) if len(k) > 10 else ("•" * len(k))


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
def status():
    key, src = db.get_groq_key()
    return {"quota": db.quota_status(), "has_key": bool(key), "key_source": src, "key_masked": _mask(key) if key else ""}


@app.get("/api/presets")
def presets():
    return PRESETS


@app.post("/api/settings")
async def save_settings(request: Request):
    body = await request.json()
    key = str(body.get("groq_api_key", "")).strip()
    if key and not key.startswith("gsk_"):
        return JSONResponse({"ok": False, "message": "Groq keys start with gsk_"}, status_code=400)
    db.set_setting("GROQ_API_KEY", key)
    return {"ok": True, **status()}


@app.post("/api/test-key")
async def test_key(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    key = str(body.get("groq_api_key", "")).strip() or db.get_groq_key()[0]
    return await groq_client.test_key(key)


@app.post("/api/parse-log")
async def parse_log(file: UploadFile = File(...)):
    raw = (await file.read())[:512_000]
    text = raw.decode("utf-8-sig", errors="replace").strip()
    rows = []
    try:
        if text[:1] in "[{":
            data = json.loads(text)
            rows = data.get("appliances", []) if isinstance(data, dict) else data
        else:
            rows = list(csv.DictReader(io.StringIO(text)))
    except Exception as e:
        raise HTTPException(400, f"Could not parse file: {e}")
    norm = []
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict):
            r = {str(k).strip().lower(): v for k, v in r.items()}
            norm.append({"name": r.get("appliance") or r.get("name"), "watts": r.get("watts"),
                         "hours_per_day": r.get("hours_per_day", r.get("hours")),
                         "peak_hour": r.get("peak_hour", 18), "shiftable": r.get("shiftable", False)})
    clean, errors = energy.normalize_rows(norm)
    if errors and not clean:
        raise HTTPException(400, " ".join(errors))
    return {"appliances": clean, "warnings": errors}


@app.post("/api/forecast")
async def forecast(request: Request):
    body = await request.json()
    ticket = db.consume()
    if ticket is None:
        q = db.quota_status()
        return JSONResponse({"error": f"Hourly limit reached (15/15 used). Resets in {q['reset_in'] // 60 + 1} min.", "quota": q}, status_code=429)

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


@app.get("/api/history")
def history():
    return db.list_forecasts()


@app.get("/api/history/{fid}")
def history_item(fid: int):
    d = db.get_forecast(fid)
    if not d:
        raise HTTPException(404, "Forecast not found")
    d["id"] = fid
    return d


@app.delete("/api/history/{fid}")
def history_delete(fid: int):
    if not db.delete_forecast(fid):
        raise HTTPException(404, "Forecast not found")
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
