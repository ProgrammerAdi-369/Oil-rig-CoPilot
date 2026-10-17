"""Presentation layer between the tools and the UI: turns tool rows into ready-to-draw views, resolves citation ids into
readable cards, and computes the overview / audit-log feeds. No LLM here; every value comes from the database."""
import json
import re

from . import tools
from .tools import as_of, q

STEP_LABELS = {
    "well_status": "Reading the latest inspection, notes and open repairs...",
    "find_wells": "Scanning every well's latest inspection...",
    "series": "Loading the wellhead vs air temperature history...",
    "downtime": "Counting non-producing inspections (7 days each)...",
    "spills": "Querying real spills (corrections applied)...",
    "compliance": "Checking SOP deadlines against regulator events...",
    "repairs": "Summing repairs in the window...",
    "rca_candidates": "Counting corrective repairs against the RCA rule...",
    "well_notes": "Reading human notes on the well...",
    "search": "Searching manuals, SOPs and repair reports...",
    "correct_value": "Recording the correction (original value kept)...",
    "add_well_note": "Recording the note and checking it against the data...",
    "add_type_rule": "Saving the well-type rule...",
    "recall": "Recalling your earlier conversations...",
}
ID_KEYS = ("maintenance_id", "note_id", "event_id", "inspection_id", "asset_id", "id")
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def steps(trace):
    return [{"tool": t["tool"], "label": STEP_LABELS.get(t["tool"], f"Running {t['tool']}..."), "rows": t["n_rows"], "error": t["error"]}
            for t in trace or []]


