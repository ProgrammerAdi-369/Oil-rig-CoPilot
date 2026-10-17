"""All 18 example questions through the real LLM, in the order of 03-evaluation-queries.md, on a throw-away DB copy.
   py -m copilot.eval.run_agent [--no-llm] [Q-number ...]   Prints each answer and which expected markers it contains.
   --no-llm removes the model key, so only the rule-based router and templates answer (questions it can't route fail)."""
import json
import os
import sys
from pathlib import Path

from copilot import tools

tools.clean_copy()  # throw-away copy with no runtime data, whatever was done in the UI
from copilot import agent  # noqa: E402

if "--no-llm" in sys.argv:
    sys.argv.remove("--no-llm")
    for k in ("LLM_API_KEY", "GEMINI_API_KEY"):
        os.environ.pop(k, None)

M, J, T, JK, L = "U-201", "U-202", "U-204", "U-102", "U-401"
D1, D2 = "2026-10-15T10:00:00Z", "2026-10-16T10:00:00Z"
Q6 = "Which 3 wells in Northeast Block 7 had the most downtime in the last 4 months? Show a bar chart."
Q2 = "Which wells in Northeast Block 8 are not producing oil right now, and why? Show them in a table."
Q14 = "Which wells in Northeast Block 7 need a root-cause analysis on their pump jack?"
# (number, user, ts, question, markers that must appear in answer text or returned rows, markers that must NOT appear)
STEPS = [
    (1, M, D2, "Is WELL-0001 producing oil right now? When was it last inspected, and by whom? Show me its status card.",
     ["not producing", "Ryan Brooks", "INS-0001-0203", "CTX-0001-003", "3.2"], []),
    (2, M, D2, Q2, ["0164", "0170", "0172", "0175", "4.1", "2.9", "5.7", "0.4"], []),
    (3, M, D2, "Show a line chart of WELL-0001's wellhead temperature against air temperature for the last 13 weeks, and mark when it was not producing oil.",
     ["2026-10-08", "2026-10-15"], []),
    (4, M, D2, "How many oil spills has WELL-0001 had in the last 4 years, and how much oil in total? List them in a table.", ["6", "15.1"], []),
    (5, M, D2, "How many days was WELL-0001 down in 2025?", ["21"], []),
    (6, M, D2, Q6, ["0121", "49", "0138", "0107", "42"], []),
    (7, M, D2, "Show on a map every well in Northeast Block 8 with a real spill in the last 90 days.", ["0151", "0165", "0175", "0186"], []),
    (8, M, D2, "Show a heatmap of 2026 spills by geographic area and month.", ["43", "35", "37", "26"], []),
    (9, M, D2, "Which rules has WELL-0001 broken in the last 12 months, and what is still open?",
     ["SR-01", "SR-02", "SR-03", "RC-04", "5,000"], []),
    (10, M, D2, "In Southwest Block 24, which spills in the last 90 days were not contained within the SOP time limit?", ["0082", "7.1", "0100", "8.1"], []),
    # Q11: day 1 Michael asks Q6, day 2 (new chat) asks the follow-up
    (11, M, D1, Q6, ["0121"], []),
    (11, M, D2, "For the three wells we discussed yesterday, what have repairs cost this year?", ["25,794", "46,942", "5,176"], []),
    (12, M, D2, "The 15 Oct reading for WELL-0164 is wrong. The handheld thermal gun used in that inspection was faulty; the field crew re-measured the wellhead at 41.0 °C.",
     ["INS-0164-0205", "24", "41", "producing", "Pump jack not moving"], []),
    (12, M, D2, Q2, ["0170", "0172", "0175"], []),
    (13, M, D2, "The AI estimated the 24 Sep spill at WELL-0151 as 4.5 bbl. The field crew measured 5.4 bbl.",
     ["INS-0151-0201", "5.4", "SR-01", "SR-03", "2026-11-23"], []),
    (14, M, D2, Q14, ["0108", "0121", "0138"], ["0120"]),
    (14, M, D2, "Note for all T350 wells: our team now wants a pump jack root-cause analysis after 2 repairs, not 3.", ["T350", "2"], []),
    (14, M, D2, Q14, ["0108", "0120", "0121", "0138", "Michael"], ["0102"]),
    (15, J, D2, "Is WELL-0164 producing oil right now?", ["41", "Michael Turner", "Pump jack not moving"], []),
    (15, L, D2, "Which spills in Northeast Block 8 in the last 90 days needed a report to the regulator?", ["0151", "5.4"], ["0165", "0186"]),
    (16, JK, D2, "FYI for everyone: WELL-0007 will be shut in from 17 Oct for a 10-day planned workover.", ["WELL-0007", "17"], []),
    (16, M, D2, "Is any downtime planned for WELL-0007?", ["17", "Jake Morales"], []),
    (16, J, D2, "For the three wells we discussed yesterday, what have repairs cost this year?", [], ["25,794", "46,942", "5,176"]),
    (17, M, D2, "WELL-0175 has been shut in for planned work since 14 Oct.", ["WELL-0175"], []),
    (17, T, D2, "WELL-0175 is running fine.", ["0.4", "Michael Turner", "unconfirmed"], []),
    (17, JK, D2, "WELL-0001 is back online since 14 Oct.", ["CTX-0001-003", "20 Oct", "unconfirmed"], []),
    (18, L, D2, "Was the 20 Aug spill at WELL-0101 real oil?", ["Ryan Brooks", "Chris Dalton", "CTX-0101-002", "CTX-0101-003"], []),
]


