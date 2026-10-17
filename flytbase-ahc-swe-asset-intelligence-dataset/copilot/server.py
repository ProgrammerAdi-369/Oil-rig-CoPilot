"""HTTP API for the web UI (stdlib only) + static hosting of the built frontend.
   py -m copilot.server [--port 8000] [--reset-demo]
The user is identified by the X-User-Id header, validated against `users`, and injected into the agent; the model never
chooses it. X-Field-Date (YYYY-MM-DD, <= data date) lets the UI simulate "yesterday" for the memory demo."""
import argparse
import json
import mimetypes
import os
import re
import sys
import traceback
import urllib.error
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

os.environ.setdefault("LLM_MIN_INTERVAL", "2")  # pace LLM calls: the free tier rate-limits
os.environ.setdefault("LLM_DEADLINE", "100")     # a browser will not wait longer than this for one model call

from . import agent, memory, present, tools  # noqa: E402
from .tools import q  # noqa: E402

DIST = Path(__file__).resolve().parents[2] / "FRONTEND" / "dist"
ROUTES = []


def route(method, pattern):
    def deco(fn):
        ROUTES.append((method, re.compile(f"^{pattern}$"), fn))
        return fn
    return deco


class Bad(Exception):
    """Client error: (status, message)."""
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status


def num(query, name, default, lo, hi):
    try:
        v = int(query.get(name, [default])[0])
    except ValueError:
        raise Bad(400, f"{name} must be an integer")
    return max(lo, min(hi, v))


def area_arg(query):
    a = query.get("area", [None])[0] or None
    if a and not q("SELECT 1 FROM areas WHERE area_id=?", a):
        raise Bad(400, f"unknown area {a}")
    return a


def current_user(h, required=True):
    uid = h.headers.get("X-User-Id")
    if not uid and not required:
        return None
    if not uid or not q("SELECT 1 FROM users WHERE user_id=?", uid):
        raise Bad(401, "unknown or missing X-User-Id")
    return uid


def packed(res, visual=None):
    """Tool result -> API payload with a ready-to-draw view."""
    visual = visual or res.get("visual")
    return {**{k: v for k, v in res.items() if k != "rows"}, "rows": res.get("rows", [])[:200], "view": present.view(visual, res.get("rows"))}


# ---------------------------------------------------------------- read endpoints (no LLM)
@route("GET", "/api/meta")
def meta(h, query):
    c = lambda t: q(f"SELECT count(*) AS n FROM {t}")[0]["n"]
    return {"as_of": tools.as_of(), "model": agent.MODEL, "llm_ready": bool(os.environ.get("LLM_API_KEY") or os.environ.get("GEMINI_API_KEY")),
            "counts": {"wells": c("wells"), "inspections": c("inspections"), "repairs": c("maintenance"), "notes": c("notes"), "chunks": c("chunks")}}


@route("GET", "/api/users")
def users(h, query):
    return q("SELECT u.user_id, u.name, u.role, u.team_id, t.name AS team FROM users u LEFT JOIN teams t USING (team_id) ORDER BY u.user_id")


@route("GET", "/api/areas")
def areas(h, query):
    return q("""SELECT a.area_id, a.name, a.team_id, a.lat, a.lon, (SELECT count(*) FROM wells w WHERE w.area_id=a.area_id) AS wells
                FROM areas a ORDER BY a.area_id""")


@route("GET", "/api/overview")
def overview(h, query):
    return present.overview(area_arg(query))


@route("GET", "/api/wells")
def wells(h, query):
    p = query.get("producing", [None])[0]
    return packed(tools.find_wells(producing=None if p is None else p == "true", area_id=area_arg(query), well_type=query.get("type", [None])[0]), "table")


@route("GET", r"/api/wells/(WELL-\d{4})")
def well(h, query, wid):
    r = tools.well_status(wid)
    if r.get("error"):
        raise Bad(404, r["error"])
    return packed(r, "card")


@route("GET", r"/api/wells/(WELL-\d{4})/series")
def series(h, query, wid):
    return packed(tools.series(wid, last_weeks=num(query, "weeks", 13, 1, 208)), "line")


@route("GET", "/api/downtime")
def downtime(h, query):
    return packed(tools.downtime(group_by=query.get("group", ["well"])[0], area_id=area_arg(query), top_n=num(query, "top", 5, 1, 50),
                                 last_months=num(query, "months", 4, 1, 48)), "bar")


@route("GET", "/api/spills")
def spills(h, query):
    return packed(tools.spills(area_id=area_arg(query), last_days=num(query, "days", 90, 1, 1500)), "map")


@route("GET", "/api/spills/heatmap")
def heatmap(h, query):
    y = num(query, "year", int(tools.as_of()[:4]), 2022, 2100)
    return packed(tools.spills(group_by="area_month", area_id=area_arg(query), since=f"{y}-01-01", until=f"{y}-12-31"), "heatmap")


@route("GET", "/api/compliance")
def compliance(h, query):
    r = tools.compliance(area_id=area_arg(query), last_months=num(query, "months", 12, 1, 48))
    r["counts"] = {"breach": sum(x["status"] == "breach" for x in r["rows"]), "pending": sum(x["status"] == "pending" for x in r["rows"])}
    return packed(r, "table")


