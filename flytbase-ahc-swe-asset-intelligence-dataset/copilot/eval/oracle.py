"""Independent ground truth: recomputed straight from the raw dataset files (JSON/JSONL/Markdown), never from
copilot.db or its views, so a bug in a view cannot make the critic agree with a wrong answer.
   O = Oracle(dataset_dir, as_of="2026-10-16");  O.downtime("WELL-0001", "2025-01-01", "2025-12-31") -> 21"""
import json
import re
from datetime import date, timedelta
from pathlib import Path


def jl(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


class Oracle:
    def __init__(self, dataset, as_of=None, corrections=None):
        """corrections: {inspection_id: {"wellhead_temp_c": x, "spill_est_volume_bbl": y, "spill_detected": 0}} from the session."""
        root = Path(dataset)
        self.fix = corrections or {}
        self.wells, self.ins, self.mnt, self.reg, self.void = {}, {}, {}, {}, set()
        self.delta = {}
        for md in (root / "fleet" / "well-types").glob("*.md"):
            m = re.search(r"at least \*\*(\d+(?:\.\d+)?) °C above", md.read_text(encoding="utf-8"))
            self.delta[md.stem] = float(m.group(1))
        self.areas = {a["area_id"]: a for a in json.loads((root / "fleet" / "areas.json").read_text(encoding="utf-8"))["areas"]}
        for d in sorted((root / "assets").iterdir()):
            meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
            a = meta["asset_id"]
            self.wells[a] = meta
            self.ins[a] = jl(d / "inspections.jsonl")
            self.mnt[a] = jl(d / "maintenance.jsonl")
            self.reg[a] = jl(d / "regulatory-events.jsonl")
            for n in jl(d / "context.jsonl"):
                if n["note_type"] == "correction":
                    self.void.add(n["inspection_id"])
            for m in self.mnt[a]:
                m["_dir"] = d
        last = max(i["inspected_at"] for v in self.ins.values() for i in v)
        self.as_of = as_of or (date.fromisoformat(last[:10]) + timedelta(days=1)).isoformat()

    # ---- windows (inclusive, compared by date)
    def months_back(self, n, end=None):
        end = date.fromisoformat(end or self.as_of)
        y, m = divmod(end.year * 12 + end.month - 1 - n, 12)
        return date(y, m + 1, min(end.day, 28 if m == 1 else 30 if m + 1 in (4, 6, 9, 11) else 31)).isoformat()

    def days_back(self, n):
        return (date.fromisoformat(self.as_of) - timedelta(days=n)).isoformat()

    def _eff(self, i):
        return {**i, **self.fix.get(i["inspection_id"], {})}

    def producing(self, asset, i):
        i = self._eff(i)
        return i["wellhead_temp_c"] - i["ambient_temp_c"] >= self.delta[self.wells[asset]["well_type"]]

    def downtime(self, asset, since, until):
        return 7 * sum(1 for i in self.ins[asset] if since <= i["inspected_at"][:10] <= until and not self.producing(asset, i))

    def downtime_by_well(self, area, since, until):
        return {a: self.downtime(a, since, until) for a, w in self.wells.items() if w["area_id"] == area}

    def spills(self, asset, since, until):
        out = []
        for i in self.ins[asset]:
            e = self._eff(i)
            if since <= i["inspected_at"][:10] <= until and e["spill_detected"] and i["inspection_id"] not in self.void:
                out.append(e)
        return out

    def spill_class(self, bbl):
        return "major" if bbl >= 25 else "reportable" if bbl >= 5 else "moderate" if bbl >= 1 else "minor"

    def repair_cost(self, asset, since, until):
        return sum(m["cost_usd"]["total"] for m in self.mnt[asset] if since <= m["started_at"][:10] <= until)

    def containment_hours(self, inspection_id):
        """From the repair report's Compliance-check line, not from any index."""
        asset = "WELL-" + inspection_id.split("-")[1]
        for m in self.mnt[asset]:
            if m["triggered_by_inspection_id"] == inspection_id and m["report_file"]:
                t = (m["_dir"] / m["report_file"]).read_text(encoding="utf-8")
                r = re.search(r"Contained about (\d+(?:\.\d+)?) hours", t)
                if r:
                    return float(r.group(1))
        return None

    def slow_containment(self, area, since, until, limit=4.0):
        out = {}
        for a, w in self.wells.items():
            if w["area_id"] == area:
                for s in self.spills(a, since, until):
                    h = self.containment_hours(s["inspection_id"])
                    if h is not None and h > limit:
                        out[a] = (s["inspection_id"], h)
        return out

    def breaches(self, asset, since, until):
        """Protocol breaches for one well from raw regulator events + reports (SR-01/02/03, RC-04), deadlines per the SOPs."""
        out, now = set(), date.fromisoformat(self.as_of) + timedelta(days=1)
        for s in self.spills(asset, since, until):
            iid, found = s["inspection_id"], date.fromisoformat(s["inspected_at"][:10])
            cls = self.spill_class(s["spill_est_volume_bbl"])
            evs = [e for e in self.reg[asset] if e["related_inspection_id"] == iid]
            if cls in ("reportable", "major"):
                limit = 2 if cls == "major" else 24
                filed = [e for e in evs if e["event_type"] == "spill_report_filed"]
                if (filed and filed[0]["hours_to_report"] > limit) or (not filed and s["inspected_at"][:10] < str(now - timedelta(days=1 + limit // 24))):
                    out.add("SR-01")
                if not any(e["protocol_id"] == "SR-03" and e["status"] == "closed" for e in evs) and found + timedelta(days=60) < now:
                    out.add("SR-03")
            h = self.containment_hours(iid)
            if h is not None and h > 4:
                out.add("SR-02")
        for n in self.reg[asset]:
            if n["event_type"] == "notice_of_violation" and since <= n["date"] <= until:
                resp = [e for e in self.reg[asset] if e["event_type"] == "nov_response_filed" and e["related_inspection_id"] == n["related_inspection_id"]]
                if date.fromisoformat(n["date"]) + timedelta(days=30) < now and (not resp or resp[0]["date"] > str(date.fromisoformat(n["date"]) + timedelta(days=30))):
                    out.add("RC-04")
        return out

    def spills_by_area_month(self, year):
        grid = {}
        for a, w in self.wells.items():
            for s in self.spills(a, f"{year}-01-01", f"{year}-12-31"):
                key = (self.areas[w["area_id"]]["name"], int(s["inspected_at"][5:7]))
                grid[key] = grid.get(key, 0) + 1
        return grid

    def not_producing_now(self, area):
        out = {}
        for a, w in self.wells.items():
            if w["area_id"] == area:
                i = max(self.ins[a], key=lambda x: x["inspected_at"])
                if not self.producing(a, i):
                    e = self._eff(i)
                    out[a] = round(e["wellhead_temp_c"] - e["ambient_temp_c"], 1)
        return out

    def rca_wells(self, area, kind, count_by_type=None):
        """Wells with >= N corrective repairs of one equipment kind in the 12 months to as_of (N per well type)."""
        count_by_type = count_by_type or {}
        since, out = self.months_back(12), {}
        for a, w in self.wells.items():
            if w["area_id"] == area:
                n = sum(1 for m in self.mnt[a] if m["maintenance_type"] == "corrective" and m["equipment_kind"] == kind
                        and since <= m["started_at"][:10] <= self.as_of)
                if n >= count_by_type.get(w["well_type"], 3):
                    out[a] = n
        return out


if __name__ == "__main__":  # self-check against the answers published in 03-evaluation-queries.md
    O = Oracle(Path(__file__).resolve().parents[2] / "sample-data")
    assert O.as_of == "2026-10-16"
    s = O.spills("WELL-0001", O.months_back(48), O.as_of)
    assert len(s) == 6 and round(sum(x["spill_est_volume_bbl"] for x in s), 1) == 15.1
    assert O.downtime("WELL-0001", "2025-01-01", "2025-12-31") == 21
    d = O.downtime_by_well("NE-07", O.months_back(4), O.as_of)
    assert sorted(d.values())[-3:] == [42, 42, 49] and d["WELL-0121"] == 49 and d["WELL-0119"] == 28
    assert {a: h for a, (_, h) in O.slow_containment("SW-24", O.days_back(90), O.as_of).items()} == {"WELL-0082": 7.1, "WELL-0100": 8.1}
    assert [round(O.repair_cost(w, "2026-01-01", O.as_of)) for w in ("WELL-0121", "WELL-0138", "WELL-0107")] == [25794, 46942, 5176]
    assert O.not_producing_now("NE-08") == {"WELL-0164": 4.1, "WELL-0170": 2.9, "WELL-0172": 5.7, "WELL-0175": 0.4}
    assert sorted(O.rca_wells("NE-07", "pump_jack")) == ["WELL-0108", "WELL-0121", "WELL-0138"]
    assert sorted(O.rca_wells("NE-07", "pump_jack", {"T350": 2})) == ["WELL-0108", "WELL-0120", "WELL-0121", "WELL-0138"]
    assert O.breaches("WELL-0001", O.months_back(12), O.as_of) == {"SR-01", "SR-02", "SR-03", "RC-04"}
    g = O.spills_by_area_month(2026)
    assert sum(v for (a, _), v in g.items() if a == "Southwest Block 24") == 43
    print("oracle OK: Q4 Q5 Q6 Q8 Q10 Q11 Q2 Q14 reproduced from raw files")
