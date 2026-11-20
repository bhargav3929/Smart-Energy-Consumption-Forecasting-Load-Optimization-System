"""Demo ticket verification (format defined by the LastSem contract)."""
import base64
import hashlib
import hmac
import json
import time


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify_ticket(ticket, secret: str, slug: str):
    """Return (payload, None) if valid, else (None, error_code)."""
    if not ticket:
        return None, "TICKET_REQUIRED"
    if not secret:
        return None, "TICKET_INVALID"
    try:
        body, sig = ticket.split(".")
        payload = json.loads(_b64d(body))
        expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
        if payload.get("v") != 1 or not hmac.compare_digest(expected, _b64d(sig)):
            return None, "TICKET_INVALID"
    except Exception:
        return None, "TICKET_INVALID"
    if payload.get("slug") not in (slug, "*"):
        return None, "TICKET_INVALID"
    if int(payload.get("exp", 0)) < time.time():
        return None, "TICKET_EXPIRED"
    return payload, None
