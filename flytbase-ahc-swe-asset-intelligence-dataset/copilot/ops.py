"""Operations-SOP questions on the test dataset. Each function returns {"rows", "evidence", "visual", ...} like tools.py, applies the
wording of the documents literally (Operations SOP rev 2 OPS-1..6, MOC memos, regulator letter) and carries a `summary` and `assumptions`
so the narrator can show the rule it applied. "Now" is the end of the data day (as_of)."""
import json
from datetime import datetime, timedelta, timezone

from .tools import as_of, q


def now():
    return datetime.fromisoformat(as_of()).replace(tzinfo=timezone.utc) + timedelta(days=1)


def dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def stamp(s):
    return dt(s).strftime("%Y-%m-%d %H:%M")


def rule_at(key, day):
    """Global rule value in force on `day`: `key` is the base, `key@YYYY-MM-DD` applies from that date (newest in force wins)."""
    best, best_eff = None, ""
    for r in q("SELECT key, value FROM rules WHERE scope='global' AND (key=? OR key LIKE ?)", key, key + "@%"):
        eff = r["key"].split("@")[1] if "@" in r["key"] else "0000-00-00"
        if eff <= day and eff >= best_eff:
            best, best_eff = r["value"], eff
    return best


def _doc(stem):
    return f"sop:{stem}:0"


# ---------------------------------------------------------------- OPS-1 gas odor response
def gas_reports(since="2026-11-01", until=None, well_id=None):
    """Every operator note reporting gas (smell, rotten egg, H2S monitor alarm) and whether a field response started in time: a
    maintenance job on that well, or a MANUAL inspection (drone does not count), starting after the note within 24 h (12 h for notes
    from 1 Jan 2027)."""
    until = until or as_of()
    end = now()
    notes = q("""SELECT e.note_id, e.asset_id, e.ts, n.text, a.name AS area FROM note_events e JOIN notes n USING (note_id)
                 JOIN wells w ON w.asset_id = e.asset_id JOIN areas a ON a.area_id = w.area_id
                 WHERE e.kind = 'gas_odor' AND date(e.ts) BETWEEN ? AND ? AND (? IS NULL OR e.asset_id = ?) ORDER BY e.ts""",
              since, until, well_id, well_id)
    rows, evidence, tally = [], [], {"Met": 0, "Missed": 0, "Open": 0}
    for n in notes:
        job = q("SELECT maintenance_id AS id, started_at AS ts FROM maintenance WHERE asset_id=? AND started_at > ? ORDER BY started_at LIMIT 1", n["asset_id"], n["ts"])
        ins = q("SELECT inspection_id AS id, inspected_at AS ts FROM inspections WHERE asset_id=? AND method='manual' AND inspected_at > ? ORDER BY inspected_at LIMIT 1",
                n["asset_id"], n["ts"])
        resp = min(job + ins, key=lambda r: r["ts"], default=None)
        limit = rule_at("ops1_hours", n["ts"][:10])
        deadline = dt(n["ts"]) + timedelta(hours=limit)
        if resp:
            hours = round((dt(resp["ts"]) - dt(n["ts"])).total_seconds() / 3600, 1)
            result = "Met" if hours <= limit else "Missed"
        else:
            hours, result = None, ("Open" if deadline > end else "Missed")
        tally[result] += 1
        kind = "manual inspection" if resp and resp["id"].startswith("INS") else "maintenance job"
        rows.append({"well": n["asset_id"], "area": n["area"], "reported_at": stamp(n["ts"]),
                     "response": f"{resp['id']} ({kind}) · {stamp(resp['ts'])}" if resp else "none",
                     "hours_to_response": hours, "deadline": f"{limit:g} h", "result": result})
        evidence += [n["note_id"]] + ([resp["id"]] if resp else [])
    return {"rows": rows, "evidence": evidence + [_doc("operations-sop-rev2")], "visual": "table", "summary": {"reports": len(rows), **tally},
            "assumptions": ["A gas report is an operator note about a gas smell, rotten-egg odor or an H2S monitor alarm (OPS-1).",
                            "The response is the first maintenance job or manual inspection that starts after the note; drone inspections do not count.",
                            f"Deadline: {rule_at('ops1_hours', '2026-12-31'):g} h before 1 Jan 2027, {rule_at('ops1_hours', '2027-01-01'):g} h from 1 Jan 2027.",
                            "A report with no response whose deadline has not yet passed is Open, not Missed."]}


