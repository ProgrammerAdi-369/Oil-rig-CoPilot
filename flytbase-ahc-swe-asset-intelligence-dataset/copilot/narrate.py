"""Templated answers for every tool result: a headline with the key numbers, bullets with [ID] citations and the caveats
that matter. Always produces text, so an answer is never empty when the language model is slow or down. Every figure
is copied from the tool result; nothing is computed by a model."""
import re

from . import tools

MAX_ROWS = 12


def _g(v, unit=""):
    return "n/a" if v is None else f"{v:g}{unit}"


def _ids(*ids):
    return " ".join(f"[{i}]" for i in dict.fromkeys(i for i in ids if i))


def _where(a):
    names = {r["area_id"]: r["name"] for r in tools.q("SELECT area_id, name FROM areas")}
    return " in " + names.get(a["area_id"], a["area_id"]) if a.get("area_id") else ""


def _when(res):
    since, until = res.get("window") or (None, None)
    if not until:
        return ""
    return f" ({'up to' if since == '0000-01-01' else since + ' to'} {until})"


def _more(rows):
    return [f"- ...and {len(rows) - MAX_ROWS} more (see the table)."] if len(rows) > MAX_ROWS else []


def _note(n):
    span = f"{n['valid_from']} to {n['valid_to'] or 'open-ended'}"
    return f"- [{n['note_id']}] {n['author']} ({n['status']}, {span}): {n['text']}"


def well_status(res, a):
    if not res["rows"]:
        return res.get("error") or f"No such well {a.get('well_id')}."
    c = res["rows"][0]
    out = [f"**{c['asset_id']}** ({c['area_name']}, {c['well_type']}) is **{'producing oil' if c['producing'] else 'NOT producing oil'}** as of "
           f"{c['last_inspected_at'][:10]} {_ids(c['last_inspection'])}. Wellhead {_g(c['wellhead_temp_c'], ' °C')} vs air "
           f"{_g(c['ambient_temp_c'], ' °C')}: **{_g(c['delta_c'], ' °C')} above air**; a {c['well_type']} well must be at least "
           f"{_g(c['limit_c'], ' °C')} above air to count as producing."]
    if (c["recorded_status"] == "active") != c["producing"]:
        out.append(f"The recorded status is \"{c['recorded_status']}\", which is out of date against the latest inspection.")
    out.append(f"Last inspected by {c['inspector']} ({c['method']})." + (f" Inspector note: \"{c['inspector_note']}\"" if c["inspector_note"] else ""))
    for f in c["corrections"]:
        out.append(f"Reading corrected from {_g(f['original_value'])} to {_g(f['corrected_value'])} by {f['author']} ({f['reason']}); "
                   f"the original is kept {_ids(f['target_id'])}.")
    if c["active_notes"]:
        out += ["Active notes:"] + [_note(n) for n in c["active_notes"]]
    if c["upcoming_notes"]:
        out += ["Planned / upcoming:"] + [_note(n) for n in c["upcoming_notes"]]
    if c["open_repairs"]:
        out += ["Open repairs:"] + [f"- [{r['maintenance_id']}] {r['equipment_kind']}: {r['issue']} (started {r['started_at'][:10]})"
                                    for r in c["open_repairs"]]
    if not c["producing"] and not c["active_notes"] and not c["open_repairs"]:
        out.append("No reason is recorded for the stop (no open repair, no active note). I will not guess a cause; a field check is the next step.")
    return "\n".join(out)


