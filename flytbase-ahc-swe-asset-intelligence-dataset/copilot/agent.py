"""Tool-calling loop over any OpenAI-compatible endpoint (Google AI Studio, OpenRouter, Ollama).
   LLM_API_KEY=... [LLM_BASE_URL=... LLM_MODEL=...] py -m copilot.agent --user U-201 ["question"]
The model only routes to tools and phrases their output; every number comes from the tools."""
import argparse
import inspect
import json
import os
import re
import urllib.error
import uuid
from pathlib import Path

from . import llm, memory, narrate, retrieval, router, tools

for d in Path(__file__).resolve().parents:  # nearest .env above the repo supplies GEMINI_API_KEY etc.
    if (d / ".env").exists():
        for line in (d / ".env").read_text(encoding="utf-8").splitlines():
            k, sep, v = line.partition("=")
            if sep and not k.strip().startswith("#"):
                os.environ.setdefault(k.strip().removeprefix("export "), v.strip().strip("\"'"))
        break

MODEL = os.environ.get("LLM_MODEL", "gemma-4-26b-a4b-it")
USE_ROUTER = os.environ.get("ROUTER", "1") != "0"  # rule-based router first, the LLM tool loop only when it is unsure
ADDENDUM = Path(__file__).parent / "prompt_addendum.txt"

REGISTRY = {f.__name__: f for f in (
    tools.well_status, tools.find_wells, tools.series, tools.downtime, tools.spills, tools.compliance, tools.repairs,
    tools.rca_candidates, tools.well_notes, retrieval.search, memory.correct_value, memory.add_well_note,
    memory.add_type_rule, memory.recall)}
INJECTED = {"user_id"}  # supplied by the runtime from the logged-in user, never by the model
PARAM_TYPE = {"producing": "boolean", "top_n": "integer", "last_days": "integer", "last_weeks": "integer", "last_months": "integer",
              "this_year": "boolean", "value": "number", "claims_producing": "integer", "days_ago": "integer", "k": "integer",
              "limit": "integer", "well_ids": "array"}
VISUALS = [(r"heat ?map", "heatmap"), (r"line chart|trend", "line"), (r"bar chart", "bar"), (r"(?<!heat )\bmap\b|pins", "map"),
           (r"status card|\bcard\b", "card"), (r"\btable\b|\blist\b", "table")]

SYSTEM = """You are the Asset Intelligence Copilot for an oil field. Today is {today}. Use the tools for every fact; never do
arithmetic or guess data yourself. Rules:
- Wells are WELL-0001 style IDs. Areas: {areas}. Pass area_id (e.g. NE-08), never the name. Periods: "last 4 months" -> last_months=4,
  "last 90 days" -> last_days=90, "in 2025" -> since=2025-01-01 until=2025-12-31, "this year" -> this_year=true.
- Producing oil is derived by the tools from the inspection and the well-type manual; recorded_status is often out of date.
- For any producing / not-producing answer, state how many degrees the wellhead is above air versus the type limit, and flag when
  recorded_status disagrees with the latest inspection (it is out of date).
- If a stopped well has no recorded reason (no open repair, no active note), say so and suggest a check; never invent a cause.
- When a user states a fact, correction, or rule, call the matching tool (correct_value / add_well_note / add_type_rule), then
  report exactly what was recorded, the original value kept, and every conflict returned; ask the user to confirm conflicts.
- After correct_value / add_well_note, report the new producing state, every compliance consequence returned (overdue notices,
  new deadlines), any repair report whose stated class is now outdated, and every conflict, including active notes that
  disagree with the user's claim (quote their expected dates).
- When a correction removes a well from a list, say which well was removed and why (corrected_out).
- Always name the person (by name) behind any note, correction or rule you rely on, and quote the dates in their notes.
- For compliance questions, also list open_actions (pending duties that are not breaches) and fines on any notice of violation.
- If a note or correction changes an answer, say whose it is (by name) and cite it. Never use another user's private conversation.
- For "wells we discussed earlier" call recall first.
- Cite evidence IDs from the tool results (INS-..., MNT-..., REG-..., CTX-..., doc chunk ids) in square brackets.
- Rules and thresholds come from the search tool over the manuals/SOPs when you need to quote one.
Answer briefly. The UI renders the table/chart/map from the tool result, so do not repeat every row in text."""


