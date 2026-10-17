# QA report — copilot answers vs. 03-evaluation-queries.md

Rulebook: `Docs/QA_RULEBOOK.md`. **18 PASS · 9 FAIL · 0 ERROR (infra) · 0 SKIPPED** of 27 steps. Critical or major violation ⇒ FAIL; ERROR/SKIPPED are not answer failures.

| Step | User | Status | Score | Violations | Fix layer |
|---|---|---|---|---|---|
| Q1 | U-201 | PASS | 100 | — | — |
| Q2 | U-201 | FAIL | 60 | F4 | tool-logic |
| Q3 | U-201 | PASS | 100 | — | — |
| Q4 | U-201 | PASS | 100 | — | — |
| Q5 | U-201 | PASS | 100 | — | — |
| Q6 | U-201 | PASS | 100 | — | — |
| Q7 | U-201 | FAIL | 60 | F4 | tool-logic |
| Q8 | U-201 | FAIL | 85 | F3 | model-noise |
| Q9 | U-201 | PASS | 95 | B:unrecorded_shutin | prompt |
| Q10 | U-201 | FAIL | 0 | F1, S1w, F4 | tool-output |
| Q11a | U-201 | PASS | 100 | — | — |
| Q11b | U-201 | FAIL | 45 | F3, F4 | tool-logic |
| Q12a | U-201 | FAIL | 85 | F3 | model-noise |
| Q12b | U-201 | FAIL | 85 | B:removed_well_explained | prompt |
| Q13 | U-201 | PASS | 100 | — | — |
| Q14a | U-201 | PASS | 95 | H7 | prompt |
| Q14b | U-201 | PASS | 90 | H7, H8 | prompt |
| Q14c | U-201 | PASS | 100 | — | — |
| Q15a | U-202 | PASS | 100 | — | — |
| Q15b | U-401 | PASS | 100 | — | — |
| Q16a | U-102 | FAIL | 85 | V1 | prompt |
| Q16b | U-201 | PASS | 100 | — | — |
| Q16c | U-202 | PASS | 100 | — | — |
| Q17a | U-201 | FAIL | 80 | V1, H7 | prompt |
| Q17b | U-204 | PASS | 100 | — | — |
| Q17c | U-102 | PASS | 100 | — | — |
| Q18 | U-401 | PASS | 100 | — | — |

### Q2 — FAIL
> Which wells in Northeast Block 8 are not producing oil right now, and why? Show them in a table.
- **F4** (critical): oracle {'WELL-0170': 2.9, 'WELL-0172': 5.7, 'WELL-0175': 0.4} vs tool {'WELL-0164': 4.1, 'WELL-0170': 2.9, 'WELL-0172': 5.7, 'WELL-0175': 0.4}
- undecided B:no_invented_cause: needs judge (no key / no proof)

<details><summary>answer</summary>

There are 4 wells in Northeast Block 8 currently not producing.

| Well ID | Type | Last Inspection | Reason |
| :--- | :--- | :--- | :--- |
| WELL-0164 | T200 | 2026-10-15 [INS-0164-0205] | No recorded reason; suggest a check. |
| WELL-0170 | T200 | 2026-10-15 [INS-0170-0206] | Walking beam bearing wear [MNT-0170-031] |
| WELL-0172 | T200 | 2026-10-15 [INS-0172-0206] | Flowline corrosion pinhole leak [MNT-0172-028] |
| WELL-0175 | T200 | 2026-10-15 [INS-0175-0204] | No recorded reason; suggest a check. |

**Summary:**
* **WELL-0164**: Wellhead is 4.1°C above ambient (limit: 15.0°C). The recorded status "active" is out of date [INS-0164-0205].
* **WELL-0170**: Wellhead is 2.9°C above ambient (limit: 15.0°C).
* **WELL-0172**: Wellhead is 5.7°C above ambient (limit: 15.0°C). The recorded status "active" is out of date [INS-0172-0206].
* **WELL-0175**: Wellhead is 0.4°C above ambient (limit: 15.0°C). The recorded status "active" is out of date [INS-0175-0204].

