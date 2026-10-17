"""One gateway for every model call: pacing, SQLite response cache, model chain, a hard deadline per call and a circuit
breaker. After two failed calls in a row the model is skipped for BREAKER_SECS, so callers serve deterministic answers
instead of waiting on a rate-limited endpoint."""
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request

from . import tools

BREAKER_SECS = float(os.environ.get("LLM_BREAKER_SECS", "60"))
_state = {"fails": 0, "open_until": 0.0, "last_call": 0.0}
_lock = threading.Lock()


class Unavailable(urllib.error.URLError):
    """The model was not called because the circuit breaker is open."""


def available():
    return time.time() >= _state["open_until"]


def _cache(h, value=None):
    """Read (value None) or write one cached response; a locked or missing table just means no caching."""
    try:
        db = tools.db()
        db.execute("CREATE TABLE IF NOT EXISTS llm_cache (hash TEXT PRIMARY KEY, response TEXT)")
        if value is None:
            row = db.execute("SELECT response FROM llm_cache WHERE hash=?", (h,)).fetchone()
            return json.loads(row[0]) if row else None
        db.execute("INSERT OR REPLACE INTO llm_cache VALUES (?,?)", (h, json.dumps(value)))
        db.commit()
    except sqlite3.Error:
        return None


def _post(model, messages, key, schemas, end):
    """One model with retries on 429/500/503 until `end`; any other failure is raised at once."""
    payload = {"model": model, "messages": messages, "temperature": 0}
    if schemas:
        payload["tools"] = schemas
    req = urllib.request.Request(f"{os.environ.get('LLM_BASE_URL', 'https://generativelanguage.googleapis.com/v1beta/openai')}/chat/completions",
                                 json.dumps(payload).encode(), {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    for attempt in range(4):
        with _lock:  # pace calls across threads to stay under free-tier limits
            time.sleep(max(0, float(os.environ.get("LLM_MIN_INTERVAL", "0")) - (time.time() - _state["last_call"])))
            _state["last_call"] = time.time()
        try:
            with urllib.request.urlopen(req, timeout=max(5, min(120, end - time.time()))) as r:
                return json.load(r)["choices"][0]["message"]
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            retry_after = e.headers.get("Retry-After") if isinstance(e, urllib.error.HTTPError) else None
            wait = min(60, float(retry_after) if retry_after and retry_after.isdigit() else 5 * 2 ** attempt)
            if attempt == 3 or time.time() + wait > end or (isinstance(e, urllib.error.HTTPError) and e.code not in (429, 500, 503)):
                raise
            time.sleep(wait)


def call(messages, key, model=None, schemas=None, deadline=None, trip=True):
    """Message dict from the model. Cached by prompt; tries the fallback model if the first fails; raises URLError/TimeoutError
    (Unavailable when the breaker is open) so callers can fall back to a deterministic answer. trip=False: a failure here
    does not count towards opening the breaker (optional calls must not lock out the ones that matter)."""
    h = hashlib.sha256(json.dumps([model, messages, [s["function"]["name"] for s in schemas or []]], sort_keys=True, default=str).encode()).hexdigest()
    hit = _cache(h)
    if hit:
        return hit
    if not key:
        raise Unavailable("no model key configured")
    if not available():
        raise Unavailable("model skipped: circuit breaker open after repeated failures")
    primary = model or os.environ.get("LLM_MODEL", "gemma-4-26b-a4b-it")
    chain = [primary] + ([m for m in os.environ.get("LLM_FALLBACK", "gemma-4-31b-it").split(",") if m and m != primary] if not model else [])
    start = time.time()
    end = start + (deadline or float(os.environ.get("LLM_DEADLINE", "900")))
    error = None
    for i, m in enumerate(chain):
        try:
            msg = _post(m, messages, key, schemas, min(end, time.time() + max(5, (end - time.time()) / (len(chain) - i))))
        except (urllib.error.URLError, TimeoutError) as e:
            error = e
            continue
        _state["fails"] = 0
        _cache(h, msg)
        return msg
    _state["fails"] += trip
    if _state["fails"] >= 2:
        _state["open_until"], _state["fails"] = time.time() + BREAKER_SECS, 0
    raise error


POLISH = ("Rewrite this answer for an oil-field operator in clear, short prose. Keep every number, name, date and bracketed "
          "record ID exactly as written, keep the caveats, and add nothing that is not in the text.\n\n")
FACT = re.compile(r"\b[A-Z]{2,4}-[\w-]+\b|\d+(?:[.,]\d+)*")


def polish(text, key):
    """Opt-in (LLM_POLISH=1) one-call rewrite of the templated answer. Accepted only if every number and ID survives; else the original."""
    if not key or os.environ.get("LLM_POLISH") != "1" or not available():
        return text
    try:
        out = call([{"role": "user", "content": POLISH + text}], key, deadline=float(os.environ.get("LLM_POLISH_DEADLINE", "15")), trip=False)["content"] or ""
    except (urllib.error.URLError, TimeoutError):
        return text
    out = re.sub(r"</?thought>", "", re.sub(r"<thought>.*?</thought>", "", out, flags=re.S)).strip()
    return out if out and all(f in out for f in set(FACT.findall(text))) else text
