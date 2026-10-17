"""Feedback and memory. Shared: corrections, well notes, well-type rules (visible to everyone, attributed to their
author, originals kept). Private: conversations and the well sets each tool call returned (always read with a hard
user_id filter; the agent injects user_id, the LLM never supplies it)."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import tools
from .tools import db, q

FIELDS = ("wellhead_temp_c", "spill_est_volume_bbl", "spill_detected")
STOPPED_HINT = re.compile(r"not moving|no stroke|stopped|brake set|cold", re.I)


def _now():
    return tools.as_of() + datetime.now(timezone.utc).strftime("T%H:%M:%SZ")


def _ensure_schema():
    db().executescript((Path(__file__).parent / "schema.sql").read_text(encoding="utf-8"))


def _inspection(well_id, inspection_id=None, date=None):
    if inspection_id:
        r = q("SELECT * FROM inspections WHERE inspection_id=?", inspection_id)
    else:
        r = q("""SELECT * FROM inspections WHERE asset_id=? AND (? IS NULL OR date(inspected_at)=?)
                 ORDER BY inspected_at DESC LIMIT 1""", well_id, date, date)
    return r[0] if r else None


def correct_value(user_id, field, value, reason, well_id=None, inspection_id=None, date=None):
    """Correct raw sensor data (wellhead_temp_c), the AI's spill volume (spill_est_volume_bbl) or the spill detection
    (spill_detected 0/1) for ONE inspection. Keeps the original, records who and why, applies to every later answer."""
    if field not in FIELDS:
        return {"error": f"field must be one of {FIELDS}"}
    ins = _inspection(well_id, inspection_id, date)
    if not ins:
        return {"error": "inspection not found; give inspection_id, or well_id (+ date)"}
    state = "SELECT e.producing, round(e.delta_c,1) AS delta_c, e.delta_limit_c AS limit_c, s.spill_class FROM inspection_eff e LEFT JOIN spills_real s USING (inspection_id) WHERE e.inspection_id=?"
    before = q(state, ins["inspection_id"])[0]
    db().execute("UPDATE corrections SET status='superseded' WHERE target_id=? AND field=? AND status='active'",
                 (ins["inspection_id"], field))
    db().execute("""INSERT INTO corrections (target_type, target_id, field, original_value, corrected_value, author_user_id, reason,
                    created_at) VALUES ('inspection',?,?,?,?,?,?,?)""",
                 (ins["inspection_id"], field, ins[field], value, user_id, reason, _now()))
    db().commit()
    after = q(state, ins["inspection_id"])[0]
    out = {"recorded": {"inspection_id": ins["inspection_id"], "field": field, "original": ins[field], "corrected": value,
                        "by": user_id, "reason": reason},
           "before": before, "after": after, "inspector_note": ins["notes"], "conflicts": [],
           "linked_repairs": [r["maintenance_id"] for r in q(
               "SELECT maintenance_id FROM maintenance WHERE triggered_by_inspection_id=?", ins["inspection_id"])]}
    if field != "wellhead_temp_c":  # a changed spill changes class, deadlines and what earlier reports claimed
        out["compliance_now"] = [c for c in tools.compliance(well_id=ins["asset_id"], since=ins["inspected_at"][:10],
                                                             until=tools.as_of())["rows"] if c["inspection_id"] == ins["inspection_id"]]
        out["repair_report_said"] = q(f"""SELECT maintenance_id, protocol_id, result, detail FROM report_compliance
            WHERE protocol_id IN ('SR-01','SR-02','SR-03','SR-04') AND maintenance_id IN
            ({','.join('?' * len(out['linked_repairs'])) or 'NULL'})""", *out["linked_repairs"])
    if field == "wellhead_temp_c" and after["producing"] and STOPPED_HINT.search(ins["notes"] or ""):
        out["conflicts"].append({"with": "inspector_note", "detail": f"Inspection note says \"{ins['notes']}\", which disagrees "
                                 "with the corrected reading; ask the user to confirm."})
    return {"rows": [out], "evidence": [ins["inspection_id"]] + out["linked_repairs"], "visual": "card"}


def add_well_note(user_id, well_id, text, claims_producing=None, valid_from=None, valid_to=None):
    """Record shared knowledge about one well. claims_producing: 1 if the note says the well is running, 0 if stopped /
    shut in, omit if neither. A claim that contradicts the latest inspection or another user's note is saved as
    'unconfirmed' and the conflict is returned; otherwise 'reported'."""
    status = tools.well_status(well_id)
    if status.get("error"):
        return status
    card = status["rows"][0]
    conflicts = []
    starts_later = (valid_from or "") > tools.as_of()  # a future plan can't be checked against today's reading
    if claims_producing is not None and not starts_later and bool(claims_producing) != card["producing"]:
        conflicts.append({"with": "data", "detail": f"inspection {card['last_inspection']} ({card['last_inspected_at'][:10]}) shows the "
                          f"wellhead {card['delta_c']} C above air, limit {card['limit_c']:g} C: well is "
                          f"{'producing' if card['producing'] else 'not producing'}"})
    if claims_producing is not None:
        for n in q("""SELECT n.note_id, n.text, n.author_user_id, c.claims_producing FROM notes n JOIN note_claims c USING (note_id)
                      WHERE n.asset_id=? AND n.author_user_id != ? AND n.status != 'disputed' AND c.claims_producing != ?
                      AND n.valid_from <= ? AND (n.valid_to IS NULL OR n.valid_to >= ?)""",
                   well_id, user_id, int(claims_producing), tools.as_of(), tools.as_of()):
            conflicts.append({"with": "note", "detail": f"{n['note_id']} by {n['author_user_id']}: {n['text']}"})
    today = tools.as_of()
    n = db().execute("SELECT count(*) FROM notes WHERE note_id LIKE 'USR-%'").fetchone()[0] + 1
    note_id = f"USR-{well_id[-4:]}-{n:03d}"
    db().execute("INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (note_id, well_id, _now(), user_id, "operator_feedback", None, text, valid_from or today, valid_to,
                  "unconfirmed" if conflicts else "reported"))
    if claims_producing is not None:
        db().execute("INSERT INTO note_claims VALUES (?,?)", (note_id, int(claims_producing)))
    db().commit()
    out = {"recorded": {"note_id": note_id, "well_id": well_id, "by": user_id, "status": "unconfirmed" if conflicts else "reported"},
           "conflicts": conflicts, "latest_inspection": card["last_inspection"], "active_notes": card["active_notes"]}
    return {"rows": [out], "evidence": [note_id, card["last_inspection"]] + [n["note_id"] for n in card["active_notes"]], "visual": "text"}


def add_type_rule(user_id, well_type, key, value, text):
    """A rule for every well of one type (not other types), e.g. key='rca_corrective_count' value=2. It overrides the
    manual for that well type only and is cited as the user's rule."""
    known = q("SELECT unit, source FROM rules WHERE key=? LIMIT 1", key)
    if not known:
        return {"error": f"unknown rule key {key}; known: {[r['key'] for r in q('SELECT DISTINCT key FROM rules')]}"}
    old = tools.rule(key, well_type)
    db().execute("INSERT OR REPLACE INTO rules VALUES ('well_type',?,?,?,?,?,?,?,?)",
                 (well_type, key, value, known[0]["unit"], f"user:{user_id}", text[:200], f"user:{user_id}", _now()))
    db().commit()
    return {"rows": [{"well_type": well_type, "key": key, "old": old["value"], "old_source": old["label"], "new": value, "by": user_id}],
            "evidence": [f"rule:{well_type}:{key}"], "visual": "text"}


