"""SQLite persistence: settings, sliding-window rate limit, forecast history."""
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .config import usable_key

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
        cols = [r["name"] for r in c.execute("PRAGMA table_info(forecasts)").fetchall()]
        if "tid" not in cols:
            c.execute("ALTER TABLE forecasts ADD COLUMN tid TEXT NOT NULL DEFAULT ''")
        c.execute("CREATE TABLE IF NOT EXISTS ticket_runs (tid TEXT PRIMARY KEY, runs INTEGER NOT NULL DEFAULT 0, ts REAL NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS daily_runs (day TEXT PRIMARY KEY, runs INTEGER NOT NULL DEFAULT 0)")


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


def get_groq_key(demo: bool = False):
    """Returns (key, source) with source 'ui', 'env' or 'none'. Only usable keys count.
    Demo mode ignores saved keys (server environment only)."""
    if not demo:
        k = (get_setting("GROQ_API_KEY") or "").strip()
        if usable_key(k):
            return k, "ui"
    k = os.getenv("GROQ_API_KEY", "").strip()
    if usable_key(k):
        return k, "env"
    return "", "none"


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
def save_forecast(data: dict, tid: str = "") -> int:
    with db() as c:
        cur = c.execute(
            "INSERT INTO forecasts(created_at,title,city,payload,tid) VALUES(?,?,?,?,?)",
            (data["created_at"], data["title"], data["city"]["name"], json.dumps(data), tid),
        )
        return cur.lastrowid


def list_forecasts(limit=50, tid: str = ""):
    with db() as c:
        rows = c.execute("SELECT id,created_at,title,city,payload FROM forecasts WHERE tid=? ORDER BY id DESC LIMIT ?", (tid, limit)).fetchall()
    out = []
    for r in rows:
        try:
            e = json.loads(r["payload"])["energy"]
            meta = {"daily_kwh": e["daily_kwh_baseline"], "bill": e["bill_baseline"], "savings": e["savings_month"]}
        except Exception:
            meta = {}
        out.append({"id": r["id"], "created_at": r["created_at"], "title": r["title"], "city": r["city"], **meta})
    return out


def get_forecast(fid: int, tid: str = ""):
    with db() as c:
        row = c.execute("SELECT payload FROM forecasts WHERE id=? AND tid=?", (fid, tid)).fetchone()
    return json.loads(row["payload"]) if row else None


def delete_forecast(fid: int, tid: str = "") -> bool:
    with db() as c:
        return c.execute("DELETE FROM forecasts WHERE id=? AND tid=?", (fid, tid)).rowcount > 0


# ---------- demo tickets ----------
def purge_demo():
    """Delete ticket run counts and ticket history older than 24 hours."""
    cutoff = time.time() - 86400
    with db() as c:
        c.execute("DELETE FROM ticket_runs WHERE ts <= ?", (cutoff,))
        c.execute("DELETE FROM forecasts WHERE tid != '' AND created_at <= ?", (cutoff,))


def ticket_runs_used(tid: str) -> int:
    with db() as c:
        row = c.execute("SELECT runs FROM ticket_runs WHERE tid=?", (tid,)).fetchone()
    return row["runs"] if row else 0


def daily_runs_used() -> int:
    day = time.strftime("%Y-%m-%d", time.gmtime())
    with db() as c:
        row = c.execute("SELECT runs FROM daily_runs WHERE day=?", (day,)).fetchone()
    return row["runs"] if row else 0


def record_demo_run(tid: str):
    """Count one successful live run for this ticket and for today."""
    day = time.strftime("%Y-%m-%d", time.gmtime())
    with db() as c:
        c.execute("INSERT INTO ticket_runs(tid,runs,ts) VALUES(?,1,?) ON CONFLICT(tid) DO UPDATE SET runs=runs+1", (tid, time.time()))
        c.execute("INSERT INTO daily_runs(day,runs) VALUES(?,1) ON CONFLICT(day) DO UPDATE SET runs=runs+1", (day,))