def cell(v):
    """One table cell: nested lists/dicts become short readable text, never raw JSON."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return round(v, 2)
    if isinstance(v, (list, tuple)):
        parts = []
        for x in v:
            if isinstance(x, dict):
                parts.append(next((str(x[k]) for k in ID_KEYS if x.get(k)), cell(x)))
            else:
                parts.append(str(cell(x)))
        return ", ".join(parts)
    if isinstance(v, dict):
        return ", ".join(f"{k}: {cell(x)}" for k, x in v.items() if x is not None)[:140]
    return v


def label(k):
    return k.replace("_", " ")


def _wells_table(rows):
    """find_wells rows as a readable table: the well, its state, the margin, and the recorded reason for a stop."""
    cols = [("asset_id", "Well"), ("well_type", "Type"), ("producing", "Status"), ("delta_c", "Above air °C"), ("limit_c", "Limit °C"),
            ("recorded_status", "Recorded status"), ("reason", "Recorded reason"), ("inspector_note", "Inspector note")]
    out = []
    for r in rows[:200]:
        why = [f"{m['maintenance_id']}: {m['issue']}" for m in r.get("open_repairs", [])] + [n["text"] for n in r.get("active_notes", [])]
        out.append({**{k: cell(r.get(k)) for k, _ in cols if k != "reason"}, "reason": " · ".join(why) or "none recorded"})
    return {"type": "table", "columns": [{"key": k, "label": lab} for k, lab in cols], "rows": out}


def _table(rows):
    if {"asset_id", "producing", "delta_c", "has_recorded_reason"} <= set(rows[0]):
        return _wells_table(rows)
    cols = []
    for r in rows[:50]:
        cols += [k for k in r if k not in cols and not k.startswith("_") and k not in ("lat", "lon", "text")]
    cols = cols[:12]
    return {"type": "table", "columns": [{"key": c, "label": label(c)} for c in cols],
            "rows": [{c: cell(r.get(c)) for c in cols} for r in rows[:200]]}


def _card(rows):
    r = rows[0]
    if "last_inspection" not in r:
        return {"type": "card", "kind": "generic", "title": "Result",
                "items": [{"label": label(k), "value": cell(v)} for k, v in r.items() if v not in (None, "", [], {}) and not k.startswith("_")][:16]}
    stale = (r.get("recorded_status") == "active" and not r["producing"]) or (r.get("recorded_status") == "down" and r["producing"])
    return {"type": "card", "kind": "well", "title": f"{r['asset_id']} · {r.get('name', '')}", "subtitle": f"{r.get('well_type')} · {r.get('area_name')}",
            "producing": bool(r["producing"]), "headline": "Producing oil" if r["producing"] else "Not producing oil",
            "metrics": [
                {"label": "Wellhead above air", "value": f"{r['delta_c']} °C", "sub": f"limit {r['limit_c']:g} °C for {r.get('well_type')}"},
                {"label": "Wellhead / air", "value": f"{r['wellhead_temp_c']} / {r['ambient_temp_c']} °C",
                 "sub": f"raw wellhead {r['wellhead_temp_raw_c']} °C (corrected)" if r["wellhead_temp_raw_c"] != r["wellhead_temp_c"] else "latest reading"}],
            "facts": [
                {"label": "Last inspection", "value": f"{r['last_inspection']} · {r['last_inspected_at'][:10]} · {r['method']} · {r['inspector']}"},
                {"label": "Recorded status", "value": r.get("recorded_status"), "flag": "out of date vs the inspection" if stale else None},
                {"label": "Inspector note", "value": r.get("inspector_note") or "—"}],
            "notes": [{"id": n["note_id"], "text": n["text"], "author": n["author"], "status": n["status"], "from": n["valid_from"], "to": n["valid_to"]}
                      for n in r.get("active_notes", [])],
            "upcoming": [{"id": n["note_id"], "text": n["text"], "author": n["author"], "from": n["valid_from"], "to": n["valid_to"]}
                         for n in r.get("upcoming_notes", [])],
            "repairs": [{"id": m["maintenance_id"], "text": f"{m['equipment_kind']}: {m['issue']} (started {m['started_at'][:10]})"} for m in r.get("open_repairs", [])],
            "corrections": [{"text": f"{c['field']}: {c['original_value']} → {c['corrected_value']} by {c.get('author') or c['author_user_id']} ({c['reason']})"}
                            for c in r.get("corrections", [])]}


def _bar(rows):
    if rows and "key" in rows[0] and "days" in rows[0]:
        return {"type": "bar", "unit": "days", "items": [{"label": r["key"], "value": r["days"]} for r in rows]}
    if rows and "asset_id" in rows[0] and "cost_usd" in rows[0] and "jobs" in rows[0]:
        return {"type": "bar", "unit": "USD", "items": [{"label": r["asset_id"], "value": r["cost_usd"]} for r in rows]}
    lab = next((k for k, v in rows[0].items() if isinstance(v, str)), None)
    num = next((k for k, v in rows[0].items() if isinstance(v, (int, float)) and not isinstance(v, bool)), None)
    return {"type": "bar", "unit": label(num), "items": [{"label": r[lab], "value": r[num]} for r in rows]} if lab and num else None


def _line(rows):
    if not (rows and "date" in rows[0] and "wellhead_temp_c" in rows[0]):
        return None
    return {"type": "line", "limit": rows[0].get("limit_c"), "points": [
        {"date": r["date"], "wellhead": r["wellhead_temp_c"], "ambient": r["ambient_temp_c"], "delta": r["delta_c"], "producing": bool(r["producing"])} for r in rows]}


def _map(rows):
    pins = [r for r in rows if r.get("lat") is not None and r.get("lon") is not None]
    if not pins:
        return None
    return {"type": "map", "pins": [{"id": r.get("asset_id"), "lat": r["lat"], "lon": r["lon"],
                                     "detail": r.get("detail") or " · ".join(
                                         str(x) for x in (f"{r['bbl']} bbl" if "bbl" in r else None, r.get("date"), r.get("spill_class")) if x)} for r in pins]}


def _heatmap(rows):
    if not (rows and {"area", "month", "spills"} <= set(rows[0])):
        return None
    areas = list(dict.fromkeys(r["area"] for r in rows))
    months = sorted({r["month"] for r in rows})
    grid = {(r["area"], r["month"]): r["spills"] for r in rows}
    cells = [[grid.get((a, m), 0) for m in months] for a in areas]
    return {"type": "heatmap", "rows": areas, "cols": [MONTHS[int(m[5:]) - 1] for m in months], "cells": cells,
            "totals": [sum(c) for c in cells], "max": max(max(c) for c in cells)}


BUILDERS = {"card": _card, "bar": _bar, "line": _line, "map": _map, "heatmap": _heatmap, "table": _table}


def view(visual, rows):
    """Ready-to-draw structure for the chosen visual; falls back to a table if the rows do not fit it; None for text answers."""
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    if not rows or visual == "text":
        return None
    try:
        v = BUILDERS.get(visual, _table)(rows)
    except (KeyError, TypeError, ValueError, IndexError):
        v = None
    return v or _table(rows)


# ---------------------------------------------------------------- composing several visuals for one answer
MAX_VISUALS, MAX_COMPANIONS = 4, 2
TOOL_TITLES = {
    "well_status": "Well status", "find_wells": "Wells at their latest inspection", "series": "Wellhead vs air temperature",
    "downtime": "Downtime", "spills": "Real spills", "compliance": "SOP breaches and pending duties", "repairs": "Repairs",
    "rca_candidates": "Root-cause analysis candidates", "well_notes": "Human notes"}
SUFFIX = {"map": " · locations", "table": " · data", "bar": " · chart", "line": " · trend", "card": "", "heatmap": " · heatmap"}


def strict_view(visual, rows):
    """Like view() but without the table fallback: None when the rows do not fit the visual (a map needs coordinates...)."""
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    if not rows or visual not in BUILDERS:
        return None
    if visual == "card" and "last_inspection" not in rows[0]:
        return None
    try:
        return BUILDERS[visual](rows)
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def _span(window):
    if not window or len(window) != 2:
        return ""
    fmt = lambda d: f"{int(d[8:])} {MONTHS[int(d[5:7]) - 1]} {d[:4]}"
    return f"{fmt(window[0])} – {fmt(window[1])}" if window[0] > "0001" else f"until {fmt(window[1])}"


def _caption(args, window):
    bits = []
    if args.get("area_id"):
        name = q("SELECT name FROM areas WHERE area_id=?", args["area_id"])
        bits.append(name[0]["name"] if name else args["area_id"])
    for k in ("well_id", "well_type", "equipment_kind"):
        if args.get(k):
            bits.append(str(args[k]))
    if span := _span(window):
        bits.append(span)
    return " · ".join(bits)


def _entry(source, tool, args, window, visual, v, rows):
    title = TOOL_TITLES.get(tool, tool.replace("_", " ").capitalize())
    if tool == "spills" and args.get("group_by") == "area_month":
        title = "Real spills by area and month"
    default = {"well_status": "card", "series": "line", "downtime": "bar", "find_wells": "table", "compliance": "table"}.get(tool)
    return {"source": source, "tool": tool, "type": v["type"], "title": title + (SUFFIX[v["type"]] if default != v["type"] else ""),
            "caption": _caption(args, window), "view": v, "n_rows": len(rows)}


# companions: tool -> function(args, rows) -> [(visual, rows, tool, args, window)]; computed with the existing tools, no LLM
def _c_well_status(args, rows):
    w = rows[0]["asset_id"]
    r = tools.series(w, last_weeks=13)
    return [("line", r["rows"], "series", {"well_id": w}, r["window"])]


def _c_series(args, rows):
    r = tools.well_status(args["well_id"])
    return [("card", r["rows"], "well_status", {"well_id": args["well_id"]}, None)] if r["rows"] else []


def _c_find_wells(args, rows):
    ids = [r["asset_id"] for r in rows if r.get("asset_id")]
    if not ids:
        return []
    coords = q(f"SELECT asset_id, lat, lon FROM wells WHERE asset_id IN ({','.join('?' * len(ids))})", *ids)
    by = {r["asset_id"]: r for r in rows}
    pins = [{**c, "detail": f"{by[c['asset_id']].get('delta_c')} °C above air · {'producing' if by[c['asset_id']].get('producing') else 'not producing'}"} for c in coords]
    return [("map", pins, "find_wells", args, None)]


def _c_spills(args, rows):
    if args.get("group_by") == "area_month" or not rows or "bbl" not in rows[0]:
        return []
    out = [("map", rows, "spills", args, None)]
    per = {}
    for r in rows:
        per[r["asset_id"]] = round(per.get(r["asset_id"], 0) + r["bbl"], 2)
    if len(per) > 1:
        out.append(("bar", [{"well": w, "bbl": b} for w, b in sorted(per.items(), key=lambda x: -x[1])], "spills", args, None))
    return out


def _c_downtime(args, rows):
    if not rows or "days" not in rows[0]:
        return []
    group = args.get("group_by", "well")
    return [("table", [{group: r["key"], "days down": r["days"], "weeks not producing": r["weeks"]} for r in rows], "downtime", args, None)]


def _c_compliance(args, rows):
    if not rows or "protocol_id" not in rows[0]:
        return []
    counts = {}
    for r in rows:
        k = f"{r['protocol_id']} {r['status']}"
        counts[k] = counts.get(k, 0) + 1
    return [("bar", [{"protocol": k, "count": n} for k, n in sorted(counts.items())], "compliance", args, None)]


def _c_repairs(args, rows):
    if rows and "maintenance_id" in rows[0]:
        per = {}
        for r in rows:
            per[r["equipment_kind"]] = per.get(r["equipment_kind"], 0) + (r["cost_usd"] or 0)
        return [("bar", [{"equipment": k, "cost usd": round(v)} for k, v in sorted(per.items(), key=lambda x: -x[1])], "repairs", args, None)] if len(per) > 1 else []
    if rows and "jobs" in rows[0]:
        return [("table", [{"well": r["asset_id"], "jobs": r["jobs"], "cost usd": round(r["cost_usd"])} for r in rows], "repairs", args, None)]
    return []


def _c_rca(args, rows):
    if not rows or "corrective_repairs" not in rows[0]:
        return []
    return [("bar", [{"well": r["asset_id"], "corrective repairs": r["corrective_repairs"]} for r in rows], "rca_candidates", args, None)]


COMPANIONS = {"well_status": _c_well_status, "series": _c_series, "find_wells": _c_find_wells, "spills": _c_spills, "downtime": _c_downtime,
              "compliance": _c_compliance, "repairs": _c_repairs, "rca_candidates": _c_rca}


def compose(named, tool_results, visual):
    """Plan the visuals of one answer. Order: the primary visual (what the answer is about, or the first the user named), the other
    visuals the user named, every other tool result, then up to two companions. Capped at four, de-duplicated; a visual whose data
    does not fit is skipped, never faked."""
    if not tool_results:
        return []
    out, seen = [], set()

    def add(source, tool, args, window, vis, rows, strict=True):
        if len(out) >= MAX_VISUALS:
            return False
        v = strict_view(vis, rows) if strict else view(vis, rows)
        key = json.dumps(v, sort_keys=True, default=str) if v else None
        if not v or key in seen:
            return False
        seen.add(key)
        out.append({"id": f"v{len(out)}", **_entry(source, tool, args, window, vis, v, rows)})
        return True

    primary = tool_results[-1]
    if visual == "text" and not named:
        return []  # a short answer: no component
    add("primary", primary["tool"], primary["args"], primary["window"], visual, primary["rows"], strict=False)
    for vis in named:  # the other visuals the user asked for, from the newest result that fits
        if vis != visual:
            for res in reversed(tool_results):
                if add("named", res["tool"], res["args"], res["window"], vis, res["rows"]):
                    break
    for res in tool_results[:-1]:  # what else the model looked at
        add("tool", res["tool"], res["args"], res["window"], res["visual"], res["rows"])
    added = 0
    for vis, rows, tool, args, window in COMPANIONS.get(primary["tool"], lambda a, r: [])(primary["args"], primary["rows"]):
        if added < MAX_COMPANIONS and add("companion", tool, args, window, vis, rows):
            added += 1
    return out


# ---------------------------------------------------------------- citations
def _clip(s, n=420):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def evidence_card(eid):
    """Readable card for a cited id (inspection, repair report, regulator event, note, manual/SOP/report chunk, rule)."""
    try:
        if eid.startswith("INS-"):
            r = q("""SELECT e.*, u.name AS inspector, i.wellhead_temp_c AS raw_temp FROM inspection_eff e JOIN inspections i USING (inspection_id)
                     JOIN users u ON u.user_id=e.inspector_user_id WHERE e.inspection_id=?""", eid)
            if r:
                r = r[0]
                spill = f" Spill: {r['spill_bbl']} bbl over {r['spill_area_pct']}% of the pad{' (voided by a correction)' if not r['spill_real'] else ''}." if r["spill_detected_raw"] else ""
                fix = f" Wellhead corrected from {r['raw_temp']} °C." if r["raw_temp"] != r["wh_temp_c"] else ""
                return {"id": eid, "kind": "inspection", "title": f"Inspection {eid} — {r['asset_id']}",
                        "snippet": _clip(f"{r['inspected_at'][:16].replace('T', ' ')} by {r['inspector']} ({r['method']}). Wellhead {r['wh_temp_c']} °C, air {r['ambient_temp_c']} °C: "
                                         f"{round(r['delta_c'], 1)} °C above air against a {r['delta_limit_c']:g} °C limit → {'producing' if r['producing'] else 'not producing'}.{spill}{fix} {r['notes'] or ''}"),
                        "source": "inspections.jsonl"}
        elif eid.startswith("MNT-"):
            r = q("SELECT * FROM maintenance WHERE maintenance_id=?", eid)
            if r:
                r = r[0]
                comp = q("SELECT protocol_id, result, detail FROM report_compliance WHERE maintenance_id=? AND result != 'Met'", eid)
                extra = " Compliance: " + "; ".join(f"{c['protocol_id']} {c['result']} ({c['detail']})" for c in comp) if comp else ""
                return {"id": eid, "kind": "repair", "title": f"Repair {eid} — {r['asset_id']} {r['equipment_kind']} ({r['maintenance_type']})",
                        "snippet": _clip(f"{r['issue']} → {r['action_taken']}. {r['started_at'][:10]} to {r['completed_at'][:10]}, cost USD {r['cost_total']:,.0f}. "
                                         f"Root cause: {r['root_cause'] or 'n/a'}.{extra}"), "source": r["report_file"] or "maintenance.jsonl"}
        elif eid.startswith("REG-"):
            r = q("SELECT * FROM regulatory_events WHERE event_id=?", eid)
            if r:
                r = r[0]
                return {"id": eid, "kind": "regulator", "title": f"{r['event_type'].replace('_', ' ')} {eid} — {r['asset_id']}",
                        "snippet": _clip(f"{r['date']} · {r['agency']} · {r['protocol_id']} · status {r['status']}"
                                         f"{' · fine USD ' + format(r['fine_usd'], ',.0f') if r['fine_usd'] else ''}. {r['detail']}"), "source": "regulatory-events.jsonl"}
        elif eid.startswith(("CTX-", "USR-")):
            r = q("SELECT n.*, u.name AS author FROM notes n JOIN users u ON u.user_id=n.author_user_id WHERE note_id=?", eid)
            if r:
                r = r[0]
                return {"id": eid, "kind": "note", "title": f"{r['note_type'].replace('_', ' ')} {eid} — {r['asset_id']}",
                        "snippet": _clip(f"{r['author']} on {r['created_at'][:10]} (status {r['status']}; valid {r['valid_from']} → {r['valid_to'] or 'open'}): {r['text']}"),
                        "source": "context.jsonl" if eid.startswith("CTX-") else "added in the copilot"}
        elif eid.startswith("rule:"):
            _, wtype, key = eid.split(":", 2)
            r = tools.rule(key, wtype)
            return {"id": eid, "kind": "rule", "title": f"Rule {key} for {wtype}", "snippet": f"{key} = {r['value']:g} ({r['label']})", "source": r["source"]}
        else:
            r = q("SELECT chunk_id, doc_type, ref_id, title, text FROM chunks WHERE chunk_id=?", eid)
            if r:
                r = r[0]
                return {"id": eid, "kind": r["doc_type"], "title": r["title"], "snippet": _clip(r["text"], 520), "source": r["ref_id"]}
    except (KeyError, ValueError, TypeError):
        pass
    return None


# ---------------------------------------------------------------- dashboards
def overview(area=None):
    a = area or None
    today = as_of()
    now = q("""SELECT count(*) AS n, coalesce(sum(e.producing), 0) AS producing FROM inspection_eff e
               WHERE e.inspected_at = (SELECT max(inspected_at) FROM inspections WHERE asset_id=e.asset_id) AND (? IS NULL OR e.area_id=?)""", a, a)[0]
    sp = tools.spills(area_id=a, last_days=90)
    big = sum(1 for r in sp["rows"] if r["spill_class"] in ("reportable", "major"))
    comp = tools.compliance(area_id=a, last_months=12)["rows"]
    breaches, pending = sum(r["status"] == "breach" for r in comp), sum(r["status"] == "pending" for r in comp)
    repairs = q("""SELECT count(*) AS n FROM maintenance m JOIN wells w USING (asset_id)
                   WHERE date(m.started_at) <= ? AND date(m.completed_at) > ? AND (? IS NULL OR w.area_id=?)""", today, today, a, a)[0]["n"]
    reg = q("""SELECT count(*) AS n FROM regulatory_events r JOIN wells w USING (asset_id) WHERE r.status='open' AND (? IS NULL OR w.area_id=?)""", a, a)[0]["n"]
    return {"as_of": today, "area": a, "cards": [
        {"id": "producing", "label": "Producing now", "value": f"{now['producing']}/{now['n']}", "delta": f"{now['n'] - now['producing']} not producing", "tone": "cyan"},
        {"id": "spills", "label": "Real spills · 90 days", "value": str(sp["count"]), "delta": f"{sp['total_bbl']} bbl · {big} reportable", "tone": "amber"},
        {"id": "breaches", "label": "SOP breaches · 12 months", "value": str(breaches), "delta": f"{pending} pending duties", "tone": "rose"},
        {"id": "repairs", "label": "Open repairs", "value": str(repairs), "delta": f"{reg} open regulator items", "tone": "emerald"}]}


def logs(limit=40, area=None):
    """Audit stream: regulator events, human notes and user corrections, newest first."""
    a = area or None
    out = []
    for r in q("""SELECT r.* FROM regulatory_events r JOIN wells w USING (asset_id) WHERE (? IS NULL OR w.area_id=?) ORDER BY r.date DESC LIMIT ?""", a, a, limit):
        kind = {"notice_of_violation": "Critical", "spill_report_filed": "Warning", "site_inspection": "Info", "nov_response_filed": "Resolved"}.get(r["event_type"], "Info")
        out.append({"time": r["date"], "type": kind, "title": f"{r['event_type'].replace('_', ' ')} · {r['asset_id']}", "detail": r["detail"], "id": r["event_id"]})
    for n in q("""SELECT n.*, u.name AS author FROM notes n JOIN users u ON u.user_id=n.author_user_id JOIN wells w USING (asset_id)
                  WHERE n.note_type != 'correction' AND (? IS NULL OR w.area_id=?) ORDER BY n.created_at DESC LIMIT ?""", a, a, limit):
        out.append({"time": n["created_at"][:16].replace("T", " "), "type": "Warning" if n["status"] in ("unconfirmed", "disputed") else "Info",
                    "title": f"Note by {n['author']} · {n['asset_id']}" + (f" ({n['status']})" if n["status"] != "confirmed" else ""), "detail": n["text"], "id": n["note_id"]})
    for c in q("""SELECT c.*, u.name AS author FROM corrections c JOIN users u ON u.user_id=c.author_user_id WHERE c.source_note_id IS NULL
                  ORDER BY c.correction_id DESC LIMIT ?""", limit):
        out.append({"time": c["created_at"][:16].replace("T", " "), "type": "Warning", "id": c["target_id"],
                    "title": f"Correction by {c['author']} · {c['target_id']}",
                    "detail": f"{c['field']}: {c['original_value']} → {c['corrected_value']} ({c['status']}). {c['reason']}"})
    return sorted(out, key=lambda x: x["time"], reverse=True)[:limit]


def rules_view():
    rows = q("""SELECT scope, scope_value, key, value, unit, source, section, created_by FROM rules ORDER BY key, scope DESC, created_at""")
    for r in rows:
        r["by_user"] = r["created_by"].startswith("user:")
    return rows
