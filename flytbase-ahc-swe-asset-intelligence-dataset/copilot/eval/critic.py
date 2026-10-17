"""QA critic for the copilot. Deterministic checks decide pass/fail; a small LLM judge is consulted only for semantic
items a regex cannot settle (and must quote the answer as proof). Rulebook: Docs/QA_RULEBOOK.md.
   py -m copilot.eval.critic --selftest             critic tests itself on canned good / mutated bad answers (no LLM)
   py -m copilot.eval.critic --run [--md] [--only Q6 Q9]   replay the 18 questions through the copilot, then critique
   py -m copilot.eval.critic --transcript            critique the last saved run again without calling the copilot"""
import json
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from copilot import tools

from .golden import GOLDEN
from .oracle import Oracle

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "Docs" / "qa_runs"
PENALTY = {"critical": 40, "major": 15, "minor": 5}
JUDGE_MODEL = "gemma-4-31b-it"
ID = re.compile(r"\b(?:INS|MNT|REG|CTX|USR)-\d{4}-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*\b|\b(?:manual|sop|report|note):[\w.:-]+|\brule:\w+:\w+")
NAMED_VISUAL = [(r"heat ?map", "heatmap"), (r"line chart|trend", "line"), (r"bar chart", "bar"), (r"\bmap\b|pins", "map"),
                (r"status card|\bcard\b", "card"), (r"\btable\b|\blist\b", "table")]


def norm(s):
    return re.sub(r"(?<=\d),(?=\d{3})", "", str(s)).replace("$", "").lower()


def has(blob, item):
    return any(norm(a) in blob for a in ([item] if isinstance(item, str) else item))


def mk(cid, ok, sev, detail=""):
    return {"id": cid, "status": "pass" if ok is True else "fail" if ok is False else "undecided", "severity": sev, "detail": detail}


# ---------------------------------------------------------------- semantic behaviours: regex first, judge as fallback
def _line_with(text, needle):
    return " ".join(l for l in text.splitlines() if needle in l)


def _stale(text, res, p):
    return bool(re.search(r"recorded[_ ]status.{0,90}(out[- ]of[- ]date|outdated|stale|disagree|does not match|doesn't match|inconsisten)|"
                          r"(out[- ]of[- ]date|outdated|stale).{0,60}recorded", text, re.I | re.S))


def _no_reason(text, res, p):
    return all(re.search(r"no (recorded )?(reason|cause|explanation)|not? (a )?recorded (reason|cause)", _line_with(text, w) or text, re.I)
               for w in p)


def _conflict(text, res, p):
    return norm(p[0]) in norm(text) and bool(re.search(r"conflict|contradict|disagree|inconsisten|does not match|differs", text, re.I))


def _first_sentence(text):
    return re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]


def _concludes_producing(text, res, p):
    s = _first_sentence(text)
    return bool(re.search(r"producing|\byes\b", s, re.I)) and not re.search(r"not (currently )?producing|\bno,", s, re.I)


