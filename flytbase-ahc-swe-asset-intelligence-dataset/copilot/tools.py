"""Deterministic query tools. Each returns {"rows": [...], "evidence": [ids], "visual": str, ...}; the LLM only picks a
tool and phrases the result. All numbers come from the SQL views (corrections and rule overrides already applied)."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "copilot.db"
_db = None


def db():
    global _db
    if _db is None:
        _db = sqlite3.connect(DB_PATH)
        _db.row_factory = sqlite3.Row
    return _db


def q(sql, *args):
    return [dict(r) for r in db().execute(sql, args)]


def as_of():
    return db().execute("SELECT value FROM meta WHERE key='as_of'").fetchone()[0]


def window(since=None, until=None, last_days=None, last_weeks=None, last_months=None):
    """Inclusive date window ending today (as_of) unless `until` is given; periods compare by date."""
    end = until or as_of()
    if last_days:
        since = db().execute("SELECT date(?, ?)", (end, f"-{int(last_days)} days")).fetchone()[0]
    elif last_weeks:
        since = db().execute("SELECT date(?, ?)", (end, f"-{int(last_weeks) * 7} days")).fetchone()[0]
    elif last_months:
        since = db().execute("SELECT date(?, ?)", (end, f"-{int(last_months)} months")).fetchone()[0]
    return since or "0000-01-01", end


def _where(col_date, win, area_id=None, well_id=None, well_type=None, alias=""):
    p = f"{alias}." if alias else ""
    sql, args = [f"date({p}{col_date}) BETWEEN ? AND ?"], list(win)
    for col, val in (("area_id", area_id), ("asset_id", well_id), ("well_type", well_type)):
        if val:
            sql.append(f"{p}{col} = ?")
            args.append(val)
    return " AND ".join(sql), args


def well_status(well_id):
    """Status card: producing now (latest inspection, corrections applied), why not, and what the systems of record say."""
    today = as_of()
    w = q("SELECT w.*, a.name AS area_name FROM wells w JOIN areas a USING (area_id) WHERE asset_id=?", well_id)
    if not w:
        return {"rows": [], "evidence": [], "visual": "card", "error": f"unknown well {well_id}"}
    last = q("""SELECT e.*, u.name AS inspector FROM inspection_eff e JOIN users u ON u.user_id=e.inspector_user_id
                WHERE e.asset_id=? ORDER BY e.inspected_at DESC LIMIT 1""", well_id)[0]
    wh_raw = q("SELECT wellhead_temp_c FROM inspections WHERE inspection_id=?", last["inspection_id"])[0]["wellhead_temp_c"]
    fixes = q("""SELECT c.*, u.name AS author FROM corrections c LEFT JOIN users u ON u.user_id=c.author_user_id
                 WHERE c.status='active' AND c.target_id=?""", last["inspection_id"])
    notes = q("""SELECT n.note_id, n.note_type, n.text, n.status, n.valid_from, n.valid_to, u.name AS author FROM notes n
                 JOIN users u ON u.user_id=n.author_user_id WHERE n.asset_id=? AND n.note_type != 'correction'
                 AND n.valid_from <= ? AND (n.valid_to IS NULL OR n.valid_to >= ?) ORDER BY n.created_at""", well_id, today, today)
    upcoming = q("""SELECT n.note_id, n.text, n.status, n.valid_from, n.valid_to, u.name AS author FROM notes n
                    JOIN users u ON u.user_id=n.author_user_id WHERE n.asset_id=? AND n.valid_from > ? ORDER BY n.valid_from""",
                 well_id, today)
    repairs = q("""SELECT maintenance_id, started_at, completed_at, equipment_kind, issue FROM maintenance
                   WHERE asset_id=? AND date(started_at) <= ? AND date(completed_at) > ?""", well_id, today, today)
    card = {**w[0], "as_of": today, "producing": bool(last["producing"]), "delta_c": round(last["delta_c"], 1),
            "limit_c": last["delta_limit_c"], "wellhead_temp_c": last["wh_temp_c"], "wellhead_temp_raw_c": wh_raw,
            "ambient_temp_c": last["ambient_temp_c"], "last_inspection": last["inspection_id"],
            "last_inspected_at": last["inspected_at"], "method": last["method"], "inspector": last["inspector"],
            "inspector_note": last["notes"], "active_notes": notes, "upcoming_notes": upcoming, "open_repairs": repairs,
            "corrections": fixes}
    evidence = [last["inspection_id"]] + [n["note_id"] for n in notes + upcoming] + [r["maintenance_id"] for r in repairs]
    return {"rows": [card], "evidence": evidence, "visual": "card"}


def well_notes(well_id, since=None, until=None, last_days=None, last_weeks=None, last_months=None):
    """Every human note on a well in the window (any validity), with author, type, status and the inspection it corrects."""
    win = window(since, until, last_days, last_weeks, last_months)
    rows = q("""SELECT n.note_id, date(n.created_at) AS date, u.name AS author, u.role, n.note_type, n.status, n.inspection_id, n.text,
                       n.valid_from, n.valid_to FROM notes n JOIN users u ON u.user_id=n.author_user_id
                WHERE n.asset_id=? AND date(n.created_at) BETWEEN ? AND ? ORDER BY n.created_at""", well_id, *win)
    return {"rows": rows, "evidence": [r["note_id"] for r in rows], "visual": "table", "window": win}


def find_wells(producing=None, area_id=None, well_type=None):
    """Wells (by latest inspection) filtered on producing or not, with every recorded reason for a stop."""
    today = as_of()
    cond, args = ["e.inspected_at = (SELECT max(inspected_at) FROM inspections WHERE asset_id=e.asset_id)"], []
    for col, val in (("area_id", area_id), ("well_type", well_type)):
        if val:
            cond.append(f"e.{col}=?")
            args.append(val)
    if producing is not None:
        cond.append("e.producing=?")
        args.append(int(producing))
    rows = q(f"""SELECT e.asset_id, e.well_type, e.area_id, e.inspection_id, e.inspected_at, e.producing,
                        round(e.delta_c,1) AS delta_c, e.delta_limit_c AS limit_c, e.notes AS inspector_note,
                        w.recorded_status FROM inspection_eff e JOIN wells w USING (asset_id)
                 WHERE {' AND '.join(cond)} ORDER BY e.asset_id""", *args)
    evidence = []
    for r in rows:
        r["open_repairs"] = q("""SELECT maintenance_id, started_at, equipment_kind, issue FROM maintenance WHERE asset_id=?
                                 AND date(started_at) <= ? AND date(completed_at) > ?""", r["asset_id"], today, today)
        r["active_notes"] = q("""SELECT note_id, text, status FROM notes WHERE asset_id=? AND note_type != 'correction'
                                 AND valid_from <= ? AND (valid_to IS NULL OR valid_to >= ?)""", r["asset_id"], today, today)
        r["has_recorded_reason"] = bool(r["open_repairs"] or r["active_notes"])
        evidence += [r["inspection_id"]] + [m["maintenance_id"] for m in r["open_repairs"]] + [n["note_id"] for n in r["active_notes"]]
    out = {"rows": rows, "evidence": evidence, "visual": "table"}
    if producing is False or producing == 0:  # corrected_out is filled below, then summarised in `note`
        # wells a correction moved out of this list: latest reading corrected so the well now produces
        out["corrected_out"] = q(f"""SELECT e.asset_id, e.inspection_id, c.corrected_value AS corrected_wellhead_c, c.original_value AS original_wellhead_c,
                                            c.author_user_id, c.reason, round(e.delta_c,1) AS delta_c FROM inspection_eff e
                                     JOIN corrections c ON c.target_id=e.inspection_id AND c.field='wellhead_temp_c' AND c.status='active'
                                     WHERE e.producing=1 AND e.ambient_temp_c IS NOT NULL AND c.original_value - e.ambient_temp_c < e.delta_limit_c
                                     AND {' AND '.join(cond[:-1])}""", *args[:-1])  # cond[-1] is the producing filter
        if out["corrected_out"]:
            names = {u["user_id"]: u["name"] for u in q("SELECT user_id, name FROM users")}
            out["note"] = "NOT LISTED because a user correction made them producing: " + "; ".join(
                f"{c['asset_id']} ({c['inspection_id']}) corrected {c['original_wellhead_c']:g} to {c['corrected_wellhead_c']:g} C by "
                f"{names.get(c['author_user_id'], c['author_user_id'])}" for c in out["corrected_out"])
            out["evidence"] += [c["inspection_id"] for c in out["corrected_out"]]
    return out


def series(well_id, since=None, until=None, last_days=None, last_weeks=None, last_months=None):
    """Wellhead vs ambient temperature per inspection, flagged when not producing."""
    win = window(since, until, last_days, last_weeks, last_months)
    rows = q("""SELECT inspection_id, date(inspected_at) AS date, ambient_temp_c, wh_temp_c AS wellhead_temp_c,
                       round(delta_c,1) AS delta_c, delta_limit_c AS limit_c, producing
                FROM inspection_eff WHERE asset_id=? AND date(inspected_at) BETWEEN ? AND ? ORDER BY inspected_at""", well_id, *win)
    return {"rows": rows, "evidence": [r["inspection_id"] for r in rows], "visual": "line", "window": win}


def downtime(group_by="well", area_id=None, well_id=None, well_type=None, top_n=None,
             since=None, until=None, last_days=None, last_weeks=None, last_months=None):
    """Days not producing = 7 x inspections that found the well not producing (never maintenance.downtime_hours)."""
    win = window(since, until, last_days, last_weeks, last_months)
    cond, args = _where("inspected_at", win, area_id, well_id, well_type)
    key = {"well": "asset_id", "area": "area_id", "well_type": "well_type", "month": "substr(inspected_at,1,7)"}[group_by]
    rows = q(f"SELECT {key} AS key, sum(days) AS days, count(*) AS weeks FROM downtime_weeks WHERE {cond} "
             f"GROUP BY 1 ORDER BY days DESC, key" + (f" LIMIT {int(top_n)}" if top_n else ""), *args)
    ev = q(f"SELECT inspection_id FROM downtime_weeks WHERE {cond} AND {key} IN ({','.join('?' * len(rows))})",
           *args, *[r["key"] for r in rows])  # evidence only for the groups returned
    return {"rows": rows, "evidence": [e["inspection_id"] for e in ev], "visual": "bar", "window": win}


def spills(group_by=None, area_id=None, well_id=None, well_type=None,
           since=None, until=None, last_days=None, last_weeks=None, last_months=None):
    """Real spills only: detections voided by a correction are excluded, volumes use corrected values.
    group_by='area_month' returns the area x month count matrix for a heatmap."""
    win = window(since, until, last_days, last_weeks, last_months)
    cond, args = _where("inspected_at", win, area_id, well_id, well_type)
    if group_by == "area_month":
        rows = q(f"""SELECT a.name AS area, substr(s.inspected_at,1,7) AS month, count(*) AS spills FROM spills_real s
                     JOIN areas a USING (area_id) WHERE {cond} GROUP BY 1,2 ORDER BY 1,2""", *args)
        totals = {}
        for r in rows:
            totals[r["area"]] = totals.get(r["area"], 0) + r["spills"]
        return {"rows": rows, "evidence": [], "visual": "heatmap", "window": win, "totals": totals}
    rows = q(f"""SELECT inspection_id, asset_id, area_id, well_type, date(inspected_at) AS date, round(spill_bbl,2) AS bbl,
                        spill_area_pct, spill_class, lat, lon FROM spills_real WHERE {cond} ORDER BY inspected_at""", *args)
    return {"rows": rows, "evidence": [r["inspection_id"] for r in rows], "visual": "table",
            "total_bbl": round(sum(r["bbl"] for r in rows), 2), "count": len(rows), "window": win}


def rule(key, well_type=None):
    """Effective value + source: a well-type rule (manual or user-defined, newest wins) beats the global one."""
    r = q("""SELECT value, source, created_by FROM rules WHERE key=? AND (scope='global' OR (scope='well_type' AND scope_value=?))
             ORDER BY scope='well_type' DESC, created_at DESC LIMIT 1""", key, well_type)[0]
    who = q("SELECT name FROM users WHERE user_id=?", r["created_by"].removeprefix("user:")) if r["created_by"].startswith("user:") else []
    r["label"] = f"{who[0]['name']}'s rule" if who else f"manual/SOP {r['source']}"
    return r


def _dt(s):
    from datetime import datetime
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def compliance(well_id=None, area_id=None, well_type=None,
               since=None, until=None, last_days=None, last_weeks=None, last_months=None):
    """Breaches (status 'breach') and open duties not yet due (status 'pending') against SR-01/02/03 and RC-04,
    judged from corrected spills, regulator events and the compliance table of each repair report."""
    from datetime import datetime, timedelta, timezone
    win = window(since, until, last_days, last_weeks, last_months)
    now = datetime.fromisoformat(as_of()).replace(tzinfo=timezone.utc) + timedelta(days=1)
    cond, args = _where("inspected_at", win, area_id, well_id, well_type)
    out = []

    def add(protocol, status, s, detail, evidence, due=None):
        out.append({"protocol_id": protocol, "status": status, "asset_id": s["asset_id"], "inspection_id": s["inspection_id"],
                    "detail": detail, "due": due, "evidence": evidence})

    for s in q(f"SELECT * FROM spills_real WHERE {cond} ORDER BY inspected_at", *args):
        found = _dt(s["inspected_at"])
        if s["spill_class"] in ("reportable", "major"):
            lim_h = rule("sr01_major_report_hours" if s["spill_class"] == "major" else "sr01_report_hours", s["well_type"])["value"]
            filed = q("SELECT * FROM regulatory_events WHERE related_inspection_id=? AND event_type='spill_report_filed'",
                      s["inspection_id"])
            due = found + timedelta(hours=lim_h)
            if filed and filed[0]["hours_to_report"] > lim_h:
                add("SR-01", "breach", s, f"{s['spill_class']} spill {s['spill_bbl']} bbl reported after "
                    f"{filed[0]['hours_to_report']:g} h (limit {lim_h:g} h)", [filed[0]["event_id"], s["inspection_id"]], due.isoformat())
            elif not filed:
                add("SR-01", "breach" if due < now else "pending", s, f"{s['spill_class']} spill {s['spill_bbl']} bbl: "
                    f"no written notice on record, due within {lim_h:g} h of discovery", [s["inspection_id"]], due.isoformat())
            verify_days = rule("sr03_verify_days", s["well_type"])["value"]
            if not q("SELECT 1 FROM regulatory_events WHERE related_inspection_id=? AND protocol_id='SR-03' AND status='closed'",
                     s["inspection_id"]):
                due = found + timedelta(days=verify_days)
                ev = [e["event_id"] for e in q("SELECT event_id FROM regulatory_events WHERE related_inspection_id=? AND protocol_id='SR-03'",
                                               s["inspection_id"])]
                add("SR-03", "breach" if due < now else "pending", s, f"agency verification of clean-up not closed, due "
                    f"within {verify_days:g} days of discovery", ev + [s["inspection_id"]], due.date().isoformat())
        lim_h = rule("sr02_contain_hours", s["well_type"])["value"]
        for c in q("""SELECT rc.maintenance_id, rc.containment_hours FROM report_compliance rc JOIN maintenance m USING (maintenance_id)
                      WHERE m.triggered_by_inspection_id=? AND rc.protocol_id='SR-02' AND rc.containment_hours > ?""",
                   s["inspection_id"], lim_h):
            add("SR-02", "breach", s, f"contained after about {c['containment_hours']:g} h (limit {lim_h:g} h)",
                [c["maintenance_id"], s["inspection_id"]])
    cond_e, args_e = _where("date", win, area_id, well_id, well_type, alias="e")
    cond_e = cond_e.replace("e.area_id", "w.area_id").replace("e.well_type", "w.well_type")
    for n in q(f"""SELECT e.* FROM regulatory_events e JOIN wells w USING (asset_id)
                   WHERE e.event_type='notice_of_violation' AND {cond_e} ORDER BY e.date""", *args_e):
        resp = q("""SELECT * FROM regulatory_events WHERE asset_id=? AND event_type='nov_response_filed' AND related_inspection_id IS ?
                    ORDER BY date LIMIT 1""", n["asset_id"], n["related_inspection_id"])
        days = rule("rc04_response_days")["value"]
        due = _dt(n["date"] + "T00:00:00Z") + timedelta(days=days)
        s = {"asset_id": n["asset_id"], "inspection_id": n["related_inspection_id"]}
        if resp and _dt(resp[0]["date"] + "T00:00:00Z") > due:
            add("RC-04", "breach", s, f"notice {n['event_id']} answered late on {resp[0]['date']}",
                [n["event_id"], resp[0]["event_id"]], due.date().isoformat())
        elif not resp:
            add("RC-04", "breach" if due < now else "pending", s, f"notice of violation {n['event_id']} (fine USD {n['fine_usd']:g}, "
                f"{n['status']}) has no response on record, due within {days:g} days", [n["event_id"]], due.date().isoformat())
    actions = []  # duties that are open but are not breaches (kept out of `rows`)
    if well_id:
        for k in q("SELECT DISTINCT kind FROM equipment WHERE asset_id=?", well_id):
            for r in rca_candidates(k["kind"], well_id=well_id)["rows"]:
                actions.append({"protocol_id": "RCA", "status": "pending", "asset_id": well_id, "evidence": r["repairs"],
                                "detail": f"{r['corrective_repairs']} corrective {k['kind']} repairs in the last 12 months (threshold "
                                          f"{r['threshold']:g}, {r['threshold_source']}): root-cause analysis required"})
    return {"rows": out, "open_actions": actions, "evidence": sorted({e for r in out + actions for e in r["evidence"]}),
            "visual": "table", "window": win}


def repairs(well_id=None, well_ids=None, area_id=None, well_type=None, equipment_kind=None, maintenance_type=None,
            group_by=None, since=None, until=None, last_days=None, last_weeks=None, last_months=None, this_year=False):
    """Repairs by start date in the window; group_by='well' sums cost_total per well. this_year=True -> 1 Jan..today."""
    if this_year:
        since = as_of()[:4] + "-01-01"
    win = window(since, until, last_days, last_weeks, last_months)
    cond, args = _where("started_at", win, area_id, well_id, well_type, alias="m")
    cond = cond.replace("m.area_id", "w.area_id").replace("m.well_type", "w.well_type")
    for col, val in (("equipment_kind", equipment_kind), ("maintenance_type", maintenance_type)):
        if val:
            cond += f" AND m.{col}=?"
            args.append(val)
    if well_ids:
        cond += f" AND m.asset_id IN ({','.join('?' * len(well_ids))})"
        args += list(well_ids)
    base = f"FROM maintenance m JOIN wells w USING (asset_id) WHERE {cond}"
    if group_by == "well":
        rows = q(f"SELECT m.asset_id, count(*) AS jobs, sum(m.cost_total) AS cost_usd {base} GROUP BY 1 ORDER BY cost_usd DESC", *args)
        ev = q(f"SELECT m.maintenance_id {base}", *args)
        return {"rows": rows, "evidence": [e["maintenance_id"] for e in ev], "visual": "bar", "window": win}
    rows = q(f"""SELECT m.maintenance_id, m.asset_id, date(m.started_at) AS started, date(m.completed_at) AS completed,
                        m.maintenance_type, m.equipment_kind, m.issue, m.cost_total AS cost_usd, m.root_cause {base} ORDER BY m.started_at""", *args)
    return {"rows": rows, "evidence": [r["maintenance_id"] for r in rows], "visual": "table", "window": win,
            "total_cost_usd": sum(r["cost_usd"] for r in rows)}


def rca_candidates(equipment_kind, area_id=None, well_id=None):
    """Wells with at least N corrective repairs on one equipment kind in the rule window (N from the manual, or a
    user-defined rule for that well type); each row cites which rule set the threshold."""
    today = as_of()
    out, evidence = [], []
    for w in q("SELECT asset_id, well_type FROM wells WHERE (? IS NULL OR area_id=?) AND (? IS NULL OR asset_id=?) ORDER BY asset_id",
               area_id, area_id, well_id, well_id):
        n = rule("rca_corrective_count", w["well_type"])
        months = rule("rca_window_months", w["well_type"])["value"]
        jobs = q("""SELECT maintenance_id FROM maintenance WHERE asset_id=? AND maintenance_type='corrective' AND equipment_kind=?
                    AND date(started_at) BETWEEN date(?, ?) AND ? ORDER BY started_at""",
                 w["asset_id"], equipment_kind, today, f"-{int(months)} months", today)
        if len(jobs) >= n["value"]:
            ids = [j["maintenance_id"] for j in jobs]
            out.append({"asset_id": w["asset_id"], "well_type": w["well_type"], "corrective_repairs": len(ids), "threshold": n["value"],
                        "threshold_source": n["label"], "repairs": ids})
            evidence += ids
    return {"rows": out, "evidence": evidence, "visual": "table"}
