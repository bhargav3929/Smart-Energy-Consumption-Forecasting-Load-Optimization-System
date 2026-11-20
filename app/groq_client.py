"""Groq-only AI client with model fallback chain."""
import json
import re
import time

import httpx

GROQ_BASE = "https://api.groq.com/openai/v1"
MODELS = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "llama-3.3-70b-versatile"]


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


def _err_message(resp: httpx.Response) -> str:
    try:
        return resp.json()["error"]["message"]
    except Exception:
        return f"HTTP {resp.status_code}"


async def chat_json(messages, key: str, budget_s: float = 18.0, max_tokens: int = 900):
    """Try each model in order within a total time budget.
    Returns dict(data, model, fallback, attempts, errors)."""
    deadline = time.monotonic() + budget_s
    errors, attempts = [], 0
    async with httpx.AsyncClient() as client:
        for idx, model in enumerate(MODELS):
            remaining = deadline - time.monotonic()
            if remaining < 1.5:
                errors.append("time budget exhausted")
                break
            attempts += 1
            body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.3,
                    "response_format": {"type": "json_object"}}
            if model.startswith("openai/gpt-oss"):
                body["reasoning_effort"] = "low"
            try:
                r = await client.post(f"{GROQ_BASE}/chat/completions", json=body,
                                      headers={"Authorization": f"Bearer {key}"},
                                      timeout=max(1.5, min(remaining, 9.0 if idx == 0 else remaining)))
                if r.status_code != 200:
                    errors.append(f"{model}: {_err_message(r)}")
                    if r.status_code in (401, 403):
                        break  # bad key: fallbacks won't help
                    continue
                content = r.json()["choices"][0]["message"].get("content") or ""
                return {"data": _extract_json(content), "model": model, "fallback": idx > 0,
                        "attempts": attempts, "errors": errors}
            except Exception as e:  # timeout, network, parse
                errors.append(f"{model}: {type(e).__name__} {e}"[:200])
    return {"data": None, "model": None, "fallback": False, "attempts": attempts, "errors": errors}


async def test_key(key: str):
    if not key:
        return {"ok": False, "message": "No Groq API key provided."}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{GROQ_BASE}/models", headers={"Authorization": f"Bearer {key}"}, timeout=10.0)
        if r.status_code == 200:
            return {"ok": True, "message": "Valid Groq Key"}
        return {"ok": False, "message": _err_message(r)}
    except Exception as e:
        return {"ok": False, "message": f"{type(e).__name__}: {e}"}
