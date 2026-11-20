"""Settings read from environment variables / .env (standard LastSem names, all with defaults)."""
import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None or not v.strip():
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _str(name: str, default: str) -> str:
    return (os.getenv(name) or "").strip() or default


PROJECT_NAME = _str("PROJECT_NAME", "Smart Energy Consumption Forecasting & Load Optimization System")
PROJECT_SLUG = _str("PROJECT_SLUG", "smart-energy-forecasting")
PROJECT_NUMBER = _int("PROJECT_NUMBER", 5)
VERSION = "1.0.0"

HOST = _str("HOST", "127.0.0.1")
PORT = _int("PORT", 8000 + PROJECT_NUMBER)  # 8005
MAX_UPLOAD_MB = _int("MAX_UPLOAD_MB", 8)

GROQ_MODEL = _str("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_FALLBACK_MODEL = _str("GROQ_FALLBACK_MODEL", "llama-3.3-70b-versatile")

DEMO_MODE = _bool("DEMO_MODE", False)
DEMO_TICKET_SECRET = os.getenv("DEMO_TICKET_SECRET", "").strip()
DEMO_DAILY_CAP = _int("DEMO_DAILY_CAP", 200)
DEMO_MAX_UPLOAD_MB = _int("DEMO_MAX_UPLOAD_MB", 3)
DEMO_TICKET_RUNS_DEFAULT = 3
TRUST_PROXY = _bool("TRUST_PROXY", False)

PLACEHOLDER_KEY = "your_groq_key_here"


def usable_key(key: str | None) -> bool:
    """A Groq key is usable only if non-empty, not the placeholder, no spaces, and starts with gsk_."""
    k = (key or "").strip()
    return bool(k) and k != PLACEHOLDER_KEY and " " not in k and k.startswith("gsk_")