def find_wells(res, a):
    rows, state = res["rows"], "producing" if a.get("producing") else "not producing"
    out = [f"**{len(rows)} wells{_where(a)} are {state}** by their latest inspection (corrections applied)."]
    for r in rows[:MAX_ROWS]:
        line = f"- [{r['asset_id']}] {_g(r['delta_c'], ' °C')} above air (needs {_g(r['limit_c'], ' °C')}) {_ids(r['inspection_id'])}"
        if not a.get("producing"):
            if r["recorded_status"] == "active":
                line += "; recorded status \"active\" is out of date"
            reasons = [f"repair {_ids(m['maintenance_id'])} {m['issue']}" for m in r["open_repairs"]] + \
                      [f"note {_ids(n['note_id'])} \"{n['text']}\"" for n in r["active_notes"]]
            line += ("; " + "; ".join(reasons)) if reasons else "; no recorded reason" + (f" (inspector: \"{r['inspector_note']}\")" if r["inspector_note"] else "")
        out.append(line)
    out += _more(rows)
    if res.get("note"):
        out.append(res["note"])
    return "\n".join(out)


def downtime(res, a):
    rows = res["rows"]
    if not rows:
        return f"No non-producing inspections{_where(a)}{_when(res)}, so zero days of downtime."
    by = a.get("group_by", "well")
    if a.get("well_id"):
        r = rows[0]
        head = f"**{r['key']} was down {r['days']:g} days**{_when(res)}: {r['weeks']} weekly inspections found it not producing, 7 days each."
        out = [head]
    else:
        out = [f"**Downtime by {by}{_where(a)}**{_when(res)} (7 days per non-producing weekly inspection):"]
        out += [f"- {r['key']}: **{r['days']:g} days** ({r['weeks']} inspections)" for r in rows[:MAX_ROWS]] + _more(rows)
    out.append(f"Based on {len(res['evidence'])} non-producing inspections, e.g. {_ids(*res['evidence'][:2])}. "
               "This counts inspections, not the maintenance downtime_hours field.")
    return "\n".join(out)


def spills(res, a):
    rows = res["rows"]
    if a.get("group_by") == "area_month":
        out = [f"**Real spills by area and month**{_when(res)} (voided detections excluded):"]
        out += [f"- {area}: **{n} spills**" for area, n in res["totals"].items()]
        return "\n".join(out)
    if not rows:
        return f"No real spills{_where(a)}{_when(res)} match."
    total = round(sum(r["bbl"] for r in rows), 2)
    out = [f"**{len(rows)} real spill{'s' if len(rows) != 1 else ''}{_where(a)}**{_when(res)}, **{total:g} bbl** in total (corrected volumes):"]
    out += [f"- {r['date']} [{r['asset_id']}] {r['bbl']:g} bbl, {r['spill_class']}, {_g(r['spill_area_pct'], '% of pad')} {_ids(r['inspection_id'])}"
            for r in rows[:MAX_ROWS]] + _more(rows)
    return "\n".join(out)


def compliance(res, a):
    rows, actions = res["rows"], res.get("open_actions") or []
    fmt = lambda d: re.sub(r"USD (\d{4,})", lambda m: f"USD {int(m[1]):,}", d)  # noqa: E731
    line = lambda r: (f"- **{r['protocol_id']}** [{r['asset_id']}] {r['status']}: {fmt(r['detail'])}"  # noqa: E731
                      f"{' (due ' + r['due'][:10] + ')' if r.get('due') else ''} {_ids(*r['evidence'])}")
    if not rows and not actions:
        return f"No breaches or open duties{_where(a)}{_when(res)}."
    breaches = [r for r in rows if r["status"] == "breach"]
    out = [f"**{len(breaches)} breach{'es' if len(breaches) != 1 else ''} and {len(rows) - len(breaches)} open "
           f"dut{'ies' if len(rows) - len(breaches) != 1 else 'y'}{_where(a)}**{_when(res)}:"]
    out += [line(r) for r in rows[:MAX_ROWS]] + _more(rows)
    if actions:
        out += ["Open actions (not breaches):"] + [line(r) for r in actions]
    return "\n".join(out)


