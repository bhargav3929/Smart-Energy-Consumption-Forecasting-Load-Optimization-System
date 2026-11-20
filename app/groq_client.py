"""Groq-only AI client: timeout, retry with backoff, model fallback, plain-English errors."""
import asyncio
import json
import random
import re
import time

import httpx

from . import config

GROQ_BASE = "https://api.groq.com/openai/v1"
RETRY_STATUS = {429, 500, 502, 503, 504}
MESSAGES = {
    "AI_KEY_INVALID": "Your Groq key was rejected. Open API Keys and paste a fresh key from console.groq.com/keys.",
    "AI_BUSY": "The AI service is busy right now. Wait a minute and try again.",
    "AI_FAILED": "The AI couldn't process this input.",
}


def models():
    ms = [config.GROQ_MODEL]
    if config.GROQ_FALLBACK_MODEL and config.GROQ_FALLBACK_MODEL not in ms:
        ms.append(config.GROQ_FALLBACK_MODEL)
    return ms


def _extract_json(text: str):
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    i, j = text.find("{"), text.rfind("}")
    if i != -1 and j > i:
        return json.loads(text[i:j + 1])
    raise ValueError("no JSON object in model output")


def _clean(text: str, key: str) -> str:
    return (text or "").replace(key, "[key]")[:200]


def _err_message(resp: httpx.Response) -> str:
    try:
        return resp.json()["error"]["message"]
    except Exception:
        return f"HTTP {resp.status_code}"


def _retry_wait(resp, attempt: int) -> float:
    """Backoff 1s, 2s, 4s plus jitter; honour Groq's 'try again in Xs' when X <= 20."""
    wait = (2 ** attempt) + random.random() * 0.4
    if resp is not None and resp.status_code == 429:
        m = re.search(r"try again in ([\d.]+)\s*s", _err_message(resp))
        if m and float(m.group(1)) <= 20:
            wait = float(m.group(1)) + 0.2
    return wait


def _fail(attempts, errors, code):
    return {"data": None, "model": None, "fallback": False, "attempts": attempts, "errors": errors, "code": code}


async def chat_json(messages, key: str, budget_s: float = 18.0, max_tokens: int = 900):
    """Try each model (up to 3 attempts each) within a total time budget.
    Returns dict(data, model, fallback, attempts, errors, code). `code` is an AI_* code on failure."""
    deadline = time.monotonic() + budget_s
    errors, attempts, code = [], 0, "AI_FAILED"
    async with httpx.AsyncClient() as client:
        for idx, model in enumerate(models()):
            for attempt in range(3):
                remaining = deadline - time.monotonic()
                if remaining < 1.5:
                    errors.append("time budget exhausted")
                    return _fail(attempts, errors, "AI_BUSY")
                attempts += 1
                body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.3,
                        "response_format": {"type": "json_object"}}
                if model.startswith("openai/gpt-oss"):
                    body["reasoning_effort"] = "low"
                resp = None
                try:
                    resp = await client.post(f"{GROQ_BASE}/chat/completions", json=body,
                                             headers={"Authorization": f"Bearer {key}"},
                                             timeout=max(1.5, min(remaining, 9.0 if idx == 0 else remaining)))
                    if resp.status_code == 200:
                        content = resp.json()["choices"][0]["message"].get("content") or ""
                        try:
                            data = _extract_json(content)
                        except Exception:
                            errors.append(f"{model}: invalid JSON output")
                            code = "AI_FAILED"
                            break  # try the fallback model
                        return {"data": data, "model": model, "fallback": idx > 0, "attempts": attempts,
                                "errors": errors, "code": None}
                    errors.append(f"{model}: {_clean(_err_message(resp), key)}")
                    if resp.status_code in (401, 403):
                        return _fail(attempts, errors, "AI_KEY_INVALID")
                    if resp.status_code not in RETRY_STATUS:
                        code = "AI_FAILED"
                        break  # 400/413 etc: not retried, try the fallback model
                    code = "AI_BUSY"
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    errors.append(f"{model}: {type(e).__name__}")
                    code = "AI_BUSY"
                except Exception as e:
                    errors.append(f"{model}: {type(e).__name__}")
                    code = "AI_FAILED"
                    break
                if attempt < 2:
                    wait = _retry_wait(resp, attempt)
                    if deadline - time.monotonic() - wait < 1.5:
                        break
                    await asyncio.sleep(wait)
    return _fail(attempts, errors, code)


async def test_key(key: str):
    if not config.usable_key(key):
        return {"ok": False, "message": "Groq keys start with gsk_ and contain no spaces."}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{GROQ_BASE}/models", headers={"Authorization": f"Bearer {key}"}, timeout=10.0)
        if r.status_code == 200:
            return {"ok": True, "message": "Valid Groq Key"}
        if r.status_code in (401, 403):
            return {"ok": False, "message": MESSAGES["AI_KEY_INVALID"]}
        return {"ok": False, "message": MESSAGES["AI_BUSY"]}
    except Exception:
        return {"ok": False, "message": MESSAGES["AI_BUSY"]}
