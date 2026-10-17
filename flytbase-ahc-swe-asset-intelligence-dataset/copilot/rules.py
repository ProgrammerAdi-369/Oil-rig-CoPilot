"""Thresholds the data never stores. Per-type numbers are parsed out of the well-type manuals; company-wide
deadlines are transcribed from the SOPs (each row cites its source so answers can quote it)."""
import re
from pathlib import Path

# (key, value, unit, source, section) — verified against fleet/sops/*.md and fleet/well-types/T200.md
GLOBAL = [
    ("spill_moderate_bbl", 1, "bbl", "SOP-SR", "3"),
    ("spill_reportable_bbl", 5, "bbl", "SOP-SR", "3"),
    ("spill_major_bbl", 25, "bbl", "SOP-SR", "3"),
    ("hse_notice_hours", 72, "h", "SOP-SR", "3"),
    ("sr01_report_hours", 24, "h", "SOP-SR", "SR-01"),
    ("sr01_major_report_hours", 2, "h", "SOP-SR", "SR-01"),
    ("sr02_contain_hours", 4, "h", "SOP-SR", "SR-02"),
    ("sr03_verify_days", 60, "d", "SOP-SR", "SR-03"),
    ("rc01_inspect_days", 14, "d", "SOP-RC", "RC-01"),
    ("rc03_downtime_days", 14, "d", "SOP-RC", "RC-03"),
    ("rc04_response_days", 30, "d", "SOP-RC", "RC-04"),
    ("rca_corrective_count", 3, "events", "OM-T200", "10"),
    ("rca_window_months", 12, "months", "OM-T200", "10"),
    ("spill_shutin_pct", 5, "%", "OM-T200", "9.5"),
    # Operations SOP rev 2 (test data). A key ending @YYYY-MM-DD applies from that date; the newest one in force wins.
    ("ops1_hours", 24, "h", "SOP-OPS", "OPS-1"),
    ("ops1_hours@2027-01-01", 12, "h", "SOP-OPS", "OPS-1"),
    ("ops5_temp_c", -5, "°C", "SOP-OPS", "OPS-5"),
    ("ops5_days", 7, "d", "SOP-OPS", "OPS-5"),
    ("ops6_days", 30, "d", "SOP-OPS", "OPS-6"),
]

# phrases the hand-transcribed rules above depend on; if a document no longer says them, the rule needs re-reading
DOC_CHECKS = {
    "operations-sop-rev2.md": [r"\*\*24 hours\*\* for reports noted before 1 Jan 2027", r"\*\*12 hours\*\* for reports noted from 1 Jan 2027",
                               r"at or below \*\*−5 °C\*\*", r"within \*\*7 days\*\*", r"within \*\*30 days\*\*"],
}
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4}
EQUIPMENT_WORDS = {"ESP": "esp_pump"}

# (key, regex on the manual text, unit, section)
PER_TYPE = [
    ("producing_delta_c", r"at least \*\*(\d+(?:\.\d+)?) °C above", "°C", "producing rule"),
    ("temp_alarm_c", r"at or below \**(\d+(?:\.\d+)?) °C", "°C", "temperature alarm"),
]


def seed(db, fleet_dir):
    fleet = Path(fleet_dir)
    for key, value, unit, source, section in GLOBAL:
        db.execute("INSERT OR REPLACE INTO rules VALUES ('global','',?,?,?,?,?,'dataset','1970-01-01')",
                   (key, value, unit, source, section))
    for manual in sorted((fleet / "well-types").glob("*.md")):
        wtype, text = manual.stem, manual.read_text(encoding="utf-8")
        for key, pat, unit, section in PER_TYPE:
            m = re.search(pat, text)
            if m:
                db.execute("INSERT OR REPLACE INTO rules VALUES ('well_type',?,?,?,?,?,?,'dataset','1970-01-01')",
                           (wtype, key, float(m.group(1)), unit, f"OM-{wtype}", section))
        # equipment-specific escalation, e.g. T500: "Two or more corrective maintenance events on the ESP in the 12 months"
        for m in re.finditer(r"\*\*(\w+) or more\*\* corrective maintenance events on the \*\*(\w+)\*\*", text):
            n, kind = NUMBER_WORDS.get(m.group(1).lower()), EQUIPMENT_WORDS.get(m.group(2), m.group(2).lower())
            if n:
                db.execute("INSERT OR REPLACE INTO rules VALUES ('well_type',?,?,?,?,?,?,'dataset','1970-01-01')",
                           (wtype, f"rca_count_{kind}", n, "events", f"OM-{wtype}", "maintenance escalation"))
    for doc, phrases in DOC_CHECKS.items():
        f = fleet / "sops" / doc
        if f.exists():
            text = f.read_text(encoding="utf-8")
            missing = [p for p in phrases if not re.search(p, text)]
            if missing:
                print(f"WARNING: {doc} no longer says {missing}; re-read it and update copilot/rules.py")


def check(db):
    """New-data guard: every well type in the data must have a producing rule, else fail loudly."""
    missing = [r[0] for r in db.execute(
        "SELECT DISTINCT well_type FROM wells WHERE well_type NOT IN "
        "(SELECT scope_value FROM rules WHERE scope='well_type' AND key='producing_delta_c')")]
    if missing:
        raise SystemExit(f"No producing_delta_c rule parsed for well types {missing}: check fleet/well-types/<type>.md")
