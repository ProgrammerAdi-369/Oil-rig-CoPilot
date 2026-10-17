"""Expected answers from 03-evaluation-queries.md as data. One entry per session step, in benchmark order.
  must      facts that must appear in the answer text, the returned rows or the cited records; a tuple = alternatives.
            Numbers compare with commas/$ stripped, so 5000 == 5,000 == $5,000.
  must_not  strings that must not appear in the answer text (scope / privacy leaks).
  wells_only  WELL ids the answer may mention (text + rows); anything else is a wrong-scope answer.
  visual    allowed visuals when the question names none (a visual named in the question always wins).
  behaviours  named checks implemented in critic.py: (name, *params); a trailing '?' marks an advisory (minor) check.
  oracle    name of an independent recomputation in critic.py (None = not applicable).
  depends   steps that must have run for this one to be meaningful (an ERROR there => SKIPPED here)."""

D1, D2 = "2026-10-15T10:00:00Z", "2026-10-16T10:00:00Z"
M, J, T, JK, L = "U-201", "U-202", "U-204", "U-102", "U-401"
Q6 = "Which 3 wells in Northeast Block 7 had the most downtime in the last 4 months? Show a bar chart."
Q2 = "Which wells in Northeast Block 8 are not producing oil right now, and why? Show them in a table."
Q14 = "Which wells in Northeast Block 7 need a root-cause analysis on their pump jack?"
TOP3 = ["WELL-0121", "WELL-0138", "WELL-0107"]


def g(key, user, question, ts=D2, must=(), must_not=(), visual=None, evidence=(), behaviours=(), oracle=None, depends=(),
      wells_only=None):
    return dict(key=key, q=int("".join(c for c in key[1:3] if c.isdigit())), user=user, ts=ts, question=question, must=list(must),
                must_not=list(must_not), visual=set(visual or []), evidence=list(evidence), behaviours=list(behaviours),
                oracle=oracle, depends=list(depends), wells_only=wells_only)