def named_visuals(question):
    """Every visual the user names, in the order they ask for them ("a table and a map" -> ["table", "map"])."""
    hits = [(m.start(), v) for pat, v in VISUALS for m in [re.search(pat, question, re.I)] if m]
    return list(dict.fromkeys(v for _, v in sorted(hits)))


def schema(fn):
    props, required = {}, []
    for name, p in inspect.signature(fn).parameters.items():
        if name in INJECTED:
            continue
        t = PARAM_TYPE.get(name, "string")
        props[name] = {"type": t, **({"items": {"type": "string"}} if t == "array" else {})}
        if p.default is inspect.Parameter.empty:
            required.append(name)
    doc = " ".join((fn.__doc__ or fn.__name__).split())
    return {"type": "function", "function": {"name": fn.__name__, "description": doc[:600],
                                              "parameters": {"type": "object", "properties": props, "required": required}}}


def call_llm(messages, key, model=None, with_tools=True):
    return llm.call(messages, key, model, [schema(f) for f in REGISTRY.values()] if with_tools else None)


def run_tool(name, args, user_id):
    fn = REGISTRY.get(name)
    if not fn:
        return {"error": f"unknown tool {name}"}
    if "user_id" in inspect.signature(fn).parameters:
        args["user_id"] = user_id
    try:
        return fn(**args)
    except Exception as e:  # bad arguments from the model: hand the error back so it can retry
        return {"error": f"{type(e).__name__}: {e}"}


def compact(res, limit=60):
    rows = res.get("rows") or []
    out = {**res, "rows": rows[:limit]}
    if len(rows) > limit:
        out["truncated"] = f"showing {limit} of {len(rows)} rows"
    out["evidence"] = (res.get("evidence") or [])[:40]
    return json.dumps(out, default=str)


def run_plan(plan, user_id):
    """Execute a router plan with no model call -> [{"tool", "args", "res"}]. A recall step feeds its wells to the next step."""
    steps, ids = [], []
    for st in plan:
        args = {k: (ids if v == "@ids" else v) for k, v in st["args"].items()}
        size = args.pop("size", None)
        res = run_tool(st["tool"], dict(args), user_id)
        if st["tool"] == "recall":
            ents = res.get("rows") or []
            res["chosen"] = next((e for e in ents if size and len(e["well_ids"]) == size), ents[0] if ents else None)
            ids = res["chosen"]["well_ids"] if ents else []
        if st.get("keep") and res.get("rows"):
            rows = [r for r in res["rows"] if all(r.get(k) in v for k, v in st["keep"].items())]
            res = {**res, "rows": rows, "evidence": [i for r in rows for i in (r.get("evidence") or [r.get("inspection_id")])]}
        steps.append({"tool": st["tool"], "args": args, "res": res})
        if st["tool"] == "recall" and not ids:
            break  # nothing to look up: the narrator explains instead of running the next step on an empty well list
    return steps


