# ChatGPT session findings — verified against local data

Source: shared ChatGPT conversation "Plan Energy Optimization Challenge" (https://chatgpt.com/share/6ae9b00c-5af4-83e8-81b4-733d51610d18), read 2026-11-03.
Verification: cleaned parquet in `data/clean/`, the PS-12 brief `.docx`, `CONTEXT.md` and `src/clean_data.py`.

## How to read this
- **Verified** = reproduced from the local files in this session.
- **Not verifiable locally** = depends on external sources that are not in the repo. Items that depend on the kickoff deck were checked against the deck itself once you pasted it (marked "kickoff deck p.N").
- **Discrepancy** = conflicts with something else we have.

Reading limits: the page was read from the browser's accessibility tree, which cuts each text node at about 100 characters. Long sentences are therefore abbreviated, and the stakeholder questions are paraphrased. The last section of the final research answer ("What should we actually build differently?") was not read. The vendor and case-study citations in the research answer were not opened.

## What the conversation covered
1. **Kickoff deck review.** Four stages (Understand, Talk, Build, Get bid on), 28 Oct to 18 Nov 2026. The first deliverable is an eight-slide problem breakdown: problem, today's process, sizing, root causes, scope, success metric, risks, owner questions.
2. **Problem framing.** Hotels already have meters, sub-meters and a BMS. The gap is contextual detection, explanation, costing and verified savings. ChatGPT separates "consumption is high" (Problem A) from "avoidable waste isn't caught in time" (Problem B) and says the product addresses B.
3. **Data pack inventory and a proposed fact/dimension layout**, plus the deliberate data-quality issues.
4. **Stakeholder call prep.** A 20-minute agenda, about 15 ranked questions, and 5 dataset-specific questions. It also reworked two MVP-relevant questions, explained IPMVP Option C with an illustrative example, and recommended dropping a monetisation question because the brief doesn't ask for one.
5. **Explained the swapped sub-meters.** The README says `lifts_kw` and `pool_kw` are swapped in the BMS for March 2026 only.
6. **Research 01.** Which energy-management solutions hotels use, and the gaps.

## Verification of its factual claims

| Claim in the conversation | Status | Evidence |
|---|---|---|
| Rooms 220 / 160 / 140; contract demand 1,000 / 700 / 600 kVA | Verified | `CONTEXT.md` §2, from the brief |
| Annual energy cost ₹3.70 / 2.14 / 1.56 Cr, total ₹7.40 Cr | Verified | Sum of `monthly_bills.total_energy_cost_inr`: GGN 3.699, JAI 2.142, GOA 1.559, total 7.400 Cr |
| Energy per occupied room-night 73.3 / 54.1 / 61.6 kWh | Verified | `total_kwh` ÷ `rooms_sold`: GGN 73.3, JAI 54.1, GOA 61.6 |
| 1,829 BMS alarms | Verified | `bms_alarm_log`: 1,829 rows |
| 66% of alarms closed without action | Verified | 720 "Acknowledged — no action" + 254 "normal for event" + 228 "normal for weather" = 1,202 of 1,829 = 65.7% |
| Median 8.3 h from alarm to action | Verified | Median of `action_at` − `raised_at` over the 627 alarms with an action = 8.28 h |
| Only 26% of alarms were real problems; only 40% of real problems raised an alarm | Verified against the brief text only | Stated in the brief. Not recomputed, because that needs the label table and the leakage rule applies |
| ₹21.6 L waste, 229 MWh, 107 waste events | Verified against the brief text only | Same reason |
| 1,086 kVA peak vs 1,000 kVA contract demand | Verified | `monthly_bills.recorded_md_kva`: GGN May 2026 = 1,086 |
| ₹88,218 excess-demand penalties in May and June 2026 | Verified | ₹49,880 (May) + ₹38,338 (June) = ₹88,218 |
| Row counts: meter 35,040 / 8,760 / 8,784; sub-meters 8,760 and 17,520; BMS command log 1,173; weather 26,280; occupancy 1,095; events 330; labels 111; alarms 1,829 | Verified | Cleaned tables match. Goa shows 8,760 rather than 8,784 because the 24 duplicates were dropped |
| Deliberate issues: GGN meter faults, Jaipur 10 h gap, 24 Goa duplicates, swapped sub-meters, provisional Goa bill | Verified | `CONTEXT.md` §4 and §19. The Goa Jul 2026 bill is flagged "Provisional (estimated reading)" in `monthly_bills` |
| Swap is `lifts_kw` ↔ `pool_kw`, March 2026 only, other months unchanged | Verified | `src/clean_data.py` swaps back for March 2026 only and flags it |
| Success-metric targets (precision ≥70%, recall ≥75% High+Medium, <2 h, CV(RMSE) <15% monthly and <30% hourly, NMBE ±5%, peak forecast ±5%, usefulness ≥4/5, 8–12% bill cut) | Verified | `CONTEXT.md` §7 and the brief |
| Evaluate on labels from 1 Apr 2026, tune before | Verified, consistent | Matches the leakage rule in `CLAUDE.md` |
| Problem breakdown is worth 15% of the overall grade | Verified (kickoff deck p.9, p.11) | Check-in 1 = 15%. The "50%" you mentioned is the deck's "half your grade is earned before auction day": 15% + 15% + 20% (Check-ins 1–3). The breakdown alone is 15% |
| Challenge dates 28 Oct to 18 Nov; discovery calls 4–7 Nov; problem owner Apurav | Verified (kickoff deck p.3, p.4, p.8) | Kickoff 28 Oct; breakdown session 3 Nov; Check-in 1 due Wed 4 Nov 11:59 pm; discovery calls 4–7 Nov; MVP 12 Nov; internal auction 16 Nov; final 18 Nov. Apurav (Masters' Union) owns the Masters' Union problems, which include PS-12 |
| Eight-slide breakdown elements; 20-minute call agenda | Verified (kickoff deck p.11, p.46) | Elements: problem, today's process, sizing numbers, root causes, scope, success metric, risks, owner questions. Call: 0–3 / 3–8 / 8–13 / 13–17 / 17–20 min as ChatGPT listed |
| Existing vendors (Schneider, Siemens, Honeywell, Johnson Controls, Zenatix) and the Lemon Tree, Juniper and Hilton cases (Hilton "14.5% savings since 2009") | Not verifiable locally | External, vendor-published. Citations not opened |
| Six market gaps (fragmented data, alarms without action, no contextual root cause, portfolio view, savings proof, interoperability) | Not verifiable locally | Reasoning, not data. Gaps 1, 2, 3 and 5 match the brief's own problem statement |

## Where the conversation is thinner than our local work
- **Meter faults.** It says to identify and exclude flat-line readings. Locally this is done: faults corrupt only the billed columns, values are rebuilt from `kw_avg`, and `exclude_from_model` marks the hours (see `CLAUDE.md`).
- **Bills.** It doesn't mention that the Gurugram Jan, Jul and Aug bills carry the corrupted readings, so reconciliation needs two figures (billed and corrected).
- **CH-2.** It never notices that the CH-2 sub-meter reads zero all year. This is open question 1.
- **Demand-charge ambiguity.** It doesn't notice that the tariff sheet and the worked example disagree. This is open question 2.
- **Tuning window.** It suggests Oct 2025 to Mar 2026 for development and Apr to Sep 2026 for evaluation. The rule in `CLAUDE.md` is about labels. Whether baseline training should also stop at March is not settled (see open question 6).

## Constraints from the kickoff deck that affect our plan
- **Rank 8–10 questions.** The deck says you won't get through more in the 20-minute call. We have 13 open questions and ChatGPT proposed about 15, so a shortlist is needed (p.47).
- **Send the agenda a day before the call**, start by playing back our understanding, and write up what changed for Check-in 2 (p.12).
- **Check-in 2 (12 Nov)** needs a deployed MVP URL plus a one-page note: what works, what's left, test results, what changed after the call. "A link without access is marked zero" (p.14). It is assessed on the core use case end to end, real AI work, test-set evidence and progress since Check-in 1.
- **Check-in 3 and the final** assess: works live, measured results, value case, pitch, Q&A (p.15–16).
- **"No metric: a demo, not a solution"** (p.45). Prove the savings against a named baseline, which fits our IPMVP approach.
- **Avoid** solution-first thinking, imaginary data, over-automation without a justification for keeping a human, and no feedback loop (p.47). The recommend-only guardrail already covers the third.
- **Results must be real; synthetic data is fine** (p.18). This matches the "don't claim tariffs are real" rule.
- **Best problem breakdown prize ₹5,000** (p.17).
- **Section 10 of the brief** is where the deck says to start drafting questions (p.19).

## Suggestions for OPEN_QUESTIONS.md (not yet added)
- **Scope: all three hotels or one?** ChatGPT flags this as the question that matters most for the build. It is not in our list.
- **Commercial model.** ChatGPT recommends dropping it, and our list already omits it. No change needed.
- **Real-deployment data availability and integration.** It reworked these as MVP-relevant. Partly covered by our question 12.
- **How finance verifies savings today, and whether IPMVP Option C would be accepted.** Partly covered by our question 7.
