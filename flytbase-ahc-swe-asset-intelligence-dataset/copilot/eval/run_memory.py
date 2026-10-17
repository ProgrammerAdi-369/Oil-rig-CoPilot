"""Q11-Q18 as one scripted multi-user session on a throw-away copy of copilot.db.   py -m copilot.eval.run_memory"""
import shutil
import tempfile
from pathlib import Path

from copilot import tools

tmp = Path(tempfile.mkdtemp()) / "copilot.db"
shutil.copy(tools.DB_PATH, tmp)
tools.DB_PATH = tmp
from copilot import memory  # noqa: E402  (must import after DB_PATH is redirected)

MICHAEL, JESSICA, TYLER, JAKE, LAURA = "U-201", "U-202", "U-204", "U-102", "U-401"
DAY1 = "2026-10-15T10:00:00Z"


def ok(name):
    print("PASS", name)


# Q11: day 1 Michael asks Q6; day 2, new chat, asks about "the three wells we discussed yesterday"
top3 = tools.downtime(area_id="NE-07", top_n=3, last_months=4)["rows"]
memory.log_turn(MICHAEL, "chat-1", "user", "Which 3 wells in Northeast Block 7 had the most downtime in the last 4 months?", DAY1)
memory.remember(MICHAEL, "chat-1", "top 3 downtime NE-07", [r["key"] for r in top3], DAY1)
got = memory.recall(MICHAEL, days_ago=1)
assert sorted(got["rows"][0]["well_ids"]) == ["WELL-0107", "WELL-0121", "WELL-0138"], got
costs = tools.repairs(well_ids=got["rows"][0]["well_ids"], this_year=True, group_by="well")["rows"]
assert {c["asset_id"]: round(c["cost_usd"]) for c in costs} == {"WELL-0121": 25794, "WELL-0138": 46942, "WELL-0107": 5176}
ok("q11 remembers past conversation")

# Q12: correct a raw reading; original kept; conflict with inspector note surfaced; Q2 now has 3 wells
r = memory.correct_value(MICHAEL, "wellhead_temp_c", 41.0, "handheld thermal gun faulty; crew re-measured", well_id="WELL-0164")["rows"][0]
assert r["recorded"]["inspection_id"] == "INS-0164-0205" and r["recorded"]["original"] == 24.0 and r["recorded"]["by"] == MICHAEL
assert r["before"]["producing"] == 0 and r["after"]["producing"] == 1, r
assert r["conflicts"] and r["conflicts"][0]["with"] == "inspector_note" and "Pump jack not moving" in r["conflicts"][0]["detail"]
fw = tools.find_wells(producing=False, area_id="NE-08")
assert {w["asset_id"] for w in fw["rows"]} == {"WELL-0170", "WELL-0172", "WELL-0175"}
assert [(x["asset_id"], x["author_user_id"]) for x in fw["corrected_out"]] == [("WELL-0164", MICHAEL)], fw["corrected_out"]
assert "WELL-0164" in fw["note"] and "Michael Turner" in fw["note"], fw["note"]
ok("q12 raw-data correction")

# Q13: correct the AI's spill volume -> becomes reportable; SR-01 overdue, SR-03 pending, SR-02 already breached
r = memory.correct_value(MICHAEL, "spill_est_volume_bbl", 5.4, "field crew measured 5.4 bbl", inspection_id="INS-0151-0201")["rows"][0]
assert r["recorded"]["original"] == 4.5 and r["before"]["spill_class"] == "moderate" and r["after"]["spill_class"] == "reportable", r
assert "MNT-0151-025" in r["linked_repairs"]
assert {(x["protocol_id"], x["status"]) for x in r["compliance_now"]} >= {("SR-01", "breach"), ("SR-03", "pending")}, r["compliance_now"]
assert any(x["protocol_id"] == "SR-04" and "moderate" in x["detail"] for x in r["repair_report_said"]), r["repair_report_said"]
c = {(x["protocol_id"], x["status"]): x for x in tools.compliance(well_id="WELL-0151", last_days=90)["rows"]}
assert ("SR-01", "breach") in c and "no written notice" in c[("SR-01", "breach")]["detail"], c
assert c[("SR-03", "pending")]["due"] == "2026-11-23" and ("SR-02", "breach") in c and "6.4" in c[("SR-02", "breach")]["detail"], c
ok("q13 AI-analysis correction")