def repairs(res, a):
    rows = res["rows"]
    if not rows:
        return f"No repairs{_where(a)}{_when(res)}."
    if a.get("group_by") == "well":
        total = sum(r["cost_usd"] or 0 for r in rows)
        out = [f"**{'Top ' + str(res['top']) + ' wells by repair cost' if res.get('top') else 'Repair cost by well'}{_where(a)}**{_when(res)}: "
               f"**${total:,.0f}** over {sum(r['jobs'] for r in rows)} jobs."]
        return "\n".join(out + [f"- [{r['asset_id']}] **${r['cost_usd']:,.0f}** over {r['jobs']} jobs" for r in rows[:MAX_ROWS]] + _more(rows))
    out = [f"**{len(rows)} repair{'s' if len(rows) != 1 else ''}{_where(a)}**{_when(res)}, **${res['total_cost_usd']:,.0f}** in total:"]
    out += [f"- {r['started']} [{r['asset_id']}] {r['maintenance_type']} {r['equipment_kind']}: {r['issue']} (${r['cost_usd']:,.0f}) "
            f"{_ids(r['maintenance_id'])}" for r in rows[:MAX_ROWS]] + _more(rows)
    return "\n".join(out)


def rca_candidates(res, a):
    kind = a["equipment_kind"].replace("_", " ")
    if not res["rows"]:
        return f"No wells{_where(a)} have enough corrective {kind} repairs to need a root-cause analysis."
    out = [f"**{len(res['rows'])} wells{_where(a)} need a root-cause analysis on the {kind}:**"]
    out += [f"- [{r['asset_id']}] ({r['well_type']}) {r['corrective_repairs']} corrective repairs in the rule window, threshold {r['threshold']:g} "
            f"from {r['threshold_source']} {_ids(*r['repairs'])}" for r in res["rows"]]
    return "\n".join(out)


def well_notes(res, a):
    if not res["rows"]:
        return f"No notes on {a['well_id']}{_when(res)}."
    return "\n".join([f"**{len(res['rows'])} notes on {a['well_id']}**{_when(res)}:"] +
                     [f"- {n['date']} [{n['note_id']}] {n['author']} ({n['note_type']}, {n['status']}): {n['text']}" for n in res["rows"][:MAX_ROWS]] +
                     _more(res["rows"]))


def series(res, a):
    rows = res["rows"]
    if not rows:
        return f"No inspections for {a['well_id']}{_when(res)}."
    stopped = [r for r in rows if not r["producing"]]
    out = [f"**{a['well_id']}**: {len(rows)} weekly inspections{_when(res)}, not producing in **{len(stopped)}** of them."]
    out += [f"- {r['date']} wellhead {_g(r['wellhead_temp_c'])} vs air {_g(r['ambient_temp_c'])} = {_g(r['delta_c'])} °C above air "
            f"(needs {_g(r['limit_c'])}) {_ids(r['inspection_id'])}" for r in stopped[-MAX_ROWS:]]
    return "\n".join(out)


def recall(res, a):
    if res.get("empty") or not res["rows"]:
        return "I have no earlier conversation of yours that matches, so I cannot tell which wells you mean. Name them and I will look them up."
    c = res["chosen"]
    return f"From your question on {c['day']} (\"{c['label']}\"): {', '.join(c['well_ids'])}."


HELP = ("I can answer questions about a well's status, which wells are or are not producing, downtime, spills, compliance breaches, "
        "repairs and costs, root-cause-analysis candidates, notes and temperature trends. I could not map this question to one of those "
        "with the language model unavailable. Nothing was recorded or changed. Try again in a moment, or name a well (WELL-0001), an area "
        "(Northeast Block 7) and a period (last 4 months).")

TOOLS = {f.__name__: f for f in (well_status, find_wells, downtime, spills, compliance, repairs, rca_candidates, well_notes, series, recall)}


def narrate(steps):
    """steps: [{"tool", "args", "res"}] in plan order -> the answer text."""
    return "\n\n".join(TOOLS[s["tool"]](s["res"], s["args"]) if "rows" in s["res"] else f"I could not run {s['tool']}: {s['res'].get('error')}"
                       for s in steps)
