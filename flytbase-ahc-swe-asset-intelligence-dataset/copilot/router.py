"""Rule-based router: question -> ordered plan of tool calls, with no model call. Returns None when it is not sure (statements,
corrections, unfamiliar phrasing); the caller then falls back to the LLM planner. A plan is a list of
{"tool", "args", optional "keep": {row_field: allowed values}}; an arg value "@ids" means "the wells the previous step recalled"."""
import re

from . import tools

KINDS = {"pump jack": "pump_jack", "rod string": "rod_string", "downhole pump": "downhole_pump", "flowline": "flowline", "separator": "separator"}
COUNTS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
ASKS = r"^(which|what|how|who|when|where|is|are|was|were|does|do|did|can|show|list|give|find|display|plot|compare|for)\b"
NOT_ROUTABLE = r"real oil|really|genuine|\bremeasured\b|re-measured|\bwrong\b|\bfyi\b"  # needs reading notes or recording something


def _areas(q):
    hits = []
    for a in tools.q("SELECT area_id, name FROM areas"):
        m = re.search(rf"{re.escape(a['name'])}|\b{a['area_id']}\b", q, re.I)
        if m:
            hits.append((m.start(), a["area_id"]))
    return [a for _, a in sorted(hits)]


def _period(q):
    """since/until/last_* keywords for the period the question names, {} when it names none."""
    today = tools.as_of()
    if m := re.search(r"last (\d+|a|one) (day|week|month|year)s?", q):
        n = 1 if m[1] in ("a", "one") else int(m[1])
        return {"last_months": n * 12} if m[2] == "year" else {f"last_{m[2]}s": n}
    if m := re.search(r"\b(20\d\d)\b", q):
        return {"since": f"{m[1]}-01-01", "until": f"{m[1]}-12-31"}
    if "this year" in q:
        return {"since": today[:4] + "-01-01"}
    return {}


def _top_n(q):
    if m := re.search(r"\btop (\d+)\b|\b(\d+|" + "|".join(COUNTS) + r") (?:most|wells)\b", q):
        v = m[1] or m[2]
        return int(v) if v.isdigit() else COUNTS[v]


def route(question):
    q = question.strip().lower()
    if not (q.endswith("?") or re.match(ASKS, q)) or re.search(NOT_ROUTABLE, q) or re.search(r"\b(since|before|after|between)\b", q):  # dated windows: LLM planner
        return None
    wells = list(dict.fromkeys(f"WELL-{n}" for n in re.findall(r"well[- ]?(\d{4})", q)))
    areas, period, top = _areas(question), _period(q), _top_n(q)
    if len(areas) > 1 or len(wells) > 1:
        return None  # comparisons across areas/wells need the LLM planner; the rules answer for one subject only
    area = {"area_id": areas[0]} if areas else {}
    well = {"well_id": wells[0]} if len(wells) == 1 else {}
    wtype = {"well_type": m[0].upper()} if (m := re.findall(r"\bt\d{3}\b", q)) else {}
    kind = next((v for k, v in KINDS.items() if k in q), None)
    has = lambda pat: re.search(pat, q)  # noqa: E731

    if has(r"(we|i) (discussed|talked about|asked about)|discussed (yesterday|earlier)|from my (first|earlier)") and has(r"repair|cost"):
        recall = {"days_ago": 1} if "yesterday" in q else {}
        n = COUNTS.get(next((w for w in COUNTS if re.search(rf"\b{w}\b", q)), ""), None)
        return [{"tool": "recall", "args": {**recall, **({"size": n} if n else {})}},
                {"tool": "repairs", "args": {"well_ids": "@ids", "group_by": "well", **(period or {"since": tools.as_of()[:4] + "-01-01"})}}]
    if has(r"root.cause|\brca\b") and kind:
        return [{"tool": "rca_candidates", "args": {"equipment_kind": kind, **area, **well}}]
    if has(r"not contained|contained within|sop time limit"):
        return [{"tool": "compliance", "args": {**area, **well, **wtype, **period}, "keep": {"protocol_id": ["SR-02"]}}]
    if has(r"report to the regulator|needed a report|reportable") and has(r"spill"):
        return [{"tool": "spills", "args": {**area, **well, **wtype, **period}, "keep": {"spill_class": ["reportable", "major"]}}]
    if has(r"\brules?\b|breach|compliance|violation|still open|regulator"):
        return [{"tool": "compliance", "args": {**area, **well, **wtype, **period}}]
    if has(r"spill"):
        if has(r"heat ?map|by .*month"):
            return [{"tool": "spills", "args": {"group_by": "area_month", **area, **period}}]
        return [{"tool": "spills", "args": {**area, **well, **wtype, **period}}]
    if well and has(r"planned|upcoming|scheduled"):
        return [{"tool": "well_status", "args": {"well_id": wells[0]}}]
    if has(r"downtime|\bdown\b|days .*(not producing|stopped)"):
        by = "area" if has(r"by area|per area") else "month" if has(r"by month|per month") else "well"
        return [{"tool": "downtime", "args": {"group_by": by, **area, **well, **wtype, **period, **({"top_n": top} if top else {})}}]
    if has(r"repair|maintenance") and has(r"cost|spen[dt]|how much|total|\bhow many\b|list|show|which"):
        ranked = has(r"\bmost\b|highest|biggest|\btop\b|per well|by well|each well")
        return [{"tool": "repairs", "args": {**area, **well, **wtype, **period, **({"equipment_kind": kind} if kind else {}),
                                             **({"group_by": "well"} if ranked else {})}, **({"top": top} if ranked and top else {})}]
    if well and has(r"line chart|trend|against air|vs\.? air|temperature"):
        return [{"tool": "series", "args": {**well, **(period or {"last_weeks": 13})}}]
    if well and has(r"\bnotes?\b"):
        return [{"tool": "well_notes", "args": {**well, **period}}]
    if well and has(r"producing|status|running|online|inspected|planned|downtime|shut"):
        return [{"tool": "well_status", "args": {"well_id": wells[0]}}]
    if has(r"\bwells?\b") and has(r"producing|stopped|shut in|not running"):
        stopped = has(r"not producing|stopped|shut in|not running|isn.t producing")
        return [{"tool": "find_wells", "args": {"producing": not stopped, **area, **wtype}}]