# Q14: type-scoped rule; T350 wells at 2 repairs are added, T200 WELL-0102 is not; answer cites the user's rule
assert [x["asset_id"] for x in tools.rca_candidates("pump_jack", area_id="NE-07")["rows"]] == ["WELL-0108", "WELL-0121", "WELL-0138"]
memory.add_type_rule(MICHAEL, "T350", "rca_corrective_count", 2, "our team now wants a pump jack root-cause analysis after 2 repairs")
rows = tools.rca_candidates("pump_jack", area_id="NE-07")["rows"]
assert [x["asset_id"] for x in rows] == ["WELL-0108", "WELL-0120", "WELL-0121", "WELL-0138"], rows
src = {x["asset_id"]: x["threshold_source"] for x in rows}
assert "Michael Turner" in src["WELL-0120"] and "manual" in src["WELL-0121"] and "WELL-0102" not in src, src
ok("q14 type-scoped rule")

# Q15: other users see the corrections
s = tools.well_status("WELL-0164")["rows"][0]
assert s["producing"] is True and s["corrections"][0]["author_user_id"] == MICHAEL and s["inspector_note"] == "Pump jack not moving."
big = [x for x in tools.spills(area_id="NE-08", last_days=90)["rows"] if x["spill_class"] in ("reportable", "major")]
assert [x["asset_id"] for x in big] == ["WELL-0151"], big
ok("q15 correction reaches other users")

# Q16: shared note visible to others; private memory is not
n = memory.add_well_note(JAKE, "WELL-0007", "WELL-0007 will be shut in from 17 Oct for a 10-day planned workover", 0, "2026-10-17", "2026-10-27")["rows"][0]
assert not n["conflicts"], n
up = tools.well_status("WELL-0007")["rows"][0]["upcoming_notes"]
assert up and up[0]["author"] == "Jake Morales" and up[0]["valid_from"] == "2026-10-17", up
assert memory.recall(JESSICA, days_ago=1)["empty"] is True
ok("q16 shared knowledge, private memory")

# Q17: disagreement with data / with another user is flagged, both statements kept
a = memory.add_well_note(MICHAEL, "WELL-0175", "WELL-0175 has been shut in for planned work since 14 Oct", 0, "2026-10-14")["rows"][0]
assert not a["conflicts"] and a["recorded"]["status"] == "reported", a
b = memory.add_well_note(TYLER, "WELL-0175", "WELL-0175 is running fine", 1)["rows"][0]
assert {x["with"] for x in b["conflicts"]} == {"data", "note"} and b["recorded"]["status"] == "unconfirmed", b
assert "0.4" in [x for x in b["conflicts"] if x["with"] == "data"][0]["detail"]
c = memory.add_well_note(JAKE, "WELL-0001", "WELL-0001 is back online since 14 Oct", 1, "2026-10-14")["rows"][0]
assert [x["with"] for x in c["conflicts"]] == ["data"] and "CTX-0001-003" in {x["note_id"] for x in c["active_notes"]}, c
assert {x["note_id"] for x in tools.well_notes("WELL-0175", last_days=3)["rows"]} >= {a["recorded"]["note_id"], b["recorded"]["note_id"]}
ok("q17 people disagree with the data")

# Q18: spill flagged by AI, two disagreeing non-formal notes, repair done -> detection stands, both sources shown
sp = tools.spills(well_id="WELL-0101", since="2026-08-15", until="2026-08-25")["rows"]
assert [(x["inspection_id"], x["bbl"]) for x in sp] == [("INS-0101-0197", 1.0)], sp
notes = {x["note_id"]: x for x in tools.well_notes("WELL-0101")["rows"]}
assert notes["CTX-0101-002"]["author"] == "Ryan Brooks" and notes["CTX-0101-003"]["author"] == "Chris Dalton"
assert notes["CTX-0101-002"]["note_type"] != "correction" and notes["CTX-0101-003"]["note_type"] != "correction"
assert tools.repairs(well_id="WELL-0101", since="2026-08-15", until="2026-09-30")["rows"]
ok("q18 disagreement about AI analysis")
