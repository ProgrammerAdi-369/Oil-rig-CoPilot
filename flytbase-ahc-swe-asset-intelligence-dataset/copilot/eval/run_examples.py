"""Expected answers from 03-evaluation-queries.md as assertions against the tools.   py -m copilot.eval.run_examples"""
import sys
import traceback

from copilot import tools

tools.clean_copy()  # never judge the engine on a database that someone has been using
CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


@check
def q1_status_card():
    c = tools.well_status("WELL-0001")["rows"][0]
    assert c["producing"] is False and c["delta_c"] == 3.2 and c["limit_c"] == 15, c
    assert (c["last_inspection"], c["method"], c["inspector"]) == ("INS-0001-0203", "drone", "Ryan Brooks")
    assert c["last_inspected_at"].startswith("2026-10-15") and c["recorded_status"] == "active"
    assert "CTX-0001-003" in {n["note_id"] for n in c["active_notes"]}


@check
def q2_not_producing_ne08():
    rows = {r["asset_id"]: r for r in tools.find_wells(producing=False, area_id="NE-08")["rows"]}
    assert {k: v["delta_c"] for k, v in rows.items()} == {"WELL-0164": 4.1, "WELL-0170": 2.9, "WELL-0172": 5.7, "WELL-0175": 0.4}, rows
    assert {k: v["has_recorded_reason"] for k, v in rows.items()} == {
        "WELL-0164": False, "WELL-0170": True, "WELL-0172": True, "WELL-0175": False}
    assert rows["WELL-0170"]["open_repairs"][0]["maintenance_id"] == "MNT-0170-031"
    assert rows["WELL-0172"]["open_repairs"][0]["maintenance_id"] == "MNT-0172-028"
    assert rows["WELL-0164"]["inspector_note"] == "Pump jack not moving."


@check
def q3_line_chart():
    r = tools.series("WELL-0001", last_weeks=13)["rows"]
    assert len(r) == 13 and r[0]["date"] == "2026-07-23" and r[-1]["date"] == "2026-10-15", (len(r), r[0], r[-1])
    assert [x["date"] for x in r if not x["producing"]] == ["2026-10-08", "2026-10-15"]


@check
def q4_spills_well_0001():
    r = tools.spills(well_id="WELL-0001", last_months=48)
    assert r["count"] == 6 and r["total_bbl"] == 15.1, r
    assert "INS-0001-0070" not in r["evidence"]
    assert [x["bbl"] for x in r["rows"]] == [0.5, 2.6, 3.3, 0.3, 6.8, 1.6]


@check
def q5_downtime_2025():
    r = tools.downtime(well_id="WELL-0001", since="2025-01-01", until="2025-12-31")["rows"]
    assert r[0]["days"] == 21 and r[0]["weeks"] == 3, r


@check
def q6_top3_ne07():
    r = tools.downtime(area_id="NE-07", top_n=4, last_months=4)["rows"]
    assert {x["key"]: x["days"] for x in r} == {"WELL-0121": 49, "WELL-0138": 42, "WELL-0107": 42, "WELL-0119": 28}, r


@check
def q7_map_ne08():
    r = tools.spills(area_id="NE-08", last_days=90)["rows"]
    assert {x["asset_id"]: x["bbl"] for x in r} == {"WELL-0151": 4.5, "WELL-0165": 1.2, "WELL-0175": 3.9, "WELL-0186": 0.6}, r
    assert {x["asset_id"]: (x["lat"], x["lon"]) for x in r}["WELL-0151"] == (32.12246, -102.18445)


@check
def q8_heatmap_2026():
    expected = {"Southwest Block 23": [4, 3, 3, 6, 3, 4, 4, 3, 3, 2], "Southwest Block 24": [7, 4, 5, 6, 5, 5, 3, 1, 5, 2],
                "Northeast Block 7": [5, 3, 2, 4, 6, 6, 2, 4, 4, 1], "Northeast Block 8": [4, 4, 4, 3, 2, 4, 4, 0, 1, 0]}
    got = {}
    for r in tools.spills(group_by="area_month", since="2026-01-01")["rows"]:
        got.setdefault(r["area"], [0] * 10)[int(r["month"][5:]) - 1] = r["spills"]
    assert got == expected, got


@check
def q9_rules_broken_well_0001():
    res = tools.compliance(well_id="WELL-0001", last_months=12)
    rows = res["rows"]
    rca = [a for a in res["open_actions"] if a["protocol_id"] == "RCA"]
    assert len(rca) == 1 and set(rca[0]["evidence"]) == {"MNT-0001-028", "MNT-0001-029", "MNT-0001-032"}, res["open_actions"]
    got = {r["protocol_id"]: r for r in rows if r["status"] == "breach"}
    assert set(got) == {"SR-01", "SR-02", "SR-03", "RC-04"} and len(rows) == 4, rows
    assert {r["inspection_id"] for r in rows} == {"INS-0001-0185"}
    assert "REG-0001-001" in got["SR-01"]["evidence"] and "41" in got["SR-01"]["detail"]
    assert got["SR-02"]["evidence"][0] == "MNT-0001-029" and got["SR-03"]["due"] == "2026-08-10" and got["RC-04"]["due"] == "2026-07-30"


@check
def q10_not_contained_sw24():
    rows = [r for r in tools.compliance(area_id="SW-24", last_days=90)["rows"] if r["protocol_id"] == "SR-02"]
    assert {r["asset_id"]: r["evidence"][0] for r in rows} == {"WELL-0082": "MNT-0082-028", "WELL-0100": "MNT-0100-034"}, rows
    assert {r["asset_id"] for r in rows if "7.1 h" in r["detail"]} == {"WELL-0082"}
    assert {r["asset_id"] for r in rows if "8.1 h" in r["detail"]} == {"WELL-0100"}


@check
def q11_costs_this_year():
    r = tools.repairs(well_ids=["WELL-0121", "WELL-0138", "WELL-0107"], this_year=True, group_by="well")["rows"]
    assert {x["asset_id"]: round(x["cost_usd"]) for x in r} == {"WELL-0121": 25794, "WELL-0138": 46942, "WELL-0107": 5176}, r


@check
def q14_rca_candidates_manual_rule():
    r = tools.rca_candidates("pump_jack", area_id="NE-07")["rows"]
    assert [x["asset_id"] for x in r] == ["WELL-0108", "WELL-0121", "WELL-0138"] and {x["corrective_repairs"] for x in r} == {3}, r


def main():
    failed = 0
    for fn in CHECKS:
        try:
            fn()
            print("PASS", fn.__name__)
        except Exception:
            failed += 1
            print("FAIL", fn.__name__)
            traceback.print_exc(limit=2)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