# ---------------------------------------------------------------- OPS-2 temporary bypass
def _moc_expiry():
    """{moc_id: (effective expiry, memo that set it)}: a memo that extends an earlier one replaces its expiry date."""
    memos = q("SELECT DISTINCT moc_id, expires, extends FROM moc")
    own = {m["moc_id"]: m["expires"] for m in memos}
    ext = {}
    for m in memos:
        if m["extends"]:
            ext.setdefault(m["extends"], []).append(m["moc_id"])

    def effective(mid):
        later = max(ext.get(mid, []), default=None)
        return effective(later) if later else (own[mid], mid)
    return {mid: effective(mid) for mid in own}


def bypasses(include_allowed_past=False):
    """Temporary flowline bypasses in place now, plus every past bypass that was never approved or stayed in after its approval expired.
    In place = from the operator note that puts it in until the note that takes it out; allowed only if the well is named in a
    non-expired management-of-change memo (the end of the expiry day counts)."""
    eff = _moc_expiry()
    memos = {}
    for r in q("SELECT moc_id, well_id, extends FROM moc"):
        memos.setdefault(r["well_id"], []).append(r)
    end = now()
    episodes = {}
    for e in q("""SELECT e.note_id, e.asset_id, e.ts, e.kind FROM note_events e WHERE e.kind IN ('bypass_in','bypass_out') ORDER BY e.asset_id, e.ts"""):
        eps = episodes.setdefault(e["asset_id"], [])
        if e["kind"] == "bypass_in" and (not eps or eps[-1]["out"]):
            eps.append({"in": e["ts"], "out": None, "notes": [e["note_id"]]})
        elif e["kind"] == "bypass_out" and eps and not eps[-1]["out"]:
            eps[-1]["out"] = e["ts"]
            eps[-1]["notes"].append(e["note_id"])
    areas = {r["asset_id"]: r["name"] for r in q("SELECT w.asset_id, a.name FROM wells w JOIN areas a USING (area_id)")}
    rows, evidence = [], []
    for well, eps in sorted(episodes.items()):
        covering = memos.get(well, [])
        bases = sorted({m["moc_id"] for m in covering if not m["extends"]}) or sorted({m["moc_id"] for m in covering})
        for ep in eps:
            if bases:
                valid = max(eff[b][0] for b in bases)
                approval = ", ".join(b + (f" (extended by {eff[b][1]})" if eff[b][1] != b else "") for b in bases)
                finish = dt(ep["out"]) if ep["out"] else end
                status = "Expired" if finish >= datetime.fromisoformat(valid).replace(tzinfo=timezone.utc) + timedelta(days=1) else "Allowed"
            else:
                valid, approval, status = None, "none", "Not approved"
            if ep["out"] is None or status != "Allowed" or include_allowed_past:
                rows.append({"well": well, "area": areas.get(well, ""), "bypass_in": ep["in"][:10], "bypass_out": ep["out"][:10] if ep["out"] else "still in",
                             "approval": approval, "valid_until": valid or "—", "status": status})
                evidence += ep["notes"] + [_doc(b.lower()) for b in bases]
    rows.sort(key=lambda r: (r["bypass_out"] != "still in", r["well"]))
    tally = {s: sum(r["status"] == s for r in rows) for s in ("Allowed", "Expired", "Not approved")}
    return {"rows": rows, "evidence": evidence + [_doc("operations-sop-rev2")], "visual": "table",
            "summary": {"listed": len(rows), "in_place_now": sum(r["bypass_out"] == "still in" for r in rows), **tally},
            "assumptions": ["A bypass is in place from the operator note that puts it in until the note that takes it out (OPS-2).",
                            "A memo that extends an earlier memo replaces its expiry date; the expiry date counts until the end of that day.",
                            "Past bypasses are listed only when they were never approved or stayed in after the approval expired."]}