def log_turn(user_id, chat_id, role, text, ts=None):
    db().execute("INSERT INTO conversations (user_id, chat_id, ts, role, text) VALUES (?,?,?,?,?)", (user_id, chat_id, ts or _now(), role, text))
    db().commit()


def remember(user_id, chat_id, label, well_ids, ts=None):
    """Persist the well set a tool call returned, so 'the wells we discussed yesterday' resolves to concrete IDs."""
    if well_ids:
        db().execute("INSERT INTO conversation_entities (user_id, chat_id, ts, label, well_ids) VALUES (?,?,?,?,?)",
                     (user_id, chat_id, ts or _now(), label, json.dumps(list(dict.fromkeys(well_ids)))))
        db().commit()


def recall(user_id, days_ago=None, contains=None, limit=10):
    """This user's own earlier questions and the well sets they produced. days_ago=1 -> yesterday."""
    cond, args = ["user_id=?"], [user_id]
    if days_ago is not None:
        cond.append("date(ts)=date(?, ?)")
        args += [tools.as_of(), f"-{int(days_ago)} days"]
    where = " AND ".join(cond)
    ents = q(f"SELECT chat_id, date(ts) AS day, label, well_ids FROM conversation_entities WHERE {where} ORDER BY ts DESC LIMIT ?", *args, limit)
    for e in ents:
        e["well_ids"] = json.loads(e["well_ids"])
    qs = q(f"SELECT chat_id, date(ts) AS day, text FROM conversations WHERE {where} AND role='user' "
           f"AND (? IS NULL OR text LIKE '%'||?||'%') ORDER BY ts DESC LIMIT ?", *args, contains, contains, limit)
    return {"rows": ents, "questions": qs, "evidence": [f"chat:{e['chat_id']}" for e in ents], "visual": "text",
            "empty": not ents and not qs}


_ensure_schema()
