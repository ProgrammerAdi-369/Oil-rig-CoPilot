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
]

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


def check(db):
    """New-data guard: every well type in the data must have a producing rule, else fail loudly."""
    missing = [r[0] for r in db.execute(
        "SELECT DISTINCT well_type FROM wells WHERE well_type NOT IN "
        "(SELECT scope_value FROM rules WHERE scope='well_type' AND key='producing_delta_c')")]
    if missing:
        raise SystemExit(f"No producing_delta_c rule parsed for well types {missing}: check fleet/well-types/<type>.md")