# ---------------------------------------------------------------- regulator's letter
def regulator_letter(ref=None):
    """Spills covered by the regulator's letter (reportable = volume at or above the letter's threshold after corrections, in the letter's
    areas, since its start date, not later confirmed to be something other than crude) and whether each is compliant: the clean-up report
    must contain the sentence the HSE note requires (field soil readings do not count)."""
    letter = q("SELECT * FROM regulator_letters WHERE (? IS NULL OR ref=?) ORDER BY date DESC LIMIT 1", ref, ref)
    if not letter:
        return {"rows": [], "evidence": [], "visual": "table", "error": "no regulator letter in the data"}
    L = letter[0]
    areas = json.loads(L["areas"])
    marks = ",".join("?" * len(areas))
    spills = q(f"""SELECT s.inspection_id, s.asset_id, s.inspected_at, s.spill_bbl, i.spill_est_volume_bbl AS raw_bbl, a.name AS area FROM spills_real s
                   JOIN inspections i USING (inspection_id) JOIN areas a ON a.area_id = s.area_id
                   WHERE s.area_id IN ({marks}) AND date(s.inspected_at) >= ? AND date(s.inspected_at) <= ? AND s.spill_bbl >= ?
                   ORDER BY s.asset_id, s.inspected_at""", *areas, L["since"], as_of(), L["min_bbl"])
    rows, evidence = [], []
    for s in spills:
        job = q("""SELECT m.maintenance_id, m.started_at, f.soil_samples_lab, f.interim FROM maintenance m LEFT JOIN report_facts f USING (maintenance_id)
                   WHERE m.triggered_by_inspection_id = ? ORDER BY m.started_at LIMIT 1""", s["inspection_id"])
        if not job:
            ok, why, jid = "No", "no clean-up job is recorded for this spill", "none"
        else:
            j = job[0]
            jid = j["maintenance_id"]
            if j["soil_samples_lab"]:
                ok, why = "Yes", "clean-up report says \"Soil samples sent to the lab.\""
            elif j["interim"]:
                ok, why = "No", "clean-up is still in progress (interim report) and does not yet record lab samples"
            else:
                ok, why = "No", "clean-up report does not say soil samples were sent to the lab (field readings only)"
        corrected = s["raw_bbl"] is not None and abs(s["raw_bbl"] - s["spill_bbl"]) > 1e-9
        rows.append({"well": s["asset_id"], "area": s["area"], "inspection": f"{s['inspection_id']} · {s['inspected_at'][:10]}",
                     "volume_bbl": round(s["spill_bbl"], 2) if not corrected else f"{round(s['spill_bbl'], 2)} (corrected from {s['raw_bbl']})",
                     "cleanup_job": jid, "compliant": f"{ok} — {why}"})
        evidence += [s["inspection_id"]] + ([jid] if jid != "none" else [])
    return {"rows": rows, "evidence": evidence + ["sop:" + L["source"].removesuffix(".md") + ":0"], "visual": "table",
            "summary": {"letter": L["source"], "covered": len(rows), "compliant": sum(r["compliant"].startswith("Yes") for r in rows),
                        "not_compliant": sum(r["compliant"].startswith("No") for r in rows), "results_due": L["due"]},
            "assumptions": [f"Covered: reportable spills (≥ {L['min_bbl']:g} bbl after corrections) in {', '.join(areas)} since {L['since']}; spills later confirmed not to be crude are excluded.",
                            "Compliant only if the clean-up report contains the required sentence; field soil readings do not count (HSE note on the letter)."]}


