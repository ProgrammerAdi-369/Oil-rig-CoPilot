"""Reliability checks for the router -> tools -> narrator path and the LLM gateway. No network, no key.
   py -m copilot.eval.run_engine"""
import time
import urllib.error

from copilot import tools

tools.clean_copy()  # throw-away DB copy
from copilot import agent, llm, router  # noqa: E402


def ok(name):
    print("ok -", name)


# ---- router: the 18 sample questions pick the right tool; statements and unclear phrasing return None
ROUTES = {
    "Is WELL-0001 producing oil right now? Show me its status card.": ["well_status"],
    "Which wells in Northeast Block 8 are not producing oil right now, and why?": ["find_wells"],
    "Show a line chart of WELL-0001's wellhead temperature against air temperature for the last 13 weeks": ["series"],
    "How many oil spills has WELL-0001 had in the last 4 years?": ["spills"],
    "How many days was WELL-0001 down in 2025?": ["downtime"],
    "Which 3 wells in Northeast Block 7 had the most downtime in the last 4 months?": ["downtime"],
    "Show a heatmap of 2026 spills by geographic area and month.": ["spills"],
    "Which rules has WELL-0001 broken in the last 12 months, and what is still open?": ["compliance"],
    "In Southwest Block 24, which spills in the last 90 days were not contained within the SOP time limit?": ["compliance"],
    "For the three wells we discussed yesterday, what have repairs cost this year?": ["recall", "repairs"],
    "Which wells in Northeast Block 7 need a root-cause analysis on their pump jack?": ["rca_candidates"],
    "Which spills in Northeast Block 8 in the last 90 days needed a report to the regulator?": ["spills"],
    "Is any downtime planned for WELL-0007?": ["well_status"],
}
for question, expected in ROUTES.items():
    assert [s["tool"] for s in router.route(question) or []] == expected, question
for statement in ("The 15 Oct reading for WELL-0164 is wrong.", "WELL-0175 is running fine.", "FYI for everyone: WELL-0007 will be shut in from 17 Oct.",
                  "Note for all T350 wells: our team now wants a pump jack root-cause analysis after 2 repairs.",
                  "Was the 20 Aug spill at WELL-0101 real oil?", "How many spills since 1 Nov 2026?", "What is the reservoir pressure?"):
    assert router.route(statement) is None, statement
plan = router.route("Which 3 wells in Northeast Block 7 had the most downtime in the last 4 months?")[0]["args"]
assert plan == {"group_by": "well", "area_id": "NE-07", "last_months": 4, "top_n": 3}, plan
ok("router: 13 questions routed to the right tool and arguments, 7 statements/unclear phrasings left to the LLM")

# ---- gateway: breaker, cache, fallback model, polish
calls = []


def failing(model, messages, key, schemas, end):
    calls.append(model)
    raise urllib.error.URLError("429")


llm._post = failing
llm._state.update(fails=0, open_until=0.0)
for _ in range(2):
    try:
        llm.call([{"role": "user", "content": "x"}], "k")
        raise AssertionError("should fail")
    except urllib.error.URLError:
        pass
assert len(calls) == 4 and calls[0] != calls[1], calls  # each failed call tried primary then fallback model
n = len(calls)
try:
    llm.call([{"role": "user", "content": "y"}], "k")
    raise AssertionError("breaker should be open")
except llm.Unavailable:
    assert len(calls) == n, "an open breaker must not call the model"
ok("gateway: 2 failures open the breaker, fallback model tried, no call while open")

llm._state.update(fails=0, open_until=0.0)
reply = {"role": "assistant", "content": "answer"}
llm._post = lambda *a: calls.append("m") or reply
calls.clear()
assert llm.call([{"role": "user", "content": "same"}], "k") == reply and llm.call([{"role": "user", "content": "same"}], "k") == reply
assert len(calls) == 1, "second identical prompt must come from the cache"
ok("gateway: identical prompt served from the cache")

import os  # noqa: E402

os.environ["LLM_POLISH"] = "1"  # polish is opt-in; the checks below exercise it
text = "WELL-0121 was down 49 days [INS-0121-0189]."
for out, kept in (("WELL-0121 lost 49 days of production [INS-0121-0189].", True), ("WELL-0121 was down about 50 days.", False)):
    llm._post = lambda *a, out=out: {"role": "assistant", "content": out}
    llm._state.update(fails=0, open_until=0.0)
    tools.db().execute("DELETE FROM llm_cache")
    got = llm.polish(text, "k")
    assert (got == out) is kept, (out, got)
ok("gateway: polish accepted only when every number and ID survives")

# ---- ask(): deterministic answers when the model is down; help text, not an exception, for the rest
agent.call_llm = lambda *a, **k: (_ for _ in ()).throw(llm.Unavailable("down"))
llm._state.update(fails=0, open_until=time.time() + 600)  # breaker open: polish is skipped too
t0 = time.time()
out = agent.ask("Which 3 wells in Northeast Block 7 had the most downtime in the last 4 months? Show a bar chart.", "U-201", key="k")
assert "WELL-0121" in out["text"] and "49 days" in out["text"] and out["visual"] == "bar" and out["trace"][0]["tool"] == "downtime", out["text"]
assert time.time() - t0 < 2, "deterministic answer must not wait on the model"
out = agent.ask("Is WELL-0164 producing oil right now?", "U-201", key="k")
assert "NOT producing" in out["text"] and "INS-0164-0205" in out["evidence"], out["text"]
out = agent.ask("The reading for WELL-0164 is wrong, it is really 41.", "U-201", key="k")
assert "could not map" in out["text"] and out["trace"] == [], out
ok("ask: routable questions answered with the model down, others get the help text")

agent.USE_ROUTER = False
try:
    agent.ask("Which wells are not producing?", "U-201", key="k")
    raise AssertionError("with the router off the model failure must propagate")
except llm.Unavailable:
    pass
ok("ask: router off -> old behaviour (model failure raised)")
