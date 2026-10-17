# QA Critic Rulebook — Asset Intelligence Copilot

The critic grades each copilot answer against the benchmark in `03-evaluation-queries.md` and against rules recomputed
independently from the raw data. Implemented in `copilot/eval/critic.py` (checks), `golden.py` (expected answers as
data) and `oracle.py` (independent recomputation from the raw JSON/JSONL/Markdown, never from `copilot.db` views).

**Design stance.** Deterministic code decides pass/fail. A small LLM judge (`gemma-4-31b-it`) is asked a yes/no rubric
question only when a regex cannot settle a semantic item, and it must quote the answer verbatim as proof; otherwise the
item is `undecided` and is reported, not failed. A model never grades its own answer as the sole authority.

---

## 1. Domain rules (hard constraints)

**R1 Derived facts**
1.1 **Producing** ⇔ `wellhead − ambient ≥ Δ`, Δ = 15 °C (T200), 20 °C (T350). Absolute temperature is never used.
1.2 **Downtime** = 7 days × inspections that found the well not producing, inside the window. Missed inspections add 0.
`maintenance.downtime_hours` is never used. Windows are inclusive, end on *today* (16 Oct 2026) unless stated, and compare by date;
repairs belong to a window by their **start** date.
1.3 **Real spill** = detected **and** not voided by a *formal correction* note. Two notes that disagree (Q18) are not a correction;
the detection stands and both notes are shown.
1.4 **Spill class:** < 1 bbl minor · 1 – < 5 moderate · 5 – < 25 **reportable** · ≥ 25 **major**.
1.5 **Deadlines and applicability**

| Protocol | Applies to | Rule | Clock starts |
|---|---|---|---|
| SR-01 | reportable, major | written notice ≤ 24 h (≤ 2 h major) | inspection time |
| SR-02 | **every** spill | contained ≤ 4 h (value is inside the repair report) | inspection time |
| SR-03 | reportable, major | clean-up verified ≤ 60 d, closed only by a passing agency inspection | inspection time |
| RC-04 | every notice of violation | answered ≤ 30 d | notice date |
| RCA | per well type | ≥ N corrective repairs on one equipment kind in 12 months (N = 3, or the user's rule for that well type) | — |

1.6 **Corrected values are the effective values.** The original must still be reported and kept (who, when, why).

**R2 Truth and no invented causes**
2.1 **Precedence:** formal corrections > latest inspection > active notes (they explain *why*) > `recorded_status` (stale by design).
A user claim ("running fine") never overrides an inspection; it is stored as unconfirmed.
2.2 A stop has a **recorded reason** only if there is an open repair or an active note. An inspector remark ("Pump jack not moving")
may be quoted as an observation but is not a recorded reason. With no reason the answer says **"no recorded reason"** and suggests a check;
it never invents a cause.

**R3 Visuals** — a visual named in the question always wins. Otherwise: one well now → card · list of wells/repairs/breaches → table ·
change over time → line · comparing a few wells/areas → bar · locations → map · two dimensions → heatmap · a short scalar answer → none (text).

**R4 Memory, scope, conflicts**
4.1 Corrections, shared well notes and well-type rules apply to **every** user and are attributed to their author **by name**.
4.2 A rule scoped to a well type applies to that type only (a T350 rule never touches T200 WELL-0102).
4.3 Private conversation memory belongs to one `user_id`; another user asking about "the wells we discussed yesterday" is told there is
no earlier conversation and receives none of the first user's data.
4.4 When a claim contradicts the data or another user, **both statements are kept**, the new one is marked **unconfirmed**, the conflict is
shown, and the user is asked to confirm.

**R5 Presentation** — wells by ID; people, areas and teams **by name** (not `U-201`, not `NE-07`); units (°C, bbl, h, USD); no internal tool
names, JSON or `<thought>` text; short answers (rows are rendered by the UI).

---

## 2. Checks and severity

| Id | Check | Severity |
|---|---|---|
| F1 | every required fact (golden `must`) appears in the answer, the rendered rows or the cited records | critical |
| F2 / S1 / S2 | forbidden facts absent: wrong-type wells (S1), another user's data (S2) | critical |
| S1w | wells mentioned ⊆ the expected set | critical |
| F3 | **numeric grounding**: every number in the prose is in a tool result, a difference of two result values, a per-column total, a rule constant or a count | major |
| F4 | independent oracle recomputed from raw files agrees with the tool rows | critical |
| C1 | every cited id exists in the database | critical |
| C2 | **citation relevance**: an id cited beside `WELL-0138` must belong to well 0138 | critical |
| C3 | every cited id was actually returned by a tool in this turn | critical |
| C4 | golden evidence ids are cited | major |
| V1 | visual ∈ allowed set (R3) | major |
| B:* | behaviours: stale status flagged, no-recorded-reason, no invented cause (critical), original kept, conflict surfaced, asks to confirm, author named, follows the user's rule, no prior conversation, overdue notice, outdated report, removed well explained, both notes kept | major (advisory `?` = minor) |
| H7 / H8 | internal ids instead of names; leaked internals | minor |

**Verdict.** `FAIL` if any critical or major check fails, else `PASS`.
Score (informational) = `100 − 40·critical − 15·major − 5·minor`, floor 0.
`ERROR` = infrastructure failure (HTTP 429/5xx, timeout) — never counted as a wrong answer; `SKIPPED` = a step it depends on errored.

## 3. Protocol per answer

1. **Run state.** Sessions replay in benchmark order on a throw-away database copy; the oracle's correction overlay is rebuilt from the session's `corrections` table before each step.
2. **Facts and oracle** (F1–F4, S\*). 3. **Citations** (C1–C4). 4. **Visual** (V1). 5. **Behaviours** (regex, then judge if allowed). 6. **Hygiene** (H7–H8).
7. **Verdict and layer hint** — each failure is tagged with where to fix it:

| `layer` | Meaning |
|---|---|
| `prompt` | the tool returned the facts but the answer omitted or mishandled them |
| `tool-output` | the tool did not return what the answer needed |
| `tool-logic` | the tool's rows disagree with the oracle |
| `model-noise` | hallucinated/mis-attributed citations or numbers |
| `infra` | rate limit / server error — rerun |

## 4. Output

Per step (JSON in `Docs/qa_runs/verdicts.json`):
```json
{ "key": "Q6", "status": "PASS|FAIL|ERROR|SKIPPED", "score": 100,
  "checks": [{"id": "C2", "status": "pass", "severity": "critical", "detail": "ids match their wells"}],
  "violations": [], "layer": null }
```
and `Docs/QA_REPORT.md`: summary table, per-failure detail with the answer, and a diff against the previous run (regressions first).

## 5. Generalisation to the hidden test set

Golden answers exist only for the sample data. For unseen data the critic keeps the checks that need no golden answer — F3, F4 (oracle),
C1–C3, V1, H7/H8 and the scope/privacy rules — and, in property mode, asks metamorphic variants (other area/well/window; paraphrases)
whose answers the oracle recomputes.

## 6. Running it

```bash
py -m copilot.eval.oracle            # oracle reproduces the published answers from raw files
py -m copilot.eval.critic --selftest # critic catches 15 canned bad answers and passes the good ones (no LLM)
LLM_MIN_INTERVAL=5 py -m copilot.eval.critic --run --md     # replay all questions through Gemma, critique, write Docs/QA_REPORT.md
py -m copilot.eval.critic --transcript --md                 # re-critique the last saved run without calling the copilot
```
