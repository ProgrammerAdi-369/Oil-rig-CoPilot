"""Load a dataset directory (sample or test) into one SQLite file. Idempotent: upserts by primary key, so a
second dataset loads alongside the first.   py -m copilot.ingest [sample-data] [copilot.db]"""
import json
import re
import sqlite3
import sys
from pathlib import Path

from . import rules

HERE = Path(__file__).parent
COMPLIANCE_ROW = re.compile(r"^\|\s*((?:SR|RC|WS)-\d+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$")
CONTAINED = re.compile(r"Contained about (\d+(?:\.\d+)?) hours")
NOT_A_SPILL = re.compile(r"not (?:a )?(?:crude )?spill", re.I)


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


def load_report(db, m, path):
    text = path.read_text(encoding="utf-8")
    root_cause = ""
    for n, (title, body) in enumerate(sections(text)):
        if title.lower() == "root cause":
            root_cause = body
        head = f"{m['maintenance_id']} {m['asset_id']} {m['equipment_kind']} — {m['issue']}\n"
        put_chunk(db, f"report:{m['maintenance_id']}:{n}", "report", m["maintenance_id"], m["asset_id"], None, title, head + body)
    for line in text.splitlines():
        r = COMPLIANCE_ROW.match(line)
        if r:
            proto, result, detail = r.group(1), r.group(2).replace("**", ""), r.group(3)
            c = CONTAINED.search(detail) if proto == "SR-02" else None
            db.execute("INSERT OR REPLACE INTO report_compliance VALUES (?,?,?,?,?)",
                       (m["maintenance_id"], proto, result, detail, float(c.group(1)) if c else None))
    return root_cause


def load_well(db, wdir):
    meta = json.loads((wdir / "metadata.json").read_text(encoding="utf-8"))
    a = meta["asset_id"]
    db.execute("INSERT OR REPLACE INTO wells VALUES (?,?,?,?,?,?,?,?,?,?,?)",
               (a, meta["name"], meta["well_type"], meta["area_id"], meta["team_id"], meta["in_charge_user_id"],
                meta["location"]["lat"], meta["location"]["lon"], meta["installed_on"], meta["recorded_status"],
                meta["last_inspection"]["inspection_id"]))
    for e in meta["equipment"]:
        db.execute("INSERT OR REPLACE INTO equipment VALUES (?,?,?,?)", (e["equipment_id"], a, e["kind"], e["model"]))
    db.executemany("INSERT OR REPLACE INTO inspections VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   [(i["inspection_id"], a, i["inspected_at"], i["inspector_user_id"], i["method"], i["ambient_temp_c"],
                     i["wellhead_temp_c"], int(i["spill_detected"]), i["spill_area_pct"], i["spill_est_volume_bbl"], i["notes"])
                    for i in jl(wdir / "inspections.jsonl")])
    for m in jl(wdir / "maintenance.jsonl"):
        cost = m["cost_usd"]
        root_cause = load_report(db, m, wdir / m["report_file"]) if m["report_file"] else None
        db.execute("INSERT OR REPLACE INTO maintenance VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (m["maintenance_id"], a, m["started_at"], m["completed_at"], m["maintenance_type"], m["equipment_kind"],
                    m["issue"], m["action_taken"], m["technician_user_id"], m["contractor"], m["downtime_hours"],
                    cost["labor"], cost["parts"], cost["total"], m["triggered_by_inspection_id"], m["report_file"], root_cause))
    db.executemany("INSERT OR REPLACE INTO regulatory_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   [(r["event_id"], a, r["date"], r["agency"], r["event_type"], r["protocol_id"], r["related_inspection_id"],
                     r["hours_to_report"], r["detail"], r["fine_usd"], r["status"]) for r in jl(wdir / "regulatory-events.jsonl")])
    for c in jl(wdir / "context.jsonl"):
        db.execute("INSERT OR REPLACE INTO notes VALUES (?,?,?,?,?,?,?,?,?,'confirmed')",
                   (c["note_id"], a, c["created_at"], c["author_user_id"], c["note_type"], c.get("inspection_id"), c["text"],
                    c["valid_from"], c["valid_to"]))
        put_chunk(db, f"note:{c['note_id']}", "note", c["note_id"], a, None, c["note_type"], f"{c['note_id']} {a}\n{c['text']}")
        if c["note_type"] == "correction":
            if not NOT_A_SPILL.search(c["text"]):
                print(f"WARNING: correction {c['note_id']} is not a void-spill note; needs manual handling: {c['text']}")
                continue
            db.execute("INSERT OR IGNORE INTO corrections (target_type, target_id, field, original_value, corrected_value,"
                       " author_user_id, reason, created_at, source_note_id) VALUES ('inspection',?,'spill_detected',1,0,?,?,?,?)",
                       (c["inspection_id"], c["author_user_id"], c["text"], c["created_at"], c["note_id"]))


def main(dataset=HERE.parent / "sample-data", db_path=HERE.parent / "copilot.db"):
    dataset = Path(dataset)
    db = sqlite3.connect(db_path)
    db.executescript((HERE / "schema.sql").read_text(encoding="utf-8"))
    load_fleet(db, dataset / "fleet")
    rules.seed(db, dataset / "fleet")
    for wdir in sorted((dataset / "assets").iterdir()):
        load_well(db, wdir)
    rules.check(db)
    db.execute("DELETE FROM chunks_fts")
    db.execute("INSERT INTO chunks_fts SELECT chunk_id, title, text FROM chunks")
    db.execute("INSERT OR REPLACE INTO meta VALUES ('as_of', (SELECT date(max(inspected_at), '+1 day') FROM inspections))")
    db.commit()
    for t in ("wells", "inspections", "maintenance", "report_compliance", "regulatory_events", "notes", "corrections", "rules", "chunks"):
        print(f"{t:18} {db.execute(f'SELECT count(*) FROM {t}').fetchone()[0]}")
    print("as_of", db.execute("SELECT value FROM meta WHERE key='as_of'").fetchone()[0])


if __name__ == "__main__":
    main(*sys.argv[1:3])
