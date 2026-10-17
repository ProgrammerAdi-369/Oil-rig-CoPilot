"""Load a dataset directory (sample or test) into one SQLite file. Idempotent: upserts by primary key, so a
second dataset loads alongside the first.
   py -m copilot.ingest [dataset_dir] [db_path]
   py -m copilot.ingest test-data/dataset copilot.test.db     (the test dataset; a fresh file avoids mixing with the sample)"""
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

from . import extract, rules

HERE = Path(__file__).parent
COMPLIANCE_ROW = re.compile(r"^\|\s*((?:SR|RC|WS)-\d+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$")
CONTAINED = re.compile(r"Contained about (\d+(?:\.\d+)?) hours")
NOT_A_SPILL = re.compile(r"not (?:a )?(?:crude )?spill", re.I)
CORRECTABLE = {"wellhead_temp_c", "spill_est_volume_bbl", "spill_detected"}  # fields inspection_eff knows how to override
# columns added after the first schema; ALTER TABLE brings an older database up to date
NEW_COLUMNS = [("wells", "status", "TEXT"), ("wells", "decommissioned_on", "TEXT"), ("inspections", "recorded_at", "TEXT"),
               ("maintenance", "recorded_at", "TEXT"), ("maintenance", "cost_original", "REAL"), ("maintenance", "cost_revised_on", "TEXT"),
               ("maintenance", "cost_revision_reason", "TEXT")]


def jl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def sections(text):
    """Split markdown on '## ' headings -> [(title, body)]; text before the first heading is titled 'Header'."""
    parts = re.split(r"^## ", text, flags=re.M)
    out = [("Header", parts[0].strip())] if parts[0].strip() else []
    for p in parts[1:]:
        title, _, body = p.partition("\n")
        out.append((title.strip(), body.strip()))
    return out


def put_chunk(db, chunk_id, doc_type, ref_id, asset_id, well_type, title, text):
    # keep a stored embedding only if the text is unchanged
    db.execute("""INSERT INTO chunks (chunk_id, doc_type, ref_id, asset_id, well_type, title, text) VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(chunk_id) DO UPDATE SET doc_type=excluded.doc_type, ref_id=excluded.ref_id, asset_id=excluded.asset_id,
        well_type=excluded.well_type, title=excluded.title,
        embedding=CASE WHEN chunks.text=excluded.text THEN chunks.embedding END, text=excluded.text""",
               (chunk_id, doc_type, ref_id, asset_id, well_type, title, text))


def ensure_columns(db):
    for table, col, typ in NEW_COLUMNS:
        if col not in {r[1] for r in db.execute(f"PRAGMA table_info({table})")}:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")


def load_fleet(db, fleet):
    areas = json.loads((fleet / "areas.json").read_text(encoding="utf-8"))
    for t in areas["teams"]:
        db.execute("INSERT OR REPLACE INTO teams VALUES (?,?,?)", (t["team_id"], t["name"], t["lead_user_id"]))
    for a in areas["areas"]:
        db.execute("INSERT OR REPLACE INTO areas VALUES (?,?,?,?,?)",
                   (a["area_id"], a["name"], a["team_id"], a["center"]["lat"], a["center"]["lon"]))
    for u in json.loads((fleet / "users.json").read_text(encoding="utf-8"))["users"]:
        db.execute("INSERT OR REPLACE INTO users VALUES (?,?,?,?)", (u["user_id"], u["name"], u["role"], u["team_id"]))
    for sub, doc_type in (("well-types", "manual"), ("sops", "sop")):
        for md in sorted((fleet / sub).glob("*.md")):
            wtype = md.stem if doc_type == "manual" else None
            for n, (title, body) in enumerate(sections(md.read_text(encoding="utf-8"))):
                put_chunk(db, f"{doc_type}:{md.stem}:{n}", doc_type, md.stem, None, wtype, f"{md.stem} — {title}", body)
    return {a["area_id"]: a["name"] for a in areas["areas"]}