# ---------------------------------------------------------------- OPS-3 status evidence precedence
def status_conflicts(include_older=False):
    """Wells where the latest inspection and the latest shut-in/restart operator note disagree about producing. Per OPS-3 the more recent of
    the two decides: a newer shut-in note => not producing (shut in); a newer restart note => producing, unconfirmed. A conflicting note that is
    OLDER than the latest inspection changes nothing (the inspection is newer) and is listed only with include_older=True."""
    rows, evidence, older = [], [], 0
    for s in q("""SELECT s.*, a.name AS area, n.text AS note_text FROM well_status_now s JOIN wells w USING (asset_id) JOIN areas a ON a.area_id = w.area_id
                  LEFT JOIN notes n ON n.note_id = s.note_id WHERE s.note_id IS NOT NULL AND w.status IS NULL ORDER BY s.asset_id"""):
        implied = 0 if s["note_kind"] == "shut_in" else 1
        if implied == s["insp_producing"]:
            continue
        newer = s["note_ts"] > s["inspected_at"]
        if not newer:
            older += 1
            if not include_older:
                continue
        shows = f"{'producing' if s['insp_producing'] else 'not producing'}: {round(s['delta_c'], 1)} °C above air (limit {s['delta_limit_c']:g} °C)"
        status = {"shut_in": "Not producing oil (shut in per the operator note)", "producing_unconfirmed": "Producing oil (unconfirmed: no inspection since the restart)",
                  "producing": "Producing oil (the newer inspection overrides the older shut-in note)", "not_producing": "Not producing oil (the newer inspection overrides the older restart note)"}[s["status"]]
        rows.append({"well": s["asset_id"], "area": s["area"], "latest_inspection": f"{s['inspection_id']} · {s['inspected_at'][:10]} · {shows}",
                     "latest_operator_note": f"{stamp(s['note_ts'])} · {s['note_text']}", "status_now": status})
        evidence += [s["inspection_id"], s["note_id"]]
    return {"rows": rows, "evidence": evidence + [_doc("operations-sop-rev2")], "visual": "table",
            "summary": {"disagree_and_note_is_newer": sum(1 for r in rows if "overrides" not in r["status_now"]), "older_note_conflicts_ignored": older if not include_older else 0},
            "assumptions": ["Only shut-in and restart operator notes change a well's status (OPS-3); gas, bypass and equipment remarks do not.",
                            "A conflicting note older than the latest inspection is not a live disagreement: the more recent evidence wins."]}