BEHAVIOURS = {  # name -> (regex/function check, judge question or None)
    "stale_status": (_stale, None),
    "no_recorded_reason": (_no_reason, None),
    "no_invented_cause": (None, "The wells {0} have no open repair and no active note. Does the answer avoid stating a specific cause "
                                "(e.g. a failed part) for them, saying no reason is recorded instead?"),
    "original_kept": (lambda t, r, p: p[0] in t and bool(re.search(r"original|previous|was|from|kept|estimate", t, re.I)),
                      "Does the answer say the original value {0} was kept or replaced by the corrected one?"),
    "now_producing": (lambda t, r, p: bool(re.search(r"(is|now|currently)\s+(\*\*)?producing|producing state:?\**\s*\**producing|"
                                                     r"above the .{0,12}limit", t, re.I)),
                      "Does the answer say the well is now producing after the correction?"),
    "conflict_surfaced": (_conflict, "Does the answer point out that {0} disagrees with or contradicts the new claim/correction?"),
    "ask_confirm": (lambda t, r, p: "confirm" in t.lower(), None),
    "removed_well_explained": (lambda t, r, p: bool(re.search(r"correct|no longer|removed|re-?measured|excluded", _line_with(t, p[0]) or "", re.I))
                               or (p[0] in t and bool(re.search(r"correct|no longer|re-?measured", t, re.I)) and p[1] in t),
                               "Does the answer say {0} is no longer listed because of {1}'s correction?"),
    "overdue_notice": (lambda t, r, p: "SR-01" in t and bool(re.search(r"overdue|no written notice|not recorded|no notice|none|breach", t, re.I)),
                       "Does the answer say a written regulator notice is overdue or missing for this spill?"),
    "report_outdated": (lambda t, r, p: p[0] in t and bool(re.search(r"outdated|no longer|stale|old estimate|moderate", t, re.I)),
                        "Does the answer say the earlier repair report {0} classed the spill using the old, now outdated volume?"),
    "follows_user_rule": (lambda t, r, p: p[0] in t and bool(re.search(r"\brule\b", t, re.I)),
                          "Does the answer say the threshold used comes from {0}'s rule rather than the manual?"),
    "concludes_producing": (_concludes_producing, "Does the answer conclude that the well IS producing oil?"),
    "only_one_needs_report": (None, "Does the answer say that only {0} needed a regulator report (other spills were below 5 bbl)?"),
    "no_prior_conversation": (lambda t, r, p: bool(re.search(r"(don'?t|do not|no|not)\b.{0,70}(record|history|conversation|discuss|earlier|previous|remember)", t, re.I | re.S)),
                              "Does the answer say it has no earlier conversation with this user about those wells?"),
    "yes_first": (lambda t, r, p: bool(re.search(r"\byes\b|was (real )?crude|it was (real )?oil", _first_sentence(t), re.I)), None),
    "both_kept": (lambda t, r, p: all(n in t for n in p), "Does the answer show both {0} and {1}'s statements?"),
    "unrecorded_shutin": (lambda t, r, p: bool(re.search(r"maintenance system|not (yet )?(been )?(recorded|entered|logged)", t, re.I)), None),
}


def judge_call(question_text, answer, rubric):
    """Ask the judge model a yes/no rubric question; it must return a verbatim quote or the result is undecided."""
    from copilot import agent
    key = agent.os.environ.get("LLM_API_KEY") or agent.os.environ.get("GEMINI_API_KEY")
    if not key:
        return None, ""
    prompt = (f"You are a strict QA judge. Rubric question: {rubric}\n\nAnswer under review:\n\"\"\"\n{answer}\n\"\"\"\n"
              'Reply with JSON only: {"verdict": "yes" or "no", "quote": "<exact words copied from the answer that justify it>"}')
    try:
        content = agent.call_llm([{"role": "user", "content": prompt}], key, model=JUDGE_MODEL, with_tools=False)["content"] or ""
        j = json.loads(re.search(r"\{.*\}", content, re.S).group(0))
    except Exception:
        return None, ""
    quote = j.get("quote", "")
    if j.get("verdict") not in ("yes", "no") or not quote or norm(quote) not in norm(answer):
        return None, ""  # no verbatim proof -> not trusted
    return j["verdict"] == "yes", quote


def behaviour_check(name, params, text, res, use_judge):
    advisory = name.endswith("?")
    name = name.rstrip("?")
    fn, rubric = BEHAVIOURS[name]
    sev = "minor" if advisory else "critical" if name == "no_invented_cause" else "major"
    ok = fn(text, res, params) if fn else None
    detail = "regex"
    if not ok and rubric and use_judge:
        v, quote = judge_call(None, text, rubric.format(*params))
        if v is not None:
            ok, detail = v, f"judge: \"{quote[:80]}\""
    return mk("B:" + name, ok, sev, detail if ok is not None else "needs judge (no key / no proof)")


# ---------------------------------------------------------------- numeric grounding
MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"


def numbers_in(text):
    t = ID.sub(" ", text)
    t = re.sub(r"WELL-\d{4}|\bU-\d{3}\b|\b[A-Z]{2,4}-\d{2,3}\b|\d{4}-\d{2}-\d{2}|\bT\d{3}\b|\b[A-Z]{2}\d+\b", " ", t)
    t = re.sub(rf"\b\d{{1,2}}\s+{MONTHS}\b|\b{MONTHS}\s+\d{{1,2}}\b", " ", t)
    t = re.sub(r"(?<=\d),(?=\d{3})", "", t)
    return [float(x) for x in re.findall(r"(?<![\w.])\d+(?:\.\d+)?", t)]


