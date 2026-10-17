"""HTTP API checks on a throw-away DB copy, with a scripted fake LLM so the chat path is tested offline.
   py -m copilot.eval.run_api"""
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

from copilot import tools

tools.clean_copy()  # throw-away copy with no runtime data, whatever was done in the UI
from copilot import agent, server  # noqa: E402  (after the DB redirect)
from copilot.eval.oracle import Oracle  # noqa: E402

srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
M, J = "U-201", "U-202"


def call(path, user=None, body=None, day=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={**({"X-User-Id": user} if user else {}), **({"X-Field-Date": day} if day else {}), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def call_method(method, path, user=None):
    req = urllib.request.Request(BASE + path, method=method, headers={**({"X-User-Id": user} if user else {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def get(path, user=None):
    st, js = call(path, user)
    assert st == 200, (path, st, js)
    return js


def ok(name):
    print("PASS", name)


# ---- read endpoints vs independent values
O = Oracle(Path(__file__).resolve().parents[2] / "sample-data")
m = get("/api/meta")
assert m["as_of"] == "2026-10-16" and m["counts"]["wells"] == 200 and m["counts"]["inspections"] == 39567, m
assert len(get("/api/users")) == 15 and {a["wells"] for a in get("/api/areas")} == {50}
ok("meta, users, areas")

c = get("/api/wells/WELL-0001")["view"]
assert c["type"] == "card" and c["kind"] == "well" and not c["producing"] and c["metrics"][0]["value"] == "3.2 °C", c
assert c["facts"][1]["flag"] and any(n["id"] == "CTX-0001-003" for n in c["notes"]), c
ok("well card (Q1)")

w = get("/api/wells?area=NE-08&producing=false")
assert {r["asset_id"] for r in w["rows"]} == set(O.not_producing_now("NE-08")) and w["view"]["type"] == "table", w["view"]["type"]
assert all(isinstance(v, (str, int, float)) for r in w["view"]["rows"] for v in r.values()), "table cells must be flat"
why = {r["asset_id"]: r["reason"] for r in w["view"]["rows"]}
assert [c["label"] for c in w["view"]["columns"]][:3] == ["Well", "Type", "Status"] and "inspection_id" not in {c["key"] for c in w["view"]["columns"]}
assert why["WELL-0164"] == "none recorded" and "MNT-0170-031" in why["WELL-0170"] and "MNT-0172-028" in why["WELL-0172"], why
ok("not-producing table (Q2) and flat cells")

b = get("/api/downtime?area=NE-07&top=3&months=4")["view"]
assert b["type"] == "bar" and {i["label"]: i["value"] for i in b["items"]} == {"WELL-0121": 49, "WELL-0107": 42, "WELL-0138": 42}, b
ok("downtime bar (Q6)")

p = get("/api/spills?area=NE-08&days=90")["view"]
assert p["type"] == "map" and {x["id"] for x in p["pins"]} == {"WELL-0151", "WELL-0165", "WELL-0175", "WELL-0186"}, p
assert next(x for x in p["pins"] if x["id"] == "WELL-0151")["lat"] == 32.12246
ok("spill map (Q7)")

hm = get("/api/spills/heatmap?year=2026")["view"]
assert hm["type"] == "heatmap" and dict(zip(hm["rows"], hm["totals"])) == {"Southwest Block 23": 35, "Southwest Block 24": 43, "Northeast Block 7": 37, "Northeast Block 8": 26}, hm
ok("spill heatmap (Q8)")

comp = get("/api/compliance?area=SW-23&months=12")
assert {r["protocol_id"] for r in comp["rows"] if r["asset_id"] == "WELL-0001" and r["status"] == "breach"} == O.breaches("WELL-0001", O.months_back(12), O.as_of)
ok("compliance (Q9) equals the oracle")

ln = get("/api/wells/WELL-0001/series?weeks=13")["view"]
assert ln["type"] == "line" and len(ln["points"]) == 13 and [p["date"] for p in ln["points"] if not p["producing"]] == ["2026-10-08", "2026-10-15"], ln
ok("temperature line (Q3)")

ov = get("/api/overview")
now = [not O.producing(a, max(O.ins[a], key=lambda x: x["inspected_at"])) for a in O.wells]
assert ov["cards"][0]["value"] == f"{200 - sum(now)}/200" and len(ov["cards"]) == 4, ov["cards"][0]
ok("overview equals the oracle")

rl = {(r["scope_value"], r["key"]): r["value"] for r in get("/api/rules")}
assert rl[("T200", "producing_delta_c")] == 15 and rl[("T350", "producing_delta_c")] == 20
ok("rules")

ev = lambda i: get("/api/evidence/" + urllib.request.quote(i, safe=""))
assert "3.2" in ev("INS-0001-0203")["snippet"] and "Root cause" in ev("MNT-0001-029")["snippet"]
assert "5,000" in ev("REG-0001-002")["snippet"] and "Jake Morales" in ev("CTX-0001-003")["snippet"]
assert ev("sop:spill-response-sop:4")["kind"] == "sop" and ev("rule:T350:producing_delta_c")["snippet"].startswith("producing_delta_c = 20")
assert call("/api/evidence/INS-9999-9999")[0] == 404
ok("evidence cards")

assert {x["type"] for x in get("/api/logs?limit=30")} <= {"Info", "Warning", "Critical", "Resolved"} and len(get("/api/logs")) > 5
ok("logs")

# ---- chat path with a scripted LLM
script = []


def fake_llm(messages, key, model=None, with_tools=True):
    return script.pop(0)


def tool_call(name, args):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": "t1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


agent.call_llm = fake_llm
assert call("/api/chat", None, {"message": "hi"})[0] == 401 and call("/api/chat", "U-999", {"message": "hi"})[0] == 401
assert call("/api/chat", M, {"message": "  "})[0] == 400 and call("/api/overview?area=XX-00")[0] == 400
script[:] = [tool_call("downtime", {"area_id": "NE-07", "top_n": 3, "last_months": 4}),
             {"role": "assistant", "content": "<thought>x</thought>Top 3: WELL-0121 49 days [INS-0121-0189]."}]
st, r = call("/api/chat", M, {"message": "Which 3 wells in Northeast Block 7 had the most downtime in the last 4 months? Show a bar chart."}, day="2026-10-15")
assert st == 200 and r["visual"] == "bar" and r["view"]["type"] == "bar" and "<thought>" not in r["text"], r
assert r["steps"][0]["tool"] == "downtime" and "INS-0121-0189" in r["evidence"], r
chat_id = r["chat_id"]
assert get("/api/chats", M)[0]["chat_id"] == chat_id and get("/api/chats", J) == []
msgs = get(f"/api/chats/{chat_id}", M)["messages"]
assert [x["role"] for x in msgs] == ["user", "assistant"] and msgs[1]["payload"]["view"]["type"] == "bar", msgs
assert call(f"/api/chats/{chat_id}", J)[0] == 404, "another user's chat must not be readable"
ok("chat: view, persistence, steps, privacy of chat ids")

def two_calls(*calls):
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": f"t{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}} for i, (n, a) in enumerate(calls)]}


def visuals_of(question, *llm_script):
    script[:] = list(llm_script) + [{"role": "assistant", "content": "ok"}]
    st, r = call("/api/chat", M, {"message": question})
    assert st == 200, (st, r)
    return r


# ---- Phase 2: several visuals per answer
from copilot import agent as _agent  # noqa: E402
from copilot import present  # noqa: E402

assert _agent.named_visuals("Show it as a table and on a map") == ["table", "map"]
assert _agent.named_visuals("Show a heat map of spills") == ["heatmap"] and _agent.named_visuals("a bar chart then a table") == ["bar", "table"]
assert _agent.named_visuals("Which wells are not producing?") == []
ok("named visuals: all of them, in the order asked, 'heat map' is not also a map")

r = visuals_of("Is WELL-0001 producing oil right now? Show me its status card.", tool_call("well_status", {"well_id": "WELL-0001"}))
assert [v["type"] for v in r["visuals"]] == ["card", "line"] and [v["source"] for v in r["visuals"]] == ["primary", "companion"], r["visuals"]
assert r["visuals"][1]["title"] == "Wellhead vs air temperature" and "WELL-0001" in r["visuals"][1]["caption"] and r["view"] == r["visuals"][0]["view"]
ok("well status card gets its 13-week temperature line as a companion")

r = visuals_of("Which wells in Northeast Block 8 are not producing? Show them in a table and on a map.", tool_call("find_wells", {"producing": False, "area_id": "NE-08"}))
assert [v["type"] for v in r["visuals"]] == ["table", "map"], r["visuals"]
pins = r["visuals"][1]["view"]["pins"]
assert {p["id"] for p in pins} == {"WELL-0164", "WELL-0170", "WELL-0172", "WELL-0175"} and all(p["lat"] for p in pins), pins
ok("'table and a map' from one tool call: the map is built from the wells' coordinates")

r = visuals_of("Top 3 downtime in Northeast Block 7, bar chart", tool_call("downtime", {"area_id": "NE-07", "top_n": 3, "last_months": 4}))
assert [v["type"] for v in r["visuals"]] == ["bar", "table"] and r["visuals"][0]["caption"].startswith("Northeast Block 7 · 16 Jun 2026"), r["visuals"]
assert [row["days down"] for row in r["visuals"][1]["view"]["rows"]] == [49, 42, 42]
ok("a named bar chart still gets its data table; captions carry area and window")

r = visuals_of("Which wells in NE-07 had the most downtime, and where were the spills?",
               two_calls(("downtime", {"area_id": "NE-07", "top_n": 3, "last_months": 4}), ("spills", {"area_id": "NE-07", "last_days": 90})))
types = [v["type"] for v in r["visuals"]]
assert len(types) <= 4 and {"bar", "map", "table"} <= set(types) and len({json.dumps(v["view"], sort_keys=True) for v in r["visuals"]}) == len(types), r["visuals"]
assert [v["source"] for v in r["visuals"]][0] == "primary" and "tool" in [v["source"] for v in r["visuals"]]
ok("two tool calls -> both shown, capped at four, no duplicates")

r = visuals_of("Show a heatmap of 2026 spills by geographic area and month.", tool_call("spills", {"group_by": "area_month", "since": "2026-01-01"}))
assert [v["type"] for v in r["visuals"]] == ["heatmap"], r["visuals"]
r = visuals_of("How many days was WELL-0001 down in 2025?", tool_call("downtime", {"well_id": "WELL-0001", "since": "2025-01-01", "until": "2025-12-31"}))
assert r["visuals"] == [] and r["view"] is None and r["visual"] == "text", r
ok("a heatmap stays alone; a one-number answer has no component")

assert present.compose([], [], "table") == [] and len(present.compose(["table", "map", "bar", "line", "heatmap"], [
    {"tool": "downtime", "args": {"area_id": "NE-07"}, "window": None, "visual": "bar", "rows": [{"key": f"WELL-{i:04d}", "days": i, "weeks": 1} for i in range(1, 4)]}], "table")) <= 4
ok("compose: empty input and the four-visual cap")

assert call_method("DELETE", f"/api/chats/{chat_id}", J)[0] == 404, "another user must not be able to delete this chat"
assert get(f"/api/chats/{chat_id}", M)["messages"], "the failed delete must not have removed anything"
script[:] = [tool_call("downtime", {"area_id": "NE-07", "top_n": 3, "last_months": 4}), {"role": "assistant", "content": "ok"}]
st, tmp_chat = call("/api/chat", M, {"message": "temporary chat"})
assert st == 200
assert call_method("DELETE", f"/api/chats/{tmp_chat['chat_id']}", M)[0] == 200 and call(f"/api/chats/{tmp_chat['chat_id']}", M)[0] == 404
assert chat_id in {c["chat_id"] for c in get("/api/chats", M)} and tmp_chat["chat_id"] not in {c["chat_id"] for c in get("/api/chats", M)}
ok("delete chat: owner only, history updated")

script[:] = [tool_call("recall", {"days_ago": 1}), {"role": "assistant", "content": "You discussed WELL-0121, WELL-0107 and WELL-0138."}]
st, r = call("/api/chat", M, {"message": "For the three wells we discussed yesterday, what have repairs cost this year?"})
assert st == 200 and sorted(r["rows"][0]["well_ids"]) == ["WELL-0107", "WELL-0121", "WELL-0138"], r["rows"]
script[:] = [tool_call("recall", {"days_ago": 1}), {"role": "assistant", "content": "I have no earlier conversation with you."}]
st, r = call("/api/chat", J, {"message": "For the three wells we discussed yesterday, what have repairs cost this year?"})
assert st == 200 and r["rows"] == [] and "WELL-0121" not in r["text"], r
ok("memory: Michael recalls yesterday via the simulated field date; Jessica gets nothing")

script[:] = [tool_call("correct_value", {"field": "wellhead_temp_c", "value": 41.0, "reason": "re-measured", "well_id": "WELL-0164"}),
             {"role": "assistant", "content": "Recorded; original 24.0 kept."}]
st, r = call("/api/chat", M, {"message": "The 15 Oct reading for WELL-0164 is wrong, the real value is 41.0."})
assert st == 200 and r["view"]["type"] == "card"
assert "WELL-0164" not in {x["asset_id"] for x in get("/api/wells?area=NE-08&producing=false")["rows"]}, "dashboard must reflect the correction"
assert any("Michael Turner" in x["title"] for x in get("/api/logs?limit=20")), "correction must appear in the audit log"
ok("correction through chat updates the dashboard and the audit log")


def boom(*a, **k):
    raise urllib.error.URLError("rate limited")


# a change was recorded, then the model stops answering: the user must be told, not get an error that loses the confirmation
calls = []


def flaky(messages, key, model=None, with_tools=True):
    calls.append(1)
    if len(calls) == 1:
        return tool_call("correct_value", {"field": "wellhead_temp_c", "value": 40.0, "reason": "re-measured", "well_id": "WELL-0164"})
    raise TimeoutError("timed out")


agent.call_llm = flaky
st, r = call("/api/chat", M, {"message": "The reading for WELL-0164 is really 40.0"})
assert st == 200 and "did not answer in time" in r["text"] and r["steps"][0]["tool"] == "correct_value", (st, r)
assert "change you asked for was recorded" in r["text"], r["text"]
calls.clear()


def flaky_read(messages, key, model=None, with_tools=True):
    calls.append(1)
    if len(calls) == 1:
        return tool_call("find_wells", {"producing": False, "area_id": "NE-08"})
    raise TimeoutError("timed out")


agent.call_llm = flaky_read
st, r = call("/api/chat", M, {"message": "Which wells in NE-08 are not producing? Show a table and a map."})
assert st == 200 and "results are shown below" in r["text"] and "recorded" not in r["text"] and [v["type"] for v in r["visuals"]] == ["table", "map"], (st, r)
agent.call_llm = flaky
assert get("/api/chats", M)[0]["turns"] >= 2, "the fallback answer must be stored in the chat"
ok("model fails after a recorded change -> explicit message, change kept, turn stored")


agent.call_llm = boom
st, r = call("/api/chat", M, {"message": "anything"})
assert st == 502 and "rate-limited" in r["error"], (st, r)
ok("LLM failure -> 502 JSON")
srv.shutdown()