# ---------------------------------------------------------------- OPS-5 freeze protection
def freeze_checks(since="2026-12-01", until=None):
    """Inspections from 1 Dec to 28 Feb at or below -5 °C ambient on a well that was producing at that reading need a "Heat trace check"
    maintenance job starting within 7 days after the inspection. Returns the ones that did not get it."""
    until = until or as_of()
    temp, days = rule_at("ops5_temp_c", since), int(rule_at("ops5_days", since))
    rows, ok, evidence = [], 0, []
    for i in q("""SELECT e.inspection_id, e.asset_id, e.inspected_at, e.ambient_temp_c, a.name AS area FROM inspection_eff e JOIN wells w USING (asset_id)
                  JOIN areas a ON a.area_id = w.area_id WHERE date(e.inspected_at) BETWEEN ? AND ? AND e.ambient_temp_c <= ? AND e.producing = 1
                  AND (substr(e.inspected_at, 6, 2) IN ('12', '01', '02')) ORDER BY e.asset_id, e.inspected_at""", since, until, temp):
        job = q("""SELECT maintenance_id, started_at FROM maintenance WHERE asset_id=? AND issue LIKE '%Heat trace check%' AND started_at > ?
                   AND started_at <= ? ORDER BY started_at LIMIT 1""", i["asset_id"], i["inspected_at"], (dt(i["inspected_at"]) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"))
        if job:
            ok += 1
            continue
        due = dt(i["inspected_at"]) + timedelta(days=days)
        rows.append({"well": i["asset_id"], "area": i["area"], "inspection": f"{i['inspection_id']} · {i['inspected_at'][:10]}", "ambient_c": i["ambient_temp_c"],
                     "heat_trace_check": "none within 7 days" if due <= now() else "not yet due", "result": "Missed" if due <= now() else "Open"})
        evidence.append(i["inspection_id"])
    return {"rows": rows, "evidence": evidence + [_doc("operations-sop-rev2")], "visual": "table",
            "summary": {"cold_producing_readings": ok + len(rows), "checked_in_time": ok, "missed": sum(r["result"] == "Missed" for r in rows)},
            "assumptions": [f"Cold = ambient at or below {temp:g} °C on a well producing at that reading; check = a maintenance job with 'Heat trace check' in its issue within {days} days (OPS-5)."]}


# ---------------------------------------------------------------- H2S evidence
def h2s_reading(well_id, date):
    """What H2S measurement exists for a gas report on `date` at a well. H2S readings are only recorded in maintenance reports (WS-03: the
    highest reading of the crew's monitors during the job); an odor note and a manual inspection carry no reading."""
    notes = q("""SELECT e.note_id, e.ts, n.text FROM note_events e JOIN notes n USING (note_id)
                 WHERE e.asset_id=? AND e.kind='gas_odor' AND date(e.ts)=? ORDER BY e.ts""", well_id, date)
    rows, evidence = [], []
    for n in notes:
        end = (dt(n["ts"]) + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        jobs = q("""SELECT m.maintenance_id, m.started_at, f.h2s_ppm FROM maintenance m LEFT JOIN report_facts f USING (maintenance_id)
                    WHERE m.asset_id=? AND m.started_at > ? AND m.started_at <= ? ORDER BY m.started_at""", well_id, n["ts"], end)
        manual = q("SELECT inspection_id, inspected_at FROM inspections WHERE asset_id=? AND method='manual' AND inspected_at > ? AND inspected_at <= ? ORDER BY inspected_at",
                   well_id, n["ts"], end)
        reading = next((j for j in jobs if j["h2s_ppm"] is not None), None)
        rows.append({"well": well_id, "report": f"{stamp(n['ts'])} · {n['text']}",
                     "response_in_7_days": ", ".join([f"{j['maintenance_id']} (job, {stamp(j['started_at'])})" for j in jobs] +
                                                   [f"{m['inspection_id']} (manual inspection, {stamp(m['inspected_at'])})" for m in manual]) or "none",
                     "h2s_ppm": reading["h2s_ppm"] if reading else "not recorded"})
        evidence += [n["note_id"]] + [j["maintenance_id"] for j in jobs] + [m["inspection_id"] for m in manual]
    return {"rows": rows, "evidence": evidence, "visual": "text" if rows and rows[0]["h2s_ppm"] == "not recorded" else "table",
            "summary": {"reports": len(rows), "reading_found": any(r["h2s_ppm"] != "not recorded" for r in rows)},
            "assumptions": ["The only H2S readings in the data are the highest monitor readings in maintenance reports (WS-03); gas odor notes and inspections have none."]}


# ---------------------------------------------------------------- teams
def team_info(team=None, area_id=None):
    """Who leads a production team and how many wells it runs now. A well's own team (and team history) beats its area's team; plugged and
    abandoned wells are not counted as run."""
    t = q("""SELECT t.team_id, t.name, t.lead_user_id, u.name AS leader FROM teams t LEFT JOIN users u ON u.user_id = t.lead_user_id
             WHERE (? IS NULL OR t.team_id = ? OR lower(t.name) LIKE '%' || lower(?) || '%')""", team, team, team)
    if area_id and not team:
        t = q("""SELECT t.team_id, t.name, t.lead_user_id, u.name AS leader FROM teams t LEFT JOIN users u ON u.user_id = t.lead_user_id
                 JOIN areas a ON a.team_id = t.team_id WHERE a.area_id = ?""", area_id)
    rows, evidence = [], []
    for x in t:
        wells = q("SELECT w.asset_id, w.area_id, a.name AS area, a.team_id AS area_team FROM wells w JOIN areas a USING (area_id) WHERE w.team_id=? AND w.status IS NULL", x["team_id"])
        by_area = {}
        for w in wells:
            by_area[w["area"]] = by_area.get(w["area"], 0) + 1
        moved = sum(1 for w in wells if w["area_team"] != x["team_id"])
        rows.append({"team": x["name"], "leader": x["leader"], "wells_run": len(wells),
                     "by_area": ", ".join(f"{k}: {v}" for k, v in sorted(by_area.items())), "wells_from_other_areas": moved})
        evidence += [f"user:{x['lead_user_id']}"]
    return {"rows": rows, "evidence": evidence, "visual": "table" if len(rows) > 1 else "text",
            "assumptions": ["Wells run = wells whose own team_id is this team, excluding plugged and abandoned wells; the area's default team is overridden by the well's own team."]}


# ---------------------------------------------------------------- what the dataset can and cannot tell
CATALOG = {
    "pressure": {"aliases": ["pressure", "psi", "reservoir", "bar", "shut-in pressure"], "measured": False,
                 "why": "no record has a pressure reading (inspections carry wellhead and air temperature, spill area and volume only)",
                 "nearest": "wellhead temperature above air (the producing test), spill volumes, repair costs and downtime; flowline test pressures appear only as text in a few repair reports (a procedure value, not a reservoir measurement)"},
    "production": {"aliases": ["produced", "production", "oil volume", "barrels", "bbl per day", "output", "most oil", "rate", "yield"], "measured": False,
                   "why": "no record has an oil, gas or water production volume (the only barrels in the data are spill volumes)",
                   "nearest": "whether a well was producing at each weekly inspection (wellhead at least the type's limit above air), which gives uptime but not volume"},
}


def data_availability(topic):
    """Whether the dataset measures what a question asks about. Used to answer honestly when it does not."""
    t = (topic or "").lower()
    hit = next((k for k, v in CATALOG.items() if k in t or any(a in t for a in v["aliases"])), None)
    fields = [r["name"] for r in q("SELECT name FROM pragma_table_info('inspections')")]
    rng = q("SELECT min(date(inspected_at)) AS a, max(date(inspected_at)) AS b, count(*) AS n FROM inspections")[0]
    base = {"inspection_fields": fields, "inspections": rng["n"], "from": rng["a"], "to": rng["b"]}
    if not hit:
        return {"rows": [{"topic": topic, "measured": "unknown", "detail": "not in the catalog of known gaps"}], "evidence": [], "visual": "text", "summary": base}
    c = CATALOG[hit]
    mentions = q("SELECT n.note_id, n.asset_id, n.text FROM notes n WHERE n.text LIKE '%pressure%' ORDER BY n.created_at") if hit == "pressure" else []
    extra = {}
    if hit == "pressure":
        psi = q("SELECT count(DISTINCT ref_id) AS reports, count(DISTINCT asset_id) AS wells FROM chunks WHERE doc_type='report' AND text LIKE '%psi%'")[0]
        sample = q("SELECT ref_id, asset_id, substr(text, instr(text, 'pressure'), 160) AS excerpt FROM chunks WHERE doc_type='report' AND text LIKE '%maximum operating pressure%' LIMIT 1")
        extra = {"flowline_psi_in_reports": psi["reports"], "flowline_psi_wells": psi["wells"], "flowline_psi_example": sample[0] if sample else None}
        c = {**c, "nearest": f"{c['nearest'].split(';')[0]}; the only pressure figures are the flowline's maximum operating pressure and the test pressure "
                             f"(1.25 × MOP, WS-05) written in {psi['reports']} repair reports on {psi['wells']} wells: those are engineering limits of a pipe, not reservoir pressure"}
    return {"rows": [{"topic": hit, "measured": "no", "why": c["why"], "nearest_data": c["nearest"]}],
            "evidence": [m["note_id"] for m in mentions] + ([extra["flowline_psi_example"]["ref_id"]] if extra.get("flowline_psi_example") else []),
            "visual": "text", "summary": {**base, **extra, "pressure_mentions": [{"note": m["note_id"], "well": m["asset_id"], "text": m["text"]} for m in mentions]}}
