"""SQLite persistence: settings, sliding-window rate limit, forecast history."""
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.getenv("SMART_ENERGY_DB", Path(__file__).resolve().parent.parent / "smart_energy.db"))
RATE_LIMIT = 15
WINDOW_SECONDS = 3600
_lock = threading.Lock()


@contextmanager
def db():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS rate_limit (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL)")
        c.execute(
            "CREATE TABLE IF NOT EXISTS forecasts (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "created_at REAL NOT NULL, title TEXT, city TEXT, payload TEXT NOT NULL)"
        )


# ---------- settings ----------
def get_setting(key: str):
    with db() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str):
    with db() as c:
        if value:
            c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        else:
            c.execute("DELETE FROM settings WHERE key=?", (key,))


def get_groq_key():
    """Returns (key, source) where source is 'settings', 'env' or None."""
    k = get_setting("GROQ_API_KEY")
    if k:
        return k, "settings"
    k = os.getenv("GROQ_API_KEY", "").strip()
    if k:
        return k, "env"
    return "", None


# ---------- rate limit (sliding window) ----------
def quota_status():
    now = time.time()
    with db() as c:
        c.execute("DELETE FROM rate_limit WHERE ts <= ?", (now - WINDOW_SECONDS,))
        rows = c.execute("SELECT ts FROM rate_limit ORDER BY ts").fetchall()
    used = len(rows)
    reset = int(rows[0]["ts"] + WINDOW_SECONDS - now) if rows else 0
    return {"limit": RATE_LIMIT, "remaining": max(0, RATE_LIMIT - used), "reset_in": max(0, reset)}


def consume():
    """Reserve one request. Returns a ticket id, or None if the hourly limit is exhausted."""
    with _lock:
        now = time.time()
        with db() as c:
            c.execute("DELETE FROM rate_limit WHERE ts <= ?", (now - WINDOW_SECONDS,))
            used = c.execute("SELECT COUNT(*) n FROM rate_limit").fetchone()["n"]
            if used >= RATE_LIMIT:
                return None
            cur = c.execute("INSERT INTO rate_limit(ts) VALUES(?)", (now,))
            return cur.lastrowid


def refund(ticket):
    if ticket is None:
        return
    with _lock, db() as c:
        c.execute("DELETE FROM rate_limit WHERE id=?", (ticket,))


# ---------- forecast history ----------
def save_forecast(data: dict) -> int:
    with db() as c:
        cur = c.execute(
            "INSERT INTO forecasts(created_at,title,city,payload) VALUES(?,?,?,?)",
            (data["created_at"], data["title"], data["city"]["name"], json.dumps(data)),
        )
        return cur.lastrowid


def list_forecasts(limit=50):
    with db() as c:
        rows = c.execute("SELECT id,created_at,title,city,payload FROM forecasts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        try:
            e = json.loads(r["payload"])["energy"]
            meta = {"daily_kwh": e["daily_kwh_baseline"], "bill": e["bill_baseline"], "savings": e["savings_month"]}
        except Exception:
            meta = {}
        out.append({"id": r["id"], "created_at": r["created_at"], "title": r["title"], "city": r["city"], **meta})
    return out


def get_forecast(fid: int):
    with db() as c:
        row = c.execute("SELECT payload FROM forecasts WHERE id=?", (fid,)).fetchone()
    return json.loads(row["payload"]) if row else None


def delete_forecast(fid: int) -> bool:
    with db() as c:
        return c.execute("DELETE FROM forecasts WHERE id=?", (fid,)).rowcount > 0