def grounded(text, res, question):
    src = json.dumps([res.get("tool_rows") or [], res.get("trace") or [], question], default=str)
    base = sorted({float(x) for x in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?", re.sub(r"(?<=\d),(?=\d{3})", "", src))})[:150]
    consts = {1, 2, 3, 4, 5, 7, 12, 14, 15, 20, 24, 25, 30, 60, 72, 90, 100}
    ok = set(base) | consts | {float(len(res.get("tool_rows") or [])), float(len(res.get("rows") or []))}
    for a in base:  # derived values: margins over a limit are differences; totals are per-column sums (below), never a+b of unrelated fields
        for b in base:
            ok.add(abs(a - b))
    cols = {}
    for r in res.get("tool_rows") or []:
        for k, v in r.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                cols[k] = cols.get(k, 0) + v
    ok.update(cols.values())
    bad = [n for n in numbers_in(text) if n > 12 and not any(abs(n - x) <= 0.051 for x in ok)]
    return bad


# ---------------------------------------------------------------- oracle comparisons (independent recomputation)
def _rows(res, *keys):
    return [r for r in res.get("tool_rows") or [] if all(k in r for k in keys)]


def oracle_check(name, O, res, step):
    if name == "q1_status":
        i = max(O.ins["WELL-0001"], key=lambda x: x["inspected_at"])
        d = round(i["wellhead_temp_c"] - i["ambient_temp_c"], 1)
        return (not O.producing("WELL-0001", i)) and str(d) in res["text"], f"oracle delta {d}, producing={O.producing('WELL-0001', i)}"
    if name == "q2_not_producing":
        exp = O.not_producing_now("NE-08")
        got = {r["asset_id"]: r["delta_c"] for r in _rows(res, "asset_id", "delta_c", "producing") if r["producing"] == 0}
        return got == exp, f"oracle {exp} vs tool {got}"
    if name == "q3_series":
        rows = _rows(res, "date", "producing")
        since = O.days_back(91)
        exp = [i["inspected_at"][:10] for i in O.ins["WELL-0001"] if since <= i["inspected_at"][:10] <= O.as_of]
        npd = [i["inspected_at"][:10] for i in O.ins["WELL-0001"] if i["inspected_at"][:10] in exp and not O.producing("WELL-0001", i)]
        return [r["date"] for r in rows] == exp and [r["date"] for r in rows if not r["producing"]] == npd, f"oracle {len(exp)} points, down {npd}"
    if name == "q4_spills":
        exp = {s["inspection_id"]: s["spill_est_volume_bbl"] for s in O.spills("WELL-0001", O.months_back(48), O.as_of)}
        got = {r["inspection_id"]: r["bbl"] for r in _rows(res, "inspection_id", "bbl")}
        return got == exp, f"oracle {len(exp)} spills {round(sum(exp.values()), 1)} bbl vs tool {len(got)}"
    if name == "q5_downtime":
        exp = O.downtime("WELL-0001", "2025-01-01", "2025-12-31")
        return str(exp) in norm(res["text"]), f"oracle {exp} days"
    if name == "q6_top3":
        exp = O.downtime_by_well("NE-07", O.months_back(4), O.as_of)
        got = {r["key"]: r["days"] for r in _rows(res, "key", "days")}
        return bool(got) and all(exp.get(k) == v for k, v in got.items()) and sorted(got.values(), reverse=True)[:3] == sorted(exp.values(), reverse=True)[:3], f"oracle top {sorted(exp.items(), key=lambda x: -x[1])[:4]}"
    if name == "q7_spills":
        exp = {}
        for a, w in O.wells.items():
            if w["area_id"] == "NE-08":
                for s in O.spills(a, O.days_back(90), O.as_of):
                    exp[a] = s["spill_est_volume_bbl"]
        got = {r["asset_id"]: r["bbl"] for r in _rows(res, "asset_id", "bbl")}
        return got == exp, f"oracle {exp}"
    if name == "q8_heatmap":
        exp = O.spills_by_area_month(2026)
        got = {(r["area"], int(r["month"][5:])): r["spills"] for r in _rows(res, "area", "month", "spills")}
        return got == exp, f"oracle total {sum(exp.values())} vs tool {sum(got.values())}"
    if name == "q9_breaches":
        exp = O.breaches("WELL-0001", O.months_back(12), O.as_of)
        got = {r["protocol_id"] for r in _rows(res, "protocol_id", "status") if r["status"] == "breach"}
        return got == exp, f"oracle {sorted(exp)} vs tool {sorted(got)}"
    if name == "q10_slow":
        exp = O.slow_containment("SW-24", O.days_back(90), O.as_of)
        got = {r["asset_id"] for r in _rows(res, "protocol_id", "asset_id") if r["protocol_id"] == "SR-02"}
        return got == set(exp), f"oracle {exp}"
    if name == "q11_costs":
        exp = {w: round(O.repair_cost(w, "2026-01-01", O.as_of)) for w in ("WELL-0121", "WELL-0138", "WELL-0107")}
        got = {r["asset_id"]: round(r["cost_usd"]) for r in _rows(res, "asset_id", "cost_usd", "jobs")}
        return got == exp, f"oracle {exp}"
    if name in ("q14_rca_manual", "q14_rca_user"):
        exp = O.rca_wells("NE-07", "pump_jack", {"T350": 2} if name.endswith("user") else {})
        got = {r["asset_id"] for r in _rows(res, "asset_id", "corrective_repairs")}
        return got == set(exp), f"oracle {sorted(exp)}"
    return None, "no oracle"


# ---------------------------------------------------------------- the evaluator
def segments(text):
    return [s for l in text.splitlines() for s in re.split(r"(?<=[.;])\s+", l) if s.strip()]


def evaluate(step, res, ctx):
    """-> {"key","status","score","checks":[...],"violations":[...],"layer":...}; status PASS|FAIL|ERROR|SKIPPED."""
    out = {"key": step["key"], "question": step["question"], "user": step["user"]}
    if res is None or any(ctx["results"].get(d, {}).get("status") in ("ERROR", "SKIPPED") for d in step["depends"]):
        return {**out, "status": "SKIPPED", "score": None, "checks": [], "violations": [], "layer": "infra",
                "detail": "a step this one depends on did not run"}
    if res.get("error"):
        return {**out, "status": "ERROR", "score": None, "checks": [], "violations": [], "layer": "infra", "detail": res["error"]}
    text, rows = res.get("text") or "", res.get("rows") or []
    cited = set(ID.findall(text))
    returned = set(res.get("tool_evidence") or []) | set(ID.findall(json.dumps(res.get("tool_rows") or [], default=str)))
    blob = norm(text + " " + json.dumps(rows, default=str) + " " + " ".join(res.get("evidence") or []))
    checks = []
    # facts
    missing = [m for m in step["must"] if not has(blob, m)]
    checks.append(mk("F1", not missing, "critical", f"missing {missing}" if missing else "all required facts present"))
    if step["must_not"]:
        leaked = [x for x in step["must_not"] if norm(x) in norm(text)]
        scope = "S2" if step["key"] == "Q16c" else "S1"
        checks.append(mk(scope, not leaked, "critical", f"must not appear: {leaked}" if leaked else "no out-of-scope data"))
    if step["wells_only"] is not None:
        seen = set(re.findall(r"WELL-\d{4}", text)) | {r.get("asset_id") or r.get("key") for r in rows if isinstance(r, dict)}
        extra = {w for w in seen if w and str(w).startswith("WELL-")} - step["wells_only"]
        checks.append(mk("S1w", not extra, "critical", f"wells outside the expected set: {sorted(extra)}" if extra else "wells match"))
    bad = grounded(text, res, step["question"])
    checks.append(mk("F3", not bad, "major", f"numbers not found in tool results: {bad}" if bad else "numbers grounded"))
    if step["oracle"]:
        ok, detail = oracle_check(step["oracle"], ctx["oracle"], res, step)
        checks.append(mk("F4", ok, "critical", detail))
    # citations
    unknown = [i for i in cited if not ctx["exists"](i)]
    checks.append(mk("C1", not unknown, "critical", f"cited ids not in the database: {unknown}" if unknown else "all cited ids exist"))
    fabricated = [i for i in cited if i not in returned and ctx["exists"](i)]
    checks.append(mk("C3", not fabricated, "critical", f"cited but never returned by a tool: {fabricated}" if fabricated else "citations came from tool results"))
    wrong = []
    for seg in segments(text):
        wells = {w[5:] for w in re.findall(r"WELL-\d{4}", seg)}
        if wells:
            wrong += [i for i in ID.findall(seg) if re.match(r"(INS|MNT|REG|CTX|USR)-(\d{4})-", i) and i.split("-")[1] not in wells]
    checks.append(mk("C2", not wrong, "critical", f"id attributed to the wrong well: {sorted(set(wrong))}" if wrong else "ids match their wells"))
    need = [e for e in step["evidence"] if e not in cited and e not in (res.get("evidence") or [])]
    checks.append(mk("C4", not need, "major", f"expected evidence not cited: {need}" if need else "expected evidence cited"))
    # visual
    named = next((v for pat, v in NAMED_VISUAL if re.search(pat, step["question"], re.I)), None)
    allowed = {named} if named else step["visual"]
    if allowed:
        checks.append(mk("V1", res.get("visual") in allowed, "major", f"visual {res.get('visual')!r}, expected {sorted(allowed)}"))
    # behaviours
    for name, *params in step["behaviours"]:
        checks.append(behaviour_check(name, params, text, res, ctx["judge"]))
    # hygiene
    bits = re.findall(r"\bU-\d{3}\b|\b(?:NE|SW)-\d{2}\b", text)
    checks.append(mk("H7", not bits, "minor", f"internal ids shown instead of names: {sorted(set(bits))}" if bits else "names used"))
    leak = re.findall(r"</?thought>|tool_call|rca_corrective_count|\"rows\"|has_recorded_reason", text)
    checks.append(mk("H8", not leak, "minor", f"internals leaked: {sorted(set(leak))}" if leak else "clean"))
    viol = [c for c in checks if c["status"] == "fail"]
    score = max(0, 100 - sum(PENALTY[c["severity"]] for c in viol))
    status = "FAIL" if any(c["severity"] in ("critical", "major") for c in viol) else "PASS"
    return {**out, "status": status, "score": score, "checks": checks, "violations": viol, "layer": layer_hint(viol, blob, res)}


def layer_hint(viol, blob, res):
    ids = {v["id"] for v in viol}
    if not ids:
        return None
    if ids & {"F4", "S1", "S2"} and not ids & {"F1"}:
        return "tool-logic"
    if ids & {"F1"}:
        miss = re.findall(r"'([^']+)'", next(v["detail"] for v in viol if v["id"] == "F1"))
        rows = norm(json.dumps(res.get("tool_rows") or [], default=str))
        return "prompt" if miss and all(norm(m) in rows for m in miss) else "tool-output"
    if ids & {"C1", "C2", "C3", "F3"}:
        return "model-noise"
    return "prompt"


# ---------------------------------------------------------------- running sessions
def make_ctx(db_path, dataset, judge=True):
    con = sqlite3.connect(db_path)
    q = {"INS": "SELECT 1 FROM inspections WHERE inspection_id=?", "MNT": "SELECT 1 FROM maintenance WHERE maintenance_id=?",
         "REG": "SELECT 1 FROM regulatory_events WHERE event_id=?", "CTX": "SELECT 1 FROM notes WHERE note_id=?",
         "USR": "SELECT 1 FROM notes WHERE note_id=?"}

    def exists(i):
        if ":" in i:
            return bool(con.execute("SELECT 1 FROM chunks WHERE chunk_id=?", (i,)).fetchone()) or i.startswith("rule:")
        return bool(con.execute(q[i[:3]], (i,)).fetchone())

    def sync_fix(O):
        O.fix = {}
        for t, f, v in con.execute("SELECT target_id, field, corrected_value FROM corrections WHERE status='active'"):
            O.fix.setdefault(t, {})[f] = v

    return {"exists": exists, "oracle": Oracle(dataset), "judge": judge, "results": {}, "sync_fix": sync_fix}


def active_corrections(db_path):
    con = sqlite3.connect(db_path)
    fix = {}
    for t, f, v in con.execute("SELECT target_id, field, corrected_value FROM corrections WHERE status='active'"):
        fix.setdefault(t, {})[f] = v
    con.close()
    return fix


def run_session(steps, key=None, retry_wait=60):
    """Replay steps through the real copilot on a throw-away DB copy; returns {key: result-or-error-dict}."""
    tmp = tools.clean_copy()  # tools.db() reconnects when the path changes
    from copilot import agent
    results = {}
    for s in steps:
        for attempt in (0, 1):
            try:
                r = agent.ask(s["question"], s["user"], ts=s["ts"], key=key)
                r.pop("history", None)
                r["_fix"] = active_corrections(tmp)  # overlay the oracle needs to judge this step later
                results[s["key"]] = r
                break
            except Exception as e:
                results[s["key"]] = {"error": f"{type(e).__name__}: {e}"}
                if attempt == 0:
                    time.sleep(retry_wait)
        print(f"ran {s['key']}: {'ERROR' if 'error' in results[s['key']] else 'ok'}", flush=True)
    return results, tmp


def critique(steps, results, db_path, judge=True):
    ctx = make_ctx(db_path, ROOT / "sample-data", judge)
    verdicts = []
    for s in steps:
        r = results.get(s["key"])
        if r and "_fix" in r:
            ctx["oracle"].fix = r["_fix"]
        else:
            ctx["sync_fix"](ctx["oracle"])
        v = evaluate(s, r, ctx)
        ctx["results"][s["key"]] = v
        verdicts.append(v)
    return verdicts


# ---------------------------------------------------------------- property mode: new questions, oracle supplies the answer
def prop_steps(O, n=8, seed=7):
    """Metamorphic variants of the benchmark questions on other wells/areas/windows. Expected facts come from the
    oracle (raw files), so this works on any dataset, including the hidden test set."""
    import random
    from .golden import g
    rnd = random.Random(seed)
    wells, areas = sorted(O.wells), sorted(O.areas)
    steps, tries = [], 0
    while len(steps) < n and tries < 200:
        tries += 1
        kind, w, a = rnd.choice(("now", "year", "top", "spills", "np", "cost")), rnd.choice(wells), rnd.choice(areas)
        key, an = f"P{len(steps) + 1}", O.areas[a]["name"]
        if kind == "now":
            i = max(O.ins[w], key=lambda x: x["inspected_at"])
            e = O._eff(i)
            d = round(e["wellhead_temp_c"] - e["ambient_temp_c"], 1)
            steps.append(g(key, "U-201", f"Is {w} producing oil right now? Show me its status card.", must=[str(d), i["inspection_id"]],
                           visual={"card"}, behaviours=[("concludes_producing",)] if O.producing(w, i) else []))
        elif kind == "year":
            y = rnd.choice((2024, 2025))
            steps.append(g(key, "U-201", f"How many days was {w} down in {y}?", must=[str(O.downtime(w, f"{y}-01-01", f"{y}-12-31"))],
                           visual={"text"}))
        elif kind == "top":
            m, k = rnd.choice((3, 6)), rnd.choice((2, 3))
            d = sorted(O.downtime_by_well(a, O.months_back(m), O.as_of).items(), key=lambda x: (-x[1], x[0]))
            if len(d) <= k or d[k - 1][1] == d[k][1] or d[k - 1][1] == 0:
                continue
            steps.append(g(key, "U-201", f"Which {k} wells in {an} had the most downtime in the last {m} months? Show a bar chart.",
                           must=[f"{x} " for x, _ in d[:k]] + [str(v) for _, v in d[:k]], visual={"bar"}, wells_only={x for x, _ in d[:k]}))
        elif kind == "spills":
            s = O.spills(w, O.months_back(24), O.as_of)
            steps.append(g(key, "U-201", f"How many oil spills has {w} had in the last 2 years, and how much oil in total? List them in a table.",
                           must=[str(round(sum(x["spill_est_volume_bbl"] for x in s), 1))] if s else [], visual={"table", "text"}))
        elif kind == "np":
            npw = O.not_producing_now(a)
            if not npw:
                continue
            steps.append(g(key, "U-201", f"Which wells in {an} are not producing oil right now? Show them in a table.",
                           must=list(npw) + [str(v) for v in npw.values()], visual={"table"}, wells_only=set(npw)))
        else:
            c = round(O.repair_cost(w, f"{O.as_of[:4]}-01-01", O.as_of))
            steps.append(g(key, "U-201", f"What have repairs cost for {w} this year?", must=[str(c)], visual={"text", "table", "bar", "card"}))
    return steps


# ---------------------------------------------------------------- report
def write_report(verdicts, results, path, prev):
    n = {k: sum(1 for v in verdicts if v["status"] == k) for k in ("PASS", "FAIL", "ERROR", "SKIPPED")}
    L = ["# QA report — copilot answers vs. 03-evaluation-queries.md", "",
         f"Rulebook: `Docs/QA_RULEBOOK.md`. **{n['PASS']} PASS · {n['FAIL']} FAIL · {n['ERROR']} ERROR (infra) · {n['SKIPPED']} SKIPPED** "
         f"of {len(verdicts)} steps. Critical or major violation ⇒ FAIL; ERROR/SKIPPED are not answer failures.", ""]
    reg = [v["key"] for v in verdicts if prev.get(v["key"]) == "PASS" and v["status"] == "FAIL"]
    fixed = [v["key"] for v in verdicts if prev.get(v["key"]) in ("FAIL", "ERROR") and v["status"] == "PASS"]
    if prev:
        L += [f"**Since last run:** regressions {reg or 'none'} · newly passing {fixed or 'none'}", ""]
    L += ["| Step | User | Status | Score | Violations | Fix layer |", "|---|---|---|---|---|---|"]
    for v in verdicts:
        L.append(f"| {v['key']} | {v['user']} | {v['status']} | {v['score'] if v['score'] is not None else '—'} | "
                 f"{', '.join(c['id'] for c in v['violations']) or '—'} | {v.get('layer') or '—'} |")
    for v in verdicts:
        if v["status"] in ("FAIL", "ERROR", "SKIPPED") or v["violations"]:
            L += ["", f"### {v['key']} — {v['status']}", f"> {v['question']}"]
            if v.get("detail"):
                L.append(f"- {v['detail']}")
            for c in v["violations"]:
                L.append(f"- **{c['id']}** ({c['severity']}): {c['detail']}")
            und = [c for c in v["checks"] if c["status"] == "undecided"]
            L += [f"- undecided {c['id']}: {c['detail']}" for c in und]
            r = results.get(v["key"]) or {}
            if r.get("text"):
                L += ["", "<details><summary>answer</summary>", "", r["text"], "", "</details>"]
    Path(path).write_text("\n".join(L) + "\n", encoding="utf-8")


def save_and_report(verdicts, results, md, tag=""):
    RUNS.mkdir(parents=True, exist_ok=True)
    last = RUNS / f"{tag}last_verdicts.json"
    prev = json.loads(last.read_text(encoding="utf-8")) if last.exists() else {}
    last.write_text(json.dumps({v["key"]: v["status"] for v in verdicts}), encoding="utf-8")
    (RUNS / f"{tag}transcript.json").write_text(json.dumps(results, default=str, indent=1), encoding="utf-8")
    (RUNS / f"{tag}verdicts.json").write_text(json.dumps(verdicts, default=str, indent=1), encoding="utf-8")
    if md:
        report = ROOT / "Docs" / (f"QA_REPORT_{tag.strip('_')}.md" if tag else "QA_REPORT.md")
        write_report(verdicts, results, report, prev)
        print("wrote", report.name)
    for v in verdicts:
        print(f"{v['key']:6} {v['status']:8} {v['score'] if v['score'] is not None else '-':>4}  "
              f"{','.join(c['id'] for c in v['violations'])}  {v.get('layer') or ''}")


# ---------------------------------------------------------------- self-test: the critic must catch known-bad answers
def selftest():
    step = {s["key"]: s for s in GOLDEN}
    db_path = tools.clean_copy()
    ctx = make_ctx(db_path, ROOT / "sample-data", judge=False)
    ctx["sync_fix"](ctx["oracle"])
    rows6 = [{"key": "WELL-0121", "days": 49, "weeks": 7}, {"key": "WELL-0107", "days": 42, "weeks": 6}, {"key": "WELL-0138", "days": 42, "weeks": 6}]
    ev6 = ["INS-0121-0189", "INS-0107-0194", "INS-0138-0195"]
    good6 = {"text": "The top 3 wells are:\n* **WELL-0121**: 49 days [INS-0121-0189]\n* **WELL-0107**: 42 days [INS-0107-0194]\n"
                     "* **WELL-0138**: 42 days [INS-0138-0195]", "visual": "bar", "rows": rows6, "tool_rows": rows6, "evidence": ev6,
             "tool_evidence": ev6, "trace": [{"tool": "downtime", "args": {"area_id": "NE-07", "top_n": 3, "last_months": 4}}]}
    tab = [{"asset_id": w, "delta_c": d, "producing": 0, "recorded_status": "active", "has_recorded_reason": ok, "inspection_id": i}
           for w, d, ok, i in (("WELL-0164", 4.1, False, "INS-0164-0205"), ("WELL-0170", 2.9, True, "INS-0170-0206"),
                               ("WELL-0172", 5.7, True, "INS-0172-0206"), ("WELL-0175", 0.4, False, "INS-0175-0204"))] + [
          {"asset_id": "WELL-0170", "maintenance_id": "MNT-0170-031"}, {"asset_id": "WELL-0172", "maintenance_id": "MNT-0172-028"}]
    good2 = {"text": "| Well | Wellhead above air | Reason |\n| WELL-0164 | 4.1 °C; recorded status active is out of date [INS-0164-0205] | No recorded reason; suggest a check |\n"
                     "| WELL-0170 | 2.9 °C [INS-0170-0206] | Repair MNT-0170-031 |\n| WELL-0172 | 5.7 °C [INS-0172-0206] | Repair MNT-0172-028 |\n"
                     "| WELL-0175 | 0.4 °C [INS-0175-0204] | No recorded reason; suggest a check |",
             "visual": "table", "rows": tab, "tool_rows": tab, "evidence": ["INS-0164-0205"], "trace": [],
             "tool_evidence": ["INS-0164-0205", "INS-0170-0206", "INS-0172-0206", "INS-0175-0204", "MNT-0170-031", "MNT-0172-028"]}
    good16c = {"text": "I don't have a record of any earlier conversation with you about wells.", "visual": "text", "rows": [], "tool_rows": [],
               "evidence": [], "tool_evidence": [], "trace": []}

    def mut(base, **kw):
        return {**base, **kw}
    cases = [  # (name, step key, result, expected status, check ids that must fail)
        ("good Q6", "Q6", good6, "PASS", []),
        ("good Q2", "Q2", good2, "PASS", []),
        ("good Q16c", "Q16c", good16c, "PASS", []),
        ("wrong number", "Q6", mut(good6, text=good6["text"].replace("49 days", "48 days")), "FAIL", ["F3"]),  # 48 is in no tool result
        ("wrong visual", "Q6", mut(good6, visual="table"), "FAIL", ["V1"]),
        ("citation of the wrong well", "Q6", mut(good6, text=good6["text"].replace("INS-0138-0195", "INS-0103-0203")), "FAIL", ["C2"]),
        ("fabricated citation", "Q6", mut(good6, text=good6["text"].replace("INS-0138-0195", "INS-0138-9999")), "FAIL", ["C1"]),
        ("cited id never returned", "Q6", mut(good6, text=good6["text"] + " See [INS-0121-0200].", tool_evidence=ev6), "FAIL", ["C3"]),
        ("invented cause", "Q2", mut(good2, text=good2["text"].replace("No recorded reason; suggest a check", "Pump jack bearing failure", 1)), "FAIL", ["B:no_recorded_reason"]),
        ("recorded_status trusted", "Q2", mut(good2, text=good2["text"].replace("recorded status active is out of date", "recorded status active")), "FAIL", ["B:stale_status"]),
        ("other user's data leaked", "Q16c", mut(good16c, text="The three wells cost $25,794, $46,942 and $5,176."), "FAIL", ["S2"]),
        ("extra well listed", "Q6", mut(good6, text=good6["text"] + "\n* **WELL-0119**: 28 days [INS-0119-0150]"), "FAIL", ["S1w"]),
        ("ungrounded number", "Q6", mut(good6, text=good6["text"] + " Total downtime was 973 days."), "FAIL", ["F3"]),
        ("tool rows disagree with raw data", "Q6", mut(good6, tool_rows=[{**rows6[0], "days": 56}, *rows6[1:]]), "FAIL", ["F4"]),
        ("internal ids shown (minor only)", "Q6", mut(good6, text=good6["text"] + " Recorded by U-201."), "PASS", ["H7"]),
        ("infra error is not a wrong answer", "Q6", {"error": "HTTPError: HTTP Error 429: Too Many Requests"}, "ERROR", []),
    ]
    bad = 0
    for name, key, res, want, must_fail in cases:
        ctx["results"] = {}
        v = evaluate(step[key], res, ctx)
        failed = {c["id"] for c in v["violations"]}
        ok = v["status"] == want and set(must_fail) <= failed and (want != "PASS" or not failed - set(must_fail))
        bad += not ok
        print(("ok  " if ok else "BAD ") + f"{name:36} -> {v['status']:6} {sorted(failed)}")
    skip = evaluate(step["Q12b"], {"text": "x"}, {**ctx, "results": {"Q12a": {"status": "ERROR"}}})
    print(("ok  " if skip["status"] == "SKIPPED" else "BAD ") + f"{'dependent of an ERROR step':36} -> {skip['status']}")
    sys.exit(1 if bad or skip["status"] != "SKIPPED" else 0)


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--selftest" in a:
        selftest()
    only = [x for x in a if re.fullmatch(r"Q\d+[a-z]?", x)]
    steps = [s for s in GOLDEN if not only or s["key"] in only]
    nojudge = "--nojudge" in a
    if "--transcript" in a:
        results = json.loads((RUNS / "transcript.json").read_text(encoding="utf-8"))
        db_path = RUNS / "session.db" if (RUNS / "session.db").exists() else tools.DB_PATH  # runtime notes live in the session DB
    elif "--prop" in a:  # fresh questions on other wells/areas/windows, expected answers from the oracle
        steps = prop_steps(Oracle(ROOT / "sample-data"), int(next((x for x in a if x.isdigit()), 8)))
        results, db_path = run_session(steps)
    elif "--run" in a:
        results, db_path = run_session(steps)
        RUNS.mkdir(parents=True, exist_ok=True)
        shutil.copy(db_path, RUNS / "session.db")
    else:
        sys.exit(__doc__)
    save_and_report(critique(steps, results, db_path, not nojudge), results, "--md" in a, "prop_" if "--prop" in a else "")