@route("GET", "/api/rules")
def rules(h, query):
    return present.rules_view()


@route("GET", "/api/logs")
def logs(h, query):
    return present.logs(num(query, "limit", 40, 1, 200), area_arg(query))


@route("GET", "/api/evidence/(.+)")
def evidence(h, query, eid):
    card = present.evidence_card(unquote(eid))
    if not card:
        raise Bad(404, "no such record")
    return card


# ---------------------------------------------------------------- chats (private per user)
@route("GET", "/api/chats")
def chats(h, query):
    return memory.chats(current_user(h))


@route("GET", r"/api/chats/([\w-]+)")
def chat_get(h, query, chat_id):
    msgs = memory.chat_messages(current_user(h), chat_id)
    if not msgs:
        raise Bad(404, "no such chat")  # also what another user's chat id looks like
    return {"chat_id": chat_id, "messages": msgs}


@route("DELETE", r"/api/chats/([\w-]+)")
def chat_delete(h, query, chat_id):
    if not memory.delete_chat(current_user(h), chat_id):
        raise Bad(404, "no such chat")
    return {"deleted": chat_id}


@route("POST", "/api/chat")
def chat(h, query):
    uid = current_user(h)
    try:
        body = json.loads(h.body or b"{}")
    except ValueError:
        raise Bad(400, "body must be JSON")
    message = (body.get("message") or "").strip()
    if not message or len(message) > 2000:
        raise Bad(400, "message must be 1-2000 characters")
    chat_id = body.get("chat_id") or None
    if chat_id and not re.fullmatch(r"[\w-]{1,40}", chat_id):
        raise Bad(400, "bad chat_id")
    day = h.headers.get("X-Field-Date")
    ts = None
    if day:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or day > tools.as_of():
            raise Bad(400, "X-Field-Date must be YYYY-MM-DD and not after the data date")
        ts = day + datetime.now(timezone.utc).strftime("T%H:%M:%SZ")
    history = memory.chat_history(uid, chat_id) if chat_id else []
    out = agent.ask(message, uid, chat_id, history, ts=ts)
    visuals = present.compose(out["named"], out["tool_results"], out["visual"])
    payload = {"chat_id": out["chat_id"], "turn_id": out["turn_id"], "text": out["text"], "visual": out["visual"],
               "view": visuals[0]["view"] if visuals else None,  # the primary visual, kept for clients that draw one
               "visuals": visuals, "rows": out["rows"][:200], "evidence": out["evidence"],
               "steps": present.steps(out["trace"]), "as_of": tools.as_of()}
    memory.save_payload(out["turn_id"], payload)
    return payload


# ---------------------------------------------------------------- plumbing
class Handler(BaseHTTPRequestHandler):
    server_version = "AssetCopilot/1.0"

    def send_json(self, status, obj):
        body = json.dumps(obj, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def dispatch(self, method):
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            return self.static(url.path) if method == "GET" else self.send_json(405, {"error": "method not allowed"})
        query = parse_qs(url.query)
        # always consume the request body before answering, even when we reject the request: replying early on an unread body
        # makes some clients see a connection reset instead of our JSON error
        self.body = self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 20000))
        try:
            for m, pat, fn in ROUTES:
                hit = pat.match(url.path)
                if m == method and hit:
                    return self.send_json(200, fn(self, query, *hit.groups()))
            self.send_json(404, {"error": f"no route {method} {url.path}"})
        except Bad as e:
            self.send_json(e.status, {"error": str(e)})
        except (urllib.error.URLError, TimeoutError) as e:  # HTTPError is a URLError: the model endpoint failed or rate-limited
            self.send_json(502, {"error": "The language model is unavailable or rate-limited. Try again in a moment.", "detail": str(e)})
        except Exception as e:
            traceback.print_exc()
            self.send_json(500, {"error": f"{type(e).__name__}: {e}"})

    def static(self, path):
        if not DIST.exists():
            return self.send_json(404, {"error": "frontend not built: run `npm run build` in FRONTEND/ or use the Vite dev server on :5173"})
        f = (DIST / unquote(path).lstrip("/")).resolve()
        if not f.is_file() or DIST.resolve() not in f.parents:
            f = DIST / "index.html"  # single-page app fallback
        body = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(f.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = lambda self: self.dispatch("GET")
    do_POST = lambda self: self.dispatch("POST")
    do_DELETE = lambda self: self.dispatch("DELETE")

    def log_message(self, fmt, *args):
        print(f"{self.log_date_time_string()} {self.address_string()} {fmt % args}", file=sys.stderr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--reset-demo", action="store_true", help="wipe user-created runtime data first")
    a = ap.parse_args()
    if a.reset_demo:
        tools.reset_runtime()
        print("runtime data cleared")
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.daemon_threads = True
    print(f"API on http://{a.host}:{a.port}  (model {agent.MODEL}, data date {tools.as_of()}, frontend {'built' if DIST.exists() else 'not built'})")
    srv.serve_forever()