def ask(question, user_id, chat_id=None, history=None, key=None, ts=None):
    """One user turn -> {"text", "visual", "rows", "evidence"}. history holds earlier messages of this chat.
    The router answers what it recognises with no model call; everything else goes through the LLM tool loop."""
    key = key or os.environ.get("LLM_API_KEY") or os.environ.get("GEMINI_API_KEY")
    chat_id = chat_id or uuid.uuid4().hex[:8]
    memory.log_turn(user_id, chat_id, "user", question, ts)
    areas = "; ".join(f"{r['area_id']} = {r['name']}" for r in tools.q("SELECT area_id, name FROM areas"))
    extra = ADDENDUM.read_text(encoding="utf-8") if ADDENDUM.exists() else ""  # rules appended by the QA fix loop
    messages = [{"role": "system", "content": SYSTEM.format(today=tools.as_of(), areas=areas) + extra}, *(history or []),
                {"role": "user", "content": question}]
    last, evidence, trace, all_rows, tool_evidence, tool_results = None, [], [], [], [], []

    def record(name, args, res):
        nonlocal last, all_rows, tool_evidence, evidence
        trace.append({"tool": name, "args": {k: v for k, v in args.items() if k != "user_id"},
                      "n_rows": len(res.get("rows") or []), "error": res.get("error")})
        all_rows += [r for r in (res.get("rows") or []) if isinstance(r, dict)]
        tool_evidence += res.get("evidence", [])
        if res.get("rows") and "error" not in res:
            last = res
            tool_results.append({"tool": name, "args": trace[-1]["args"], "rows": res["rows"][:200],
                                 "visual": res.get("visual"), "window": res.get("window"), "evidence": res.get("evidence", [])})
            evidence += res.get("evidence", [])
            ids = [v for r in res["rows"] if isinstance(r, dict) for k, v in r.items()
                   if k in ("asset_id", "key", "well_id") and isinstance(v, str) and v.startswith("WELL-")]
            if name != "recall":
                memory.remember(user_id, chat_id, question[:120], ids, ts)

    plan = router.route(question) if USE_ROUTER else None
    if plan:
        steps = run_plan(plan, user_id)
        for st in steps:
            record(st["tool"], st["args"], st["res"])
        msg = {"role": "assistant", "content": llm.polish(narrate.narrate(steps), key)}
        messages.append(msg)
    else:
        for _ in range(8):
            try:
                msg = call_llm(messages, key)
            except (urllib.error.URLError, TimeoutError):
                if not trace:
                    if not USE_ROUTER:
                        raise  # nothing happened yet: let the caller report the failure
                    msg = {"role": "assistant", "content": narrate.HELP}
                    break
                done = ", ".join(dict.fromkeys(t["tool"] for t in trace))
                changed = any(t["tool"] in ("correct_value", "add_well_note", "add_type_rule") and not t["error"] for t in trace)
                note = "The change you asked for was recorded." if changed else "The results are shown below."
                msg = {"role": "assistant", "content": f"I ran {done}, but the language model did not answer in time, so there is no written summary. "
                                                       f"{note} Ask again if you want an explanation."}
                break
            messages.append(msg)
            if not msg.get("tool_calls"):
                break
            for tc in msg["tool_calls"]:
                args = json.loads(tc["function"]["arguments"] or "{}")
                res = run_tool(tc["function"]["name"], args, user_id)
                record(tc["function"]["name"], args, res)
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": compact(res)})
    text = re.sub(r"</?thought>", "", re.sub(r"<thought>.*?</thought>", "", msg.get("content") or "", flags=re.S)).strip()
    turn_id = memory.log_turn(user_id, chat_id, "assistant", text, ts)
    named = named_visuals(question)
    default = last["visual"] if last else "text"
    if last and len(last["rows"]) == 1 and default in ("bar", "line", "table"):
        default = "text"  # a single value is a short answer, not a chart
    visual = named[0] if named else default
    cited = sorted(e for e in set(evidence) if e in text)  # show only the records the answer actually cites
    return {"text": text, "visual": visual, "rows": (last or {}).get("rows", []), "evidence": cited or sorted(set(evidence)),
            "history": messages[1:], "chat_id": chat_id, "turn_id": turn_id, "trace": trace, "tool_rows": all_rows[:500],
            "tool_evidence": sorted(set(tool_evidence)), "named": named, "tool_results": tool_results}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="U-201")
    ap.add_argument("question", nargs="?")
    a = ap.parse_args()
    hist, chat = [], None
    while True:
        qn = a.question or input("you> ")
        out = ask(qn, a.user, chat, hist)
        hist, chat = out["history"], out["chat_id"]
        print(f"[{out['visual']}] {out['text']}\nevidence: {', '.join(out['evidence'][:12])}")
        if a.question:
            break
