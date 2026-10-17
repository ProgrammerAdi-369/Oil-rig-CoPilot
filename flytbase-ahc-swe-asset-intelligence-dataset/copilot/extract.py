"""Turn free text into facts: operator notes -> events, repair reports -> structured facts, and the fleet documents
(MOC memos, supplier recall notice, regulator letter). Pure functions, no database; ingest stores their output.

Operator notes follow ~45 fixed templates, so classification is by ordered regex with a keyword fallback for phrasing we
have not seen. The kinds and what they mean are defined by the Operations SOP rev 2 (OPS-1..3)."""
import re
from datetime import date

MONTHS = {m: i + 1 for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}

# ---------------------------------------------------------------- operator notes
# (kind, regex); the first match wins. `bypass_out` precedes `bypass_in`: "valve work finished and bypass removed".
NOTE_RULES = [
    ("bypass_out", r"bypass (?:removed|pulled)|(?:took|taken|removed|pulled) (?:the )?bypass|bypass (?:was )?(?:taken )?out\b|took the bypass out"),
    ("bypass_in", r"bypass (?:in place|installed)|(?:put|had|placed|installed) (?:the )?bypass|bypass in\b"),
    ("gas_odor", r"gas odou?r|gas smell|smell(?:ed)? (?:of )?gas|rotten[- ]egg|h2s (?:monitor )?(?:alarm|alarmed)|hns monitor"),
    ("restart", r"\brestarted\b(?! from the panel)|put back on production|brought .{0,20} back online"),
    ("shut_in", r"shut[- ]in\b(?! until)|shut (?:the )?well in|\bshut in\b(?! until)"),
    ("delay_weather", r"delayed by weather|weather"),
    ("delay_parts", r"waiting on (?:replacement )?parts|back-?ordered"),
    ("drive_trip", r"drive tripping|tripp(?:ed|ing) on underload"),
    ("amps_hunting", r"amps hunting"),
    ("tagging_bottom", r"tagging bottom"),
    ("fluid_pound", r"fluid pound"),
    ("rattling", r"rattling|rattle"),
    ("rod_squeal", r"rod squeal|squeal"),
]
# the "waiting on parts ... well stays shut in until they arrive" note is a delay, not a new shut-in event
ABNORMAL = {"drive_trip": 3, "tagging_bottom": 3, "amps_hunting": 2, "fluid_pound": 2, "rattling": 2, "rod_squeal": 1}
STATUS_KINDS = {"shut_in", "restart"}  # the only note kinds that move a well's status (OPS-3)


def classify_note(text):
    """-> (kind, detail). kind in NOTE_RULES kinds or 'leak' / 'routine'. Fallbacks keep unseen phrasing from becoming 'routine' silently."""
    t = text.strip()
    if re.search(r"waiting on (?:replacement )?parts.*shut in", t, re.I):
        return "delay_parts", "waiting on parts from the vendor"
    for kind, pat in NOTE_RULES:
        if re.search(pat, t, re.I):
            if kind == "shut_in" and re.search(r"leak", t, re.I):
                return "shut_in", "leak"
            return kind, ""
    if re.search(r"leak", t, re.I):
        return "leak", ""
    if re.search(r"\bgas\b|h2s", t, re.I) and re.search(r"odou?r|smell|alarm", t, re.I):
        return "gas_odor", ""
    return "routine", ""


# ---------------------------------------------------------------- repair reports
ROOT_CAUSE_ORDER = [  # OPS-4: the first row with a keyword in the text gives the category
    ("Installation error", ["installation", "installed incorrectly", "misaligned", "re-terminated", "not torqued", "cross-threaded"]),
    ("Sand", ["sand"]),
    ("Scale", ["scale", "paraffin"]),
    ("Gas interference", ["gas lock", "gas interference", "free gas"]),
    ("Corrosion", ["corrosion", "corroded"]),
    ("Electrical", ["winding", "insulation", "switch", "terminal box"]),
    ("Fatigue/wear", ["fatigue", "wear", "worn", "years of service", "buckling", "ageing", "vibration"]),
]
DELAY_REASONS = [  # sentence fragment -> category (the four reasons the reports use)
    ("weather", r"heavy rain|impassable|weather|snow|storm"),
    ("parts", r"back-?ordered|replacement part|parts? (?:from|on order)"),
    ("contractors", r"contractor"),
    ("crews", r"crew was committed|higher-priority|spill response|rig is busy|workover rig|crew"),
]


def root_cause_category(text):
    t = (text or "").lower()
    for cat, words in ROOT_CAUSE_ORDER:
        if any(w in t for w in words):
            return cat
    return "Other"