GOLDEN = [
    g("Q1", M, "Is WELL-0001 producing oil right now? When was it last inspected, and by whom? Show me its status card.",
      must=[("not producing", "isn't producing", "not currently producing"), "Ryan Brooks", ("2026-10-15", "15 Oct"), "3.2",
            "INS-0001-0203", "CTX-0001-003", ("2026-10-20", "20 Oct")],
      visual={"card"}, evidence=["INS-0001-0203", "CTX-0001-003"], behaviours=[("stale_status",)], oracle="q1_status"),
    g("Q2", M, Q2, must=["WELL-0164", "WELL-0170", "WELL-0172", "WELL-0175", "4.1", "2.9", "5.7", "0.4", "MNT-0170-031", "MNT-0172-028"],
      visual={"table"}, wells_only={"WELL-0164", "WELL-0170", "WELL-0172", "WELL-0175"},
      behaviours=[("stale_status",), ("no_recorded_reason", "WELL-0164", "WELL-0175"), ("no_invented_cause", "WELL-0164", "WELL-0175")],
      oracle="q2_not_producing"),
    g("Q3", M, "Show a line chart of WELL-0001's wellhead temperature against air temperature for the last 13 weeks, and mark when it was not producing oil.",
      must=[("2026-10-08", "8 Oct"), ("2026-10-15", "15 Oct")], visual={"line"}, oracle="q3_series"),
    g("Q4", M, "How many oil spills has WELL-0001 had in the last 4 years, and how much oil in total? List them in a table.",
      must=[("6 oil spills", "6 spills", "six spills", "6 detected"), "15.1"], visual={"table"}, evidence=["INS-0001-0185"],
      oracle="q4_spills"),
    g("Q5", M, "How many days was WELL-0001 down in 2025?", must=["21"], visual={"text"}, oracle="q5_downtime"),
    g("Q6", M, Q6, must=[*TOP3, "49", "42"], visual={"bar"}, wells_only=set(TOP3), oracle="q6_top3"),
    g("Q7", M, "Show on a map every well in Northeast Block 8 with a real spill in the last 90 days.",
      must=["WELL-0151", "WELL-0165", "WELL-0175", "WELL-0186", "4.5", "1.2", "3.9", "0.6"], visual={"map"},
      wells_only={"WELL-0151", "WELL-0165", "WELL-0175", "WELL-0186"}, oracle="q7_spills"),
    g("Q8", M, "Show a heatmap of 2026 spills by geographic area and month.", visual={"heatmap"}, oracle="q8_heatmap"),
    g("Q9", M, "Which rules has WELL-0001 broken in the last 12 months, and what is still open?",
      must=["SR-01", "SR-02", "SR-03", "RC-04", "41", "5000", "REG-0001-001", "REG-0001-002", "REG-0001-003", "MNT-0001-029",
            ("root-cause", "root cause", "RCA")],
      visual={"table", "text"}, behaviours=[("unrecorded_shutin?",)], oracle="q9_breaches"),
    g("Q10", M, "In Southwest Block 24, which spills in the last 90 days were not contained within the SOP time limit?",
      must=["WELL-0082", "7.1", "WELL-0100", "8.1", "MNT-0082-028", "MNT-0100-034"], visual={"table"},
      wells_only={"WELL-0082", "WELL-0100"}, oracle="q10_slow"),
    g("Q11a", M, Q6, ts=D1, must=TOP3, visual={"bar"}, wells_only=set(TOP3), oracle="q6_top3"),
    g("Q11b", M, "For the three wells we discussed yesterday, what have repairs cost this year?", must=["25794", "46942", "5176"],
      visual={"table", "bar", "text"}, depends=["Q11a"], oracle="q11_costs"),
    g("Q12a", M, "The 15 Oct reading for WELL-0164 is wrong. The handheld thermal gun used in that inspection was faulty; the field crew re-measured the wellhead at 41.0 °C.",
      must=["INS-0164-0205", "24", "41"], visual={"card", "text"},
      behaviours=[("original_kept", "24"), ("now_producing",), ("conflict_surfaced", "Pump jack not moving"), ("ask_confirm",)]),
    g("Q12b", M, Q2, must=["WELL-0170", "WELL-0172", "WELL-0175"], visual={"table"}, depends=["Q12a"],
      behaviours=[("removed_well_explained", "WELL-0164", "Michael Turner")], oracle="q2_not_producing"),
    g("Q13", M, "The AI estimated the 24 Sep spill at WELL-0151 as 4.5 bbl. The field crew measured 5.4 bbl.",
      must=["INS-0151-0201", "5.4", "SR-01", "SR-03", ("2026-11-23", "23 Nov"), "MNT-0151-025", "6.4"], visual={"card", "text"},
      behaviours=[("original_kept", "4.5"), ("overdue_notice",), ("report_outdated", "MNT-0151-025")]),
    g("Q14a", M, Q14, must=["WELL-0108", "WELL-0121", "WELL-0138"], must_not=["WELL-0120", "WELL-0102"], visual={"table"},
      wells_only={"WELL-0108", "WELL-0121", "WELL-0138"}, oracle="q14_rca_manual"),
    g("Q14b", M, "Note for all T350 wells: our team now wants a pump jack root-cause analysis after 2 repairs, not 3.",
      must=["T350", "2"], visual={"text"}),
    g("Q14c", M, Q14, must=["WELL-0108", "WELL-0120", "WELL-0121", "WELL-0138", "Michael Turner"], must_not=["WELL-0102"],
      visual={"table"}, depends=["Q14b"], wells_only={"WELL-0108", "WELL-0120", "WELL-0121", "WELL-0138"},
      behaviours=[("follows_user_rule", "Michael Turner")], oracle="q14_rca_user"),
    g("Q15a", J, "Is WELL-0164 producing oil right now?", must=["41", "Michael Turner", "Pump jack not moving"],
      visual={"card", "text"}, depends=["Q12a"], behaviours=[("concludes_producing",), ("conflict_surfaced", "Pump jack not moving")]),
    g("Q15b", L, "Which spills in Northeast Block 8 in the last 90 days needed a report to the regulator?",
      must=["WELL-0151", "5.4"], visual={"table", "text"}, depends=["Q13"], behaviours=[("only_one_needs_report", "WELL-0151")]),
    g("Q16a", JK, "FYI for everyone: WELL-0007 will be shut in from 17 Oct for a 10-day planned workover.",
      must=["WELL-0007"], visual={"text", "card"}),
    g("Q16b", M, "Is any downtime planned for WELL-0007?", must=["Jake Morales", ("2026-10-17", "17 Oct"), ("10 day", "10-day", "10 days")],
      visual={"text", "card", "table"}, depends=["Q16a"]),
    g("Q16c", J, "For the three wells we discussed yesterday, what have repairs cost this year?",
      must_not=["25794", "46942", "5176", "WELL-0121", "WELL-0138", "WELL-0107"], visual={"text"},
      behaviours=[("no_prior_conversation",)]),
    g("Q17a", M, "WELL-0175 has been shut in for planned work since 14 Oct.", must=["WELL-0175"], visual={"text", "card"}),
    g("Q17b", T, "WELL-0175 is running fine.", must=["0.4", "Michael Turner", "unconfirmed"], visual={"text"}, depends=["Q17a"],
      behaviours=[("conflict_surfaced", "0.4"), ("ask_confirm",)]),
    g("Q17c", JK, "WELL-0001 is back online since 14 Oct.", must=["CTX-0001-003", ("2026-10-20", "20 Oct"), "unconfirmed"],
      visual={"text"}, behaviours=[("conflict_surfaced", "CTX-0001-003"), ("ask_confirm",)]),
    g("Q18", L, "Was the 20 Aug spill at WELL-0101 real oil?",
      must=["Ryan Brooks", "Chris Dalton", "CTX-0101-002", "CTX-0101-003", "INS-0101-0197"], visual={"text", "table"},
      behaviours=[("yes_first",), ("both_kept", "Ryan Brooks", "Chris Dalton")]),
]