</details>

### Q7 — FAIL
> Show on a map every well in Northeast Block 8 with a real spill in the last 90 days.
- **F4** (critical): oracle {'WELL-0151': 5.4, 'WELL-0165': 1.2, 'WELL-0175': 3.9, 'WELL-0186': 0.6}

<details><summary>answer</summary>

There were 4 real spills in Northeast Block 8 in the last 90 days, totaling 10.2 bbl [INS-0186-0097, INS-0165-0194, INS-0175-0193, INS-0151-0201].

</details>

### Q8 — FAIL
> Show a heatmap of 2026 spills by geographic area and month.
- **F3** (major): numbers not found in tool results: [43.0]

<details><summary>answer</summary>

The heatmap for 2026 spills by area and month is displayed above. Southwest Block 24 has the highest total spill count (43) for the year so far.

</details>

### Q9 — PASS
> Which rules has WELL-0001 broken in the last 12 months, and what is still open?
- **B:unrecorded_shutin** (minor): regex

<details><summary>answer</summary>

In the last 12 months, WELL-0001 has the following breaches and open actions:

**Breaches:**
* **SR-01:** Reportable spill (6.8 bbl) reported after 41 h (limit 24 h) [REG-0001-001, INS-0001-0185].
* **SR-03:** Agency verification of clean-up not closed (due within 60 days of discovery) [REG-0001-003, INS-0001-0185].
* **SR-02:** Spill contained after ~7 h (limit 4 h) [MNT-0001-029, INS-0001-0185].
* **RC-04:** Notice of violation REG-0001-002 (fine USD 5000, open) has no response on record (due within 30 days) [REG-0001-002].

**Open Actions (Pending Duties):**
* **RCA:** Root-cause analysis required due to 3 corrective flowline repairs in the last 12 months (threshold 3, manual/SOP OM-T200) [MNT-0001-028, MNT-0001-029, MNT-0001-032].

</details>

### Q10 — FAIL
> In Southwest Block 24, which spills in the last 90 days were not contained within the SOP time limit?
- **F1** (critical): missing ['WELL-0082', '7.1', 'WELL-0100', '8.1', 'MNT-0082-028', 'MNT-0100-034']
- **S1w** (critical): wells outside the expected set: ['WELL-0080']
- **F4** (critical): oracle {'WELL-0082': ('INS-0082-0198', 7.1), 'WELL-0100': ('INS-0100-0196', 8.1)}

### Q11b — FAIL
> For the three wells we discussed yesterday, what have repairs cost this year?
- **F3** (major): numbers not found in tool results: [46942.0, 25794.0, 5176.0]
- **F4** (critical): oracle {'WELL-0121': 25794, 'WELL-0138': 46942, 'WELL-0107': 5176}

<details><summary>answer</summary>

The repair costs for the three wells discussed yesterday (WELL-0121, WELL-0107, and WELL-0138) so far this year are:

*   **WELL-0138:** $46,942.00
*   **WELL-0121:** $25,794.00
*   **WELL-0107:** $5,176.00

</details>

### Q12a — FAIL
> The 15 Oct reading for WELL-0164 is wrong. The handheld thermal gun used in that inspection was faulty; the field crew re-measured the wellhead at 41.0 °C.
- **F3** (major): numbers not found in tool results: [41.0]

<details><summary>answer</summary>

Recorded the correction for WELL-0164 (inspection [INS-0164-0205]). The `wellhead_temp_c` was updated from 24.0 to 41.0.

**New Status:**
*   **Producing:** Yes (based on temperature delta)
*   **Temperature Delta:** 21.1 °C above ambient (limit is 15.0 °C)

**Conflicts:**
*   The inspector note from Tyler Hughes ("Pump jack not moving.") disagrees with the corrected reading. Please confirm if the well is producing despite the pump jack not moving.