def _section(text, title):
    m = re.search(rf"^## {re.escape(title)}\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else ""


def parse_report(text):
    """Structured facts of one maintenance report. Every field is optional (None / False when the report lacks it)."""
    out = {"interim": bool(re.search(r"interim report", text, re.I)), "pump_model": None, "pump_serial": None, "pump_lot": None,
           "followup_days": None, "followup_text": None, "soil_samples_lab": "Soil samples sent to the lab." in text,
           "h2s_ppm": None, "extra_days": None, "extra_days_expected": False, "delay_reason": None, "delay_text": None}
    if m := re.search(r"\*\*Parts installed:\*\*\s*(.+?),\s*serial\s+(\S+),\s*lot\s+(\S+)", text):
        out["pump_model"], out["pump_serial"], out["pump_lot"] = m.group(1).strip(), m.group(2), m.group(3).rstrip(".")
    if m := re.search(r"\*\*Follow-up:\*\*\s*Crew to return within (\d+) days?(?: to)?\s*(.*)", text):
        out["followup_days"], out["followup_text"] = int(m.group(1)), m.group(2).strip().rstrip(".")
    if m := re.search(r"highest reading (\d+(?:\.\d+)?) ppm", text):
        out["h2s_ppm"] = float(m.group(1))
    if m := re.search(r"(expected to )?stay(?:ed)? shut in for about (\d+) days longer than the repair itself because ([^.\n]+)", text):
        out["extra_days"], out["extra_days_expected"], out["delay_text"] = int(m.group(2)), bool(m.group(1)), m.group(3).strip()
        out["delay_reason"] = next((cat for cat, pat in DELAY_REASONS if re.search(pat, m.group(3), re.I)), "other")
    out["root_cause"] = _section(text, "Root cause")
    out["root_cause_category"] = root_cause_category(out["root_cause"])
    return out


# ---------------------------------------------------------------- fleet documents
def _date(s):
    d, mon, y = s.split()
    return date(int(y), MONTHS[mon[:3]], int(d)).isoformat()


def parse_moc(text):
    """MOC memo -> {moc_id, wells, effective_from, expires, extends}. An extension memo carries no well list of its own."""
    moc_id = re.search(r"MOC-\d{4}-\d{3}", text).group(0)
    wells = sorted(set(re.findall(r"WELL-\d{4}", re.search(r"## Change(.*?)(?=^## |\Z)", text, re.M | re.S).group(1))))
    eff = re.search(r"Effective from (\d{1,2} \w{3}\w* \d{4})", text)
    exp = re.search(r"expires on (\d{1,2} \w{3}\w* \d{4})", text)
    ext = re.search(r"extends (MOC-\d{4}-\d{3})", text)
    return {"moc_id": moc_id, "wells": wells, "effective_from": _date(eff.group(1)) if eff else None,
            "expires": _date(exp.group(1)) if exp else None, "extends": ext.group(1) if ext else None,
            "title": (re.search(r"\*\*Title:\*\*\s*(.+)", text) or [None, ""])[1].strip()}


def parse_recall(text):
    ref = re.search(r"\*\*Reference:\*\*\s*(\S+)", text).group(1)
    notice = _date(re.search(r"\*\*Date:\*\*\s*(\d{1,2} \w{3}\w* \d{4})", text).group(1))
    model = re.search(r"Highline [A-Z]+-\d+", text) or re.search(r"([A-Z][a-z]+ [A-Z]{2}-\d+)", text)
    lots = re.findall(r"^- (LOT-[\w-]+)\s*$", re.search(r"## What is recalled(.*?)(?=^## |\Z)", text, re.M | re.S).group(1), re.M)
    by = re.search(r"by (\d{1,2} \w{3}\w* \d{4})", text)
    return {"ref": ref, "notice_date": notice, "model": model.group(0) if model else None, "lots": lots,
            "deadline": _date(by.group(1)) if by else None}


def parse_letter(text, areas):
    """Regulator letter -> criteria. `areas` = {area_id: name}; the letter names areas by name."""
    since = re.search(r"since (\d{1,2} \w{3}\w* \d{4})", text)
    due = re.search(r"submitted by (\d{1,2} \w{3}\w* \d{4})", text)
    bbl = re.search(r"(\d+(?:\.\d+)?) bbl or more", text)
    sentence = re.search(r'contains the sentence "([^"]+)"', text)
    named = [aid for aid, name in areas.items() if name in text.split("**Subject:**")[1].split("\n")[0]
             or name in re.search(r"For every reportable spill in ([^,]+?) since", text, re.S).group(1)]
    return {"date": _date(re.search(r"\*\*Date:\*\*\s*(\d{1,2} \w{3}\w* \d{4})", text).group(1)), "areas": named,
            "since": _date(since.group(1)) if since else None, "due": _date(due.group(1)) if due else None,
            "min_bbl": float(bbl.group(1)) if bbl else 5.0, "required_sentence": sentence.group(1) if sentence else None}