def load_documents(db, fleet, area_names):
    """Management-of-change memos, supplier recall notices and regulator letters found in fleet/sops."""
    sops = fleet / "sops"
    for f in sorted(sops.glob("moc-*.md")):
        m = extract.parse_moc(f.read_text(encoding="utf-8"))
        base = {x["moc_id"]: x for x in (extract.parse_moc(g.read_text(encoding="utf-8")) for g in sops.glob("moc-*.md"))}.get(m["extends"])
        wells = m["wells"] or (base["wells"] if base else [])  # an extension memo may name no wells of its own
        eff = m["effective_from"] or (base["effective_from"] if base else None)
        for w in wells:
            db.execute("INSERT OR REPLACE INTO moc VALUES (?,?,?,?,?,?)", (m["moc_id"], w, eff, m["expires"], m["extends"], m["title"]))
    for f in sorted(sops.glob("*recall*.md")):
        r = extract.parse_recall(f.read_text(encoding="utf-8"))
        for lot in r["lots"]:
            db.execute("INSERT OR REPLACE INTO recalls VALUES (?,?,?,?,?)", (r["ref"], r["model"], lot, r["notice_date"], r["deadline"]))
    for f in sorted(sops.glob("*letter*.md")):
        r = extract.parse_letter(f.read_text(encoding="utf-8"), area_names)
        db.execute("INSERT OR REPLACE INTO regulator_letters VALUES (?,?,?,?,?,?,?,?)",
                   (f.stem, r["date"], json.dumps(r["areas"]), r["since"], r["due"], r["min_bbl"], r["required_sentence"], f.name))


def load_report(db, m, path):
    text = path.read_text(encoding="utf-8")
    facts = extract.parse_report(text)
    for n, (title, body) in enumerate(sections(text)):
        head = f"{m['maintenance_id']} {m['asset_id']} {m['equipment_kind']} — {m['issue']}\n"
        put_chunk(db, f"report:{m['maintenance_id']}:{n}", "report", m["maintenance_id"], m["asset_id"], None, title, head + body)
    for line in text.splitlines():
        r = COMPLIANCE_ROW.match(line)
        if r:
            proto, result, detail = r.group(1), r.group(2).replace("**", ""), r.group(3)
            c = CONTAINED.search(detail) if proto == "SR-02" else None
            db.execute("INSERT OR REPLACE INTO report_compliance VALUES (?,?,?,?,?)",
                       (m["maintenance_id"], proto, result, detail, float(c.group(1)) if c else None))
    db.execute("INSERT OR REPLACE INTO report_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (m["maintenance_id"], int(facts["interim"]), facts["pump_model"], facts["pump_serial"], facts["pump_lot"], facts["followup_days"],
                facts["followup_text"], int(facts["soil_samples_lab"]), facts["h2s_ppm"], facts["extra_days"], int(facts["extra_days_expected"]),
                facts["delay_reason"], facts["delay_text"], facts["root_cause_category"]))
    return facts["root_cause"]