</details>

### Q12b — FAIL
> Which wells in Northeast Block 8 are not producing oil right now, and why? Show them in a table.
- **B:removed_well_explained** (major): regex

<details><summary>answer</summary>

| Well ID | Reason for Not Producing | Wellhead Temp Delta | Status Note |
| :--- | :--- | :--- | :--- |
| WELL-0170 | Walking beam bearing wear [MNT-0170-031] | 2.9°C above air (Limit: 15.0°C) | Matches recorded status |
| WELL-0172 | Flowline corrosion pinhole leak [MNT-0172-028] | 5.7°C above air (Limit: 15.0°C) | **Out of date** (Recorded: active) |
| WELL-0175 | No recorded reason; suggest a check | 0.4°C above air (Limit: 15.0°C) | **Out of date** (Recorded: active) |

</details>

### Q14a — PASS
> Which wells in Northeast Block 7 need a root-cause analysis on their pump jack?
- **H7** (minor): internal ids shown instead of names: ['NE-07']

<details><summary>answer</summary>

In Northeast Block 7 (NE-07), the following wells require a root-cause analysis (RCA) on their pump jacks due to having reached the threshold of 3 corrective repairs within 12 months [MNT-0108-024, MNT-0108-026, MNT-0108-028, MNT-0121-031, MNT-0121-034, MNT-0121-035, MNT-0138-031, MNT-0138-032, MNT-0138-034]:

| Well ID | Well Type | Corrective Repairs | Repair IDs |
| :--- | :--- | :--- | :--- |
| WELL-0108 | T350 | 3 | MNT-0108-024, MNT-0108-026, MNT-0108-028 |
| WELL-0121 | T200 | 3 | MNT-0121-031, MNT-0121-034, MNT-0121-035 |
| WELL-0138 | T350 | 3 | MNT-0138-031, MNT-0138-032, MNT-0138-034 |

</details>

### Q14b — PASS
> Note for all T350 wells: our team now wants a pump jack root-cause analysis after 2 repairs, not 3.
- **H7** (minor): internal ids shown instead of names: ['U-201']
- **H8** (minor): internals leaked: ['rca_corrective_count']

<details><summary>answer</summary>

The rule for T350 wells has been updated. The threshold for pump jack root-cause analysis is now 2 repairs (previously 3, per manual/SOP OM-T200). This change was recorded by U-201 [rule:T350:rca_corrective_count].

</details>

### Q16a — FAIL
> FYI for everyone: WELL-0007 will be shut in from 17 Oct for a 10-day planned workover.
- **V1** (major): visual 'table', expected ['card', 'text']

<details><summary>answer</summary>

The note has been recorded (USR-0007-001 by Jake Morales, valid 2026-10-17 to 2026-10-27). No conflicts were found.

**WELL-0007 Status:**
*   **Producing:** Yes [INS-0007-0203].
*   **Temperature:** Wellhead is 50.6°C, which is **29.9°C above** the 20.0°C limit [INS-0007-0203].
*   **Recorded Status:** "active" matches the latest inspection [INS-0007-0203].
*   **Compliance:** No new consequences; historical breaches for SR-02 were noted [INS-0007-0040, INS-0007-0132].

</details>

### Q17a — FAIL
> WELL-0175 has been shut in for planned work since 14 Oct.
- **V1** (major): visual 'table', expected ['card', 'text']
- **H7** (minor): internal ids shown instead of names: ['U-201']

<details><summary>answer</summary>

Recorded note `USR-0175-002` by user `U-201`: "Shut in for planned work since 14 Oct." (valid from 2026-10-14). No conflicts were found.

**WELL-0175 Status:**
*   **Producing State:** Shut in (not producing).
*   **Compliance:** One breach on `SR-02` (inspection `INS-0175-0051`: "contained after about 5.6 h (limit 4 h)"). No open actions.
*   **Repairs:** No repair reports are currently outdated.

</details>