def main(only, md_path=None):
    names = {u["user_id"]: u["name"] for u in tools.q("SELECT user_id, name FROM users")}
    entries = []
    for n, user, ts, question, must, must_not in STEPS:
        if only and n not in only:
            continue
        try:
            out = agent.ask(question, user, ts=ts)
        except Exception as e:
            print(f"\n=== Q{n} [{user}] ERROR {type(e).__name__}: {e}")
            entries.append((n, user, ts, question, None, f"ERROR {type(e).__name__}: {e}"))
            continue
        blob = (out["text"] + json.dumps(out["rows"], default=str) + " ".join(out["evidence"])).lower()
        missing = [m for m in must if m.lower() not in blob]
        leaked = [m for m in must_not if m.lower() in out["text"].lower()]
        verdict = "OK" if not missing and not leaked else f"missing={missing} unexpected={leaked}"
        print(f"\n=== Q{n} [{user}] {question}\n[{out['visual']}] {out['text']}\nevidence: {', '.join(out['evidence'][:10])}")
        print("CHECK:", verdict)
        entries.append((n, user, ts, question, out, verdict))
    if md_path:
        write_md(md_path, entries, names)


def write_md(path, entries, names):
    ok = sum(1 for e in entries if e[5] == "OK")
    lines = [f"# Question & answer log — all 18 example questions through {agent.MODEL}", "",
             f"Generated by `py -m copilot.eval.run_agent --md`. Model: `{agent.MODEL}` via the Google AI Studio OpenAI-compatible endpoint. "
             f"Data \"today\": {tools.as_of()}. Each step ran on a throw-away copy of the database in the order of `03-evaluation-queries.md`, "
             "so later steps see the corrections and notes made by earlier ones.", "",
             f"Automatic marker check: **{ok} of {len(entries)} steps** contain every expected fact (plain string match against the answer, returned rows "
             "and cited records, so it is a screen and not a grade — read the answers).", "",
             "| Step | User | Check |", "|---|---|---|"]
    lines += [f"| Q{n} | {names.get(u, u)} | {'✅' if v == 'OK' else '⚠️ ' + v} |" for n, u, _, _, _, v in entries]
    for n, user, ts, question, out, verdict in entries:
        lines += ["", "---", "", f"## Q{n} — asked by {names.get(user, user)}", "", f"> {question}", ""]
        if out is None:
            lines += [f"**{verdict}**"]
            continue
        lines += [f"**Visual shown:** `{out['visual']}`", "", out["text"], "",
                  f"**Evidence cited:** {', '.join(out['evidence']) or '—'}", "",
                  f"**Marker check:** {'✅ all expected facts present' if verdict == 'OK' else '⚠️ ' + verdict}"]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", path)


if __name__ == "__main__":
    args = sys.argv[1:]
    md = None
    if "--md" in args:
        i = args.index("--md")
        md = args[i + 1] if i + 1 < len(args) and not args[i + 1].isdigit() else str(Path(__file__).resolve().parents[2] / "Docs" / "QNA.md")
        args = [a for j, a in enumerate(args) if j != i and not (j == i + 1 and a == md)]
    main({int(a) for a in args}, md)