def load_well(db, wdir):
    meta = json.loads((wdir / "metadata.json").read_text(encoding="utf-8"))
    a = meta["asset_id"]
    db.execute("""INSERT OR REPLACE INTO wells (asset_id, name, well_type, area_id, team_id, in_charge_user_id, lat, lon, installed_on,
                  recorded_status, last_inspection_id, status, decommissioned_on) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
               (a, meta["name"], meta["well_type"], meta["area_id"], meta["team_id"], meta["in_charge_user_id"],
                meta["location"]["lat"], meta["location"]["lon"], meta["installed_on"], meta["recorded_status"],
                meta["last_inspection"]["inspection_id"], meta.get("status"), meta.get("decommissioned_on")))
    db.execute("DELETE FROM well_type_history WHERE asset_id=?", (a,))
    db.execute("DELETE FROM well_team_history WHERE asset_id=?", (a,))
    db.executemany("INSERT INTO well_type_history VALUES (?,?,?,?)", [(a, h["well_type"], h["from"], h.get("to")) for h in meta.get("type_history", [])])
    db.executemany("INSERT INTO well_team_history VALUES (?,?,?,?)", [(a, h["team_id"], h["from"], h.get("to")) for h in meta.get("team_history", [])])
    for e in meta["equipment"]:
        db.execute("INSERT OR REPLACE INTO equipment VALUES (?,?,?,?)", (e["equipment_id"], a, e["kind"], e["model"]))
    db.executemany("""INSERT OR REPLACE INTO inspections (inspection_id, asset_id, inspected_at, inspector_user_id, method, ambient_temp_c,
                      wellhead_temp_c, spill_detected, spill_area_pct, spill_est_volume_bbl, notes, recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                   [(i["inspection_id"], a, i["inspected_at"], i["inspector_user_id"], i["method"], i["ambient_temp_c"], i["wellhead_temp_c"],
                     int(i["spill_detected"]), i["spill_area_pct"], i["spill_est_volume_bbl"], i["notes"], i.get("recorded_at"))
                    for i in jl(wdir / "inspections.jsonl")])
    for m in jl(wdir / "maintenance.jsonl"):
        cost, rev = m["cost_usd"], m.get("cost_revision") or {}
        root_cause = load_report(db, m, wdir / m["report_file"]) if m["report_file"] else None
        db.execute("""INSERT OR REPLACE INTO maintenance (maintenance_id, asset_id, started_at, completed_at, maintenance_type, equipment_kind, issue,
                      action_taken, technician_user_id, contractor, downtime_hours, cost_labor, cost_parts, cost_total, triggered_by_inspection_id,
                      report_file, root_cause, recorded_at, cost_original, cost_revised_on, cost_revision_reason)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (m["maintenance_id"], a, m["started_at"], m["completed_at"], m["maintenance_type"], m["equipment_kind"], m["issue"],
                    m["action_taken"], m["technician_user_id"], m["contractor"], m["downtime_hours"], cost["labor"], cost["parts"], cost["total"],
                    m["triggered_by_inspection_id"], m["report_file"], root_cause, m.get("recorded_at"), rev.get("original_total"),
                    rev.get("revised_on"), rev.get("reason")))
    db.executemany("INSERT OR REPLACE INTO regulatory_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   [(r["event_id"], a, r["date"], r["agency"], r["event_type"], r["protocol_id"], r["related_inspection_id"],
                     r["hours_to_report"], r["detail"], r["fine_usd"], r["status"]) for r in jl(wdir / "regulatory-events.jsonl")])
    for c in jl(wdir / "context.jsonl"):
        db.execute("INSERT OR REPLACE INTO notes VALUES (?,?,?,?,?,?,?,?,?,'confirmed')",
                   (c["note_id"], a, c["created_at"], c["author_user_id"], c["note_type"], c.get("inspection_id"), c["text"],
                    c["valid_from"], c["valid_to"]))
        put_chunk(db, f"note:{c['note_id']}", "note", c["note_id"], a, None, c["note_type"], f"{c['note_id']} {a}\n{c['text']}")
        if c["note_type"] == "operator_note":
            kind, detail = extract.classify_note(c["text"])
            db.execute("INSERT OR REPLACE INTO note_events VALUES (?,?,?,?,?)", (c["note_id"], a, c["created_at"], kind, detail))
        elif c["note_type"] == "data_correction" and c.get("field") in CORRECTABLE:
            db.execute("INSERT OR IGNORE INTO corrections (target_type, target_id, field, original_value, corrected_value, author_user_id,"
                       " reason, created_at, source_note_id) VALUES ('inspection',?,?,?,?,?,?,?,?)",
                       (c["inspection_id"], c["field"], c["original_value"], c["corrected_value"], c["author_user_id"], c["text"],
                        c["created_at"], c["note_id"]))
        elif c["note_type"] == "data_correction":
            print(f"WARNING: data_correction {c['note_id']} changes unsupported field {c.get('field')!r}; not applied")
        elif c["note_type"] == "correction":
            if not NOT_A_SPILL.search(c["text"]):
                print(f"WARNING: correction {c['note_id']} is not a void-spill note; needs manual handling: {c['text']}")
                continue
            db.execute("INSERT OR IGNORE INTO corrections (target_type, target_id, field, original_value, corrected_value,"
                       " author_user_id, reason, created_at, source_note_id) VALUES ('inspection',?,'spill_detected',1,0,?,?,?,?)",
                       (c["inspection_id"], c["author_user_id"], c["text"], c["created_at"], c["note_id"]))


def main(dataset=HERE.parent / "sample-data", db_path=HERE.parent / "copilot.db"):
    t0 = time.time()
    dataset = Path(dataset)
    db = sqlite3.connect(db_path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=OFF")
    db.executescript((HERE / "schema.sql").read_text(encoding="utf-8"))
    ensure_columns(db)  # an older database lacks the newer columns
    area_names = load_fleet(db, dataset / "fleet")
    load_documents(db, dataset / "fleet", area_names)
    rules.seed(db, dataset / "fleet")
    wells = sorted((dataset / "assets").iterdir())
    for n, wdir in enumerate(wells, 1):
        load_well(db, wdir)
        if n % 100 == 0:
            db.commit()
            print(f"  loaded {n}/{len(wells)} wells ({time.time() - t0:.0f}s)", flush=True)
    rules.check(db)
    db.execute("DELETE FROM chunks_fts")
    db.execute("INSERT INTO chunks_fts SELECT chunk_id, title, text FROM chunks")
    db.execute("INSERT OR REPLACE INTO meta VALUES ('as_of', (SELECT date(max(inspected_at), '+1 day') FROM inspections))")
    db.commit()
    for t in ("wells", "inspections", "maintenance", "report_compliance", "report_facts", "regulatory_events", "notes", "note_events", "corrections",
              "moc", "recalls", "regulator_letters", "well_type_history", "well_team_history", "rules", "chunks"):
        print(f"{t:20} {db.execute(f'SELECT count(*) FROM {t}').fetchone()[0]}")
    print("as_of", db.execute("SELECT value FROM meta WHERE key='as_of'").fetchone()[0], f"({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main(*sys.argv[1:3])
