# PS-12 — Open Questions for the Problem Owner

Sixteen items (15 and 16 added after the detector diagnostics and the forecast). Items 1–4 block modelling and bill reconciliation; 5–14 cover scoring, product behaviour, delivery and scope. Each has a default we proceed with if unanswered. Source: `CONTEXT.md` §21.

## Status (Check-in 1 deck, slide 8)

Only item 2 has been answered directly. The other seven discovery-call items use the written fallbacks below, which were informally confirmed. We restate them at the discovery call for sign-off and do not treat them as formally signed. We also ask for two engineers (or students) to rate 20 alerts, which is how the trust metric is measured.

| # | Question | Status | What we build on |
|---|---|---|---|
| 2 | Demand-charge formula | **Answered** | Bills follow `min(MD, CD)` |
| 1 | CH-2 | **Answered** | CH-2 is completely unavailable; the zero reading is real, not a metering fault |
| 5 | Scoring weights | Default, informally confirmed | Balanced; baseline and detector first |
| 14 | Hotels to demonstrate | Default, informally confirmed | All three, Gurugram deepest |
| 9 | Limits vs recommendations | Default, informally confirmed | Safety hard; comfort hard if the room is occupied |
| 10 | Alert policy | Default, informally confirmed | Rank by ₹, show confidence, cap daily |
| 7 | Savings baseline | Default, informally confirmed | Earliest pre-change months, adjusted only |
| 12 | Deployment | Default, informally confirmed | Free hosting, no login, recorded demo |
| 3, 4, 6, 8, 11, 13 | Event ends, fault-month bills, label split, tariffs, LLM use, replay | Default | Written fallbacks below |

Still open inside item 2: whether the excess-demand penalty is charged on top of the demand charge, and whether the 75% floor applies in every hotel. Both follow the guide's worked example until answered.

Timeline: MVP online by 12 Nov (Check-in 2); final auction 18 Nov.

## 1. CH-2 shows zero energy all year

**What we see**
- The Gurugram equipment register lists three chillers: CH-1, CH-2 (300 TR) and CH-3 (150 TR).
- CH-2's sub-meter reads 0 kWh for all twelve months.
- CH-1 and CH-3 carry the whole cooling load.
- The staging guidance is written in terms of all three chillers:
  - CH-3 alone up to 130 TR.
  - CH-1 alone up to 280 TR.
  - CH-1+CH-3 up to 430 TR.
  - CH-1+CH-2 above that.

**Why it matters**
- The waste signature we found is two chillers running below about 130 TR combined, at 1.2–1.6 kW/TR. That is about 481 hours (median 1.34 kW/TR), against 0.60–0.68 kW/TR for a single chiller. First-pass size: about 33 MWh, ₹2.9 lakh, 0.8% of Gurugram's bill.
- A second cluster near 1.05 kW/TR (CH-1 alone at 130–280 TR, about 900 h, mostly June–July) is not explained. We do not call it waste. Knowing the true state of CH-2 may explain it.
- **Answered (owner): CH-2 is completely unavailable.** The zero reading is real. Consequences: the chiller waste findings stand (no hidden CH-2 energy in another meter, kW/TR and the two-chiller count are right); the staging table above 430 TR (CH-1+CH-2) can never apply, so the rule reduces to CH-1+CH-3; alert evidence says CH-2 is unavailable. The 1.05 kW/TR cluster (CH-1 alone at 130–280 TR) is **not** explained by CH-2 and stays unexplained; it is still not called waste.
- Superseded working answer: treat CH-2 as unavailable (was informally confirmed, pending sign-off).
- That finding assumes only CH-1 and CH-3 exist as working machines.
- If CH-2 is really in use and the meter is mislabelled or unwired, its energy is hiding in another meter. Our kW/TR numbers and the "two large chillers" count would then be wrong.
- If CH-2 is genuinely idle, the staging table above 430 TR can never fire. The rule "never run two large chillers below 35% load" then reduces to CH-1+CH-3.
- If the owner doesn't know, we can still treat CH-2 as unavailable. We should state that as an assumption in the alert evidence.

**What to ask**
- Is CH-2 out of service, standby only, or mis-metered?
- If it is mis-metered, which meter carries its energy?

## 2. Demand-charge formula

> **ANSWERED:** the bills follow `min(MD, CD)`. The two sub-questions under "What to ask" (penalty on top; 75% floor in every hotel) are still unanswered and follow the worked example.

**What we see**
- The tariff sheet says billing demand is `max(MD, 75% of CD)`. MD is the recorded maximum demand and CD is the contract demand.
- The guide's worked example uses `min(MD, CD)`.
- `CONTEXT.md` currently records the charge as `min(billing demand, CD) × ₹290`, with a 75%-of-CD floor. That reading combines the two statements.

**Why the two differ**
- The sheet describes a floor: you pay for at least 75% of contract demand even when actual demand is lower.
- The example describes a cap: you never pay for more than contract demand.
- They coincide only when MD sits between 75% of CD and CD.
- Above CD, the sheet's formula bills the full MD. The example's formula bills only CD, and any excess goes to a separate penalty.
- Below 75% of CD, the sheet's formula bills 75% of CD. The example's formula bills the actual MD.

**Where it hits us**
- Gurugram exceeded CD in May and June 2026, where the excess-demand penalty was ₹49,880 in May. That is where the two formulas diverge.
- Bill reconciliation (the T9 setup, Apr→May +₹5.30 lakh) must reproduce each bill's demand line exactly.
- Any savings estimate for peak shaving depends on whether the saved kVA is charged at all.
- Our hourly maximum demand already matches the bills to within 0.5 kVA, so the inputs are right. The ambiguity is only in how they are priced.

**What to ask**
- Which formula do the bills actually follow?
- Is the excess-demand penalty charged on top of the demand charge, and how is the excess computed?
- Is the 75% floor applied in every hotel's tariff, or only in some?

## 3. Event end times past midnight

**What we see**
- 167 events have an end time of 23:59.
- The field description says 23:59 means the event ran past midnight, so the real end time is lost.
- We flag these with `ends_after_midnight`.

**Why it matters**
- Events are an explanation for extra load, and an alert must not fire when load is explained by an event.
- If we assume the event ended at 23:59, we miss the load after midnight. That load would then look unexplained and could trigger a false alert.
- If we assume a late end such as 02:00, we may wrongly suppress a real anomaly.
- The decision affects the baseline too. Event hours should be modelled or excluded consistently.

**What to ask**
- Is there a typical range for the true end time, by event type? Weddings, conferences and banquets are likely to differ.
- Failing that, may we cap the assumed end at a fixed hour, for example 01:00 or 02:00?
- Do any other columns, such as catering or venue, hint at the duration?

**Fallback if there is no answer**
- Use a uniform assumed extension.
- State the assumption in the evidence panel.
- Run a sensitivity check on detector recall with different extensions.

## 4. Meter-fault hours in bill reconciliation

**What we see**
- Gurugram's meter faults corrupt only the billed columns (flat lines and zeros). `kw_avg` and power factor stay valid.
- We rebuilt cleaned values from `kw_avg` and kept the raw values in `*_raw`.
- The Jan, Jul and Aug bills were issued on the corrupted readings. The project rule is never to "fix" a bill.

**The conflict**
- Reconciliation compares the metered consumption we compute against the billed amount.
- If we use cleaned values, those three months will not match their bills. The gap is real and caused by the fault.
- If we use raw values, the reconciliation ties out. But it then validates a number we know is wrong, and the savings and alert logic would treat fault hours as real consumption.
- The T5 requirement says meter faults are suppressed, never alerts or savings. Reconciliation needs a matching rule.

**Our proposed treatment**
- Show both figures: billed (as issued) and corrected (rebuilt from `kw_avg`).
- Mark the difference as "meter fault, billed under-reading/over-reading" rather than as an unexplained variance.
- Keep these months out of any savings baseline.

**What to ask**
- Does the owner want fault-month variances surfaced as billing-dispute candidates, with the rupee value of the gap?
- Or should reconciliation just flag those months as unreliable and exclude them?
- Is there a tolerance, for example ±2%, under which a bill is treated as reconciled?

## 5. Scoring weights

**What we see**
- The brief lists several deliverables: baseline and forecast accuracy (CV(RMSE)/NMBE), anomaly detection, costed explanations and alerts, bill reconciliation, IPMVP savings, and the UI.
- It does not say how they are weighted.

**Why it matters**
- It sets where effort goes. The detector and alerts depend on the baseline, so a weak baseline hurts everything downstream.
- A polished UI over a weak model, or the reverse, are different trade-offs.

**What to ask**
- Which of forecast accuracy, detection precision/recall, explanation quality and the UI carries the most weight?

**Fallback if there is no answer**
- Balanced effort, with the baseline and detector first.

## 6. Label split and evaluation window

**What we see**
- We tune the detector only on anomalies starting before 1 Apr 2026 and report on those from 1 Apr 2026. Post-April label rows are not browsed.

**Why it matters**
- It prevents label leakage, but only if the graders use the same cutoff. A different cutoff makes our reported numbers hard to compare.
- A single held-out window can be lucky or unlucky, especially for the baseline.

**What to ask**
- Is 1 Apr 2026 the cutoff the graders use?
- Is one held-out window enough, or is a rolling backtest also expected?

**Fallback if there is no answer**
- Keep the 1 Apr 2026 split for the detector. Add a rolling-origin backtest for the baseline only.

## 7. Savings baseline (IPMVP Option C)

**What we see**
- Savings may only be claimed against an adjusted baseline.
- The data covers Oct 2025 to Sep 2026. There is no full 12-month pre-intervention year.

**Why it matters**
- Option C needs a baseline period and a reporting period. Without a full baseline year, seasonality is only partly covered, and the weather adjustment carries more weight.
- Claiming savings against an unadjusted or short baseline would break the project rule.

**What to ask**
- Which months form the baseline and which the reporting period?
- Is a baseline built from Oct 2025 onward acceptable?

**Fallback if there is no answer**
- Baseline = the earliest months before any intervention. Report savings only for the period after, and list the adjustment variables (weather, rooms sold, event guests).

## 8. Tariffs

**What we see**
- The tariffs, ToD windows and bills are supplied as part of a fictional scenario. The Goa Jul 2026 bill is provisional (`is_provisional`).
- ToD windows differ per hotel: GGN peak 18–22, JAI 17–23, GOA 18–22 with off-peak 22–06.

**Why it matters**
- Every ₹ figure depends on them, but the project must not claim they are real.

**What to ask**
- May we treat the supplied tariffs as given?
- How should they be caveated in the UI?

**Fallback if there is no answer**
- Use them as given, label ₹ figures "illustrative tariff", and mark provisional bills clearly.

## 9. Do the comfort and safety limits bind recommendations, or only automation?

**What we see**
- The guide states limits: guest rooms 22–25 °C (guest override 20–26), CHW setpoint never below 6.5 °C, hot water ≥60 °C once daily (Legionella), pool filtration ≥8 h/day, kitchen exhaust running whenever cooking equipment is on, fresh air per NBC, and fire pumps, pressurisation and lifts never controlled.
- It also has an automation table saying what may be automated.
- It never says whether a recommendation shown to an engineer may go outside a limit.

**Three possible readings**
- (a) Hard bound on every recommendation. This is the safest, but it can leave savings on the table.
- (b) Bound on automation only. Recommendations outside a limit are shown with a label because a human decides. This is risky for the safety items.
- (c) Split by type. Safety and regulatory limits are always hard. Comfort limits are soft, so a recommendation near a boundary carries a flagged trade-off.

**Edge cases to settle**
- Does the 22–25 °C band apply to unsold rooms? The brief only allows PMS setback for them.
- Is 6.5 °C itself allowed, or is it an edge? The standard setpoint is 7.0 °C.
- May the 60 °C hot-water setpoint be touched, or must only the daily cycle never be skipped? Water heating is about 14% of GGN load.
- May the pool's 8 h of filtration be moved off-peak?
- If a heatwave pushes rooms past 25 °C, should the system alert on the comfort breach, or only on energy waste?
- If an event runs past midnight with no known end time, should a banquet AHU stop time be recommended, or held back until the end time is known? (See item 3.)

**Why it matters**
- It needs a constraint layer in front of the recommender, with each rule coded as a hard rejection, a soft penalty or a flag.
- Test T10 already requires refusing kitchen exhaust, thermostats and life-safety. We need to know whether a recommendation touching those is refused outright, or only a control action.
- The UI needs "within limits / near limit" wording under readings (b) and (c).

**Fallback if there is no answer**
- Reading (c). Safety and regulatory limits (Legionella, fresh air, pool filtration, kitchen exhaust, life-safety, the 6.5 °C CHW floor) are always hard. Comfort limits are hard for occupied rooms and soft for unsold rooms. Anything outside a limit is refused, not shown with a warning.

## 10. Alert policy

**What we see**
- The brief requires alerts with evidence and no alerts for conditions explained by weather, occupancy or events. It does not set a daily volume or a ranking rule.

**Why it matters**
- It controls alert fatigue and the detector's threshold.

**What to ask**
- What alert volume per day per hotel is acceptable?
- Should alerts be ranked by ₹ impact or by confidence?

**Fallback if there is no answer**
- Rank by ₹ impact, show confidence beside it, and cap the daily alerts per hotel.

## 11. LLM use

**What we see**
- The project rule is that LLM text may only state facts present in the data. All numbers come from the models, not the LLM.

**Why it matters**
- A deployed LLM adds cost, latency and a hallucination risk to the explanations.

**What to ask**
- Is a deployed LLM expected for explanations?
- If so, which model, and what latency and cost budget?

**Fallback if there is no answer**
- Template-based explanations, with optional LLM phrasing over verified numbers, so the product works without an LLM.

## 12. Deployment

**What we see**
- The brief asks for an engineer-facing UI at a public URL. It does not name a platform, an auth requirement or data-residency limits.

**What to ask**
- What counts as a "public URL"?
- Is the UI judged live or from a recording?

**Fallback if there is no answer**
- Free-tier hosting with no login, plus a recorded demo as a fallback.

## 13. Out-of-period behaviour

**What we see**
- The data runs Oct 2025 to Sep 2026, and the current date is past the end of it.

**Why it matters**
- It decides whether the product behaves like a live monitor or a retrospective report, and how alerts are presented in time.

**What to ask**
- Should the system be demonstrated as streaming/replay, or as a batch report over the full year?

**Fallback if there is no answer**
- Replay mode over the year with a date selector, so alerts appear as of the selected time.

## 14. Which hotels to demonstrate

**What we see**
- The brief covers three hotels. Gurugram has the largest cost, the HVAC and demand-penalty story, and most of the acceptance tests (T1, T2, T4–T7, T9). T3 is Jaipur and T8 is Goa.

**Why it matters**
- It decides whether the MVP goes deep on Gurugram or wide across all three.

**What to ask**
- Are we expected to demonstrate the solution across all three hotels, or is one successful end-to-end hotel enough?

**Fallback if there is no answer**
- Run all three hotels through the same pipeline, with Gurugram getting the deepest treatment.

## 15. How is time to detect measured?

**What we see**
- The target is "median under 2 h for High" and the brief measures it as anomaly start to first alert.
- For Gurugram chiller staging, the label window opens at 22:00 but the second chiller appears a median 2 h later (29 h and 52 h later for two labels). Our alert comes 1 h after the chiller appears in every one of the 11 High cases.
- Measured from the label start the median is 3.0 h and none is within 2 h. Measured from when the equipment first shows the fault, 100% are within 2 h.

**What to ask**
- Is time to detect measured from the label start or from when the fault first shows in the data?
- Are the label windows meant to be scheduled windows (the night shift) or the true fault periods?

**Answered (owner):** time to detect is measured from when the fault first shows in the data, not from the label start.
- Headline is now the onset-based figure (`evaluation.onset_ttd`; detector unchanged). The label-start figure stays as a secondary row.
- Caveat: onset uses the detector's own raw rule flags, so a 1 h gap is close to the floor by construction. High labels of types with no rule have no onset and are not scored.

## 16. Can the laundry, water-heating and banquet plans be an input to the forecast?

**What we see**
- The three days above 1,000 kVA were not weather or occupancy. Laundry, water heating and the banquet AHUs all ran at about double their normal afternoon draw together on a hot day.
- The forecast cannot see that from weather, rooms sold and the events calendar. It predicted about 780–795 kVA on those days.

**Why it matters**
- If the housekeeping laundry plan, the heat-pump water-heating schedule and the banquet pre-cool plan are known the day before, the stack can be forecast directly and the warning becomes exact.
- Without them the product can only say a breach is possible if these loads coincide, and flags about one hot day in four.

**What to ask**
- Does the hotel plan the laundry shifts, the water-heating schedule and the hall pre-cooling in a system we could read, or only on the day?

**Decision (project team):** with only weather, occupancy and the events calendar as inputs, the >1,000 kVA days cannot be predicted. We treat them as a managed risk, not a forecast target.

**Fallback if there is no answer**
- Keep the stacking watch at 90% of contract demand and recommend holding these loads out of 13:00–17:00 on watch days.

**If a daily hotel schedule is provided (route to a real fix)**
- Any artifact giving the next day's planned timing of the laundry shifts, heat-pump water heating and banquet-hall pre-cooling would let us map the stack directly: a schedule file or export, a housekeeping or banquet plan sheet, or a BMS schedule table. Hourly start and end times per load are enough.
- With it, the forecast adds the planned kW of each load at its planned hours, so the stack becomes a prediction instead of a "could happen" allowance, and the watch can fire only on days where the loads really overlap.
- The change would be: add the schedule as an input to `src/forecast.py`, replace the connected-rating allowance on days with a plan, and keep the 90% watch as the fallback for days without one.
- To check it, replay the schedule against the three breach days (12 May, 18 Jun, 25 Jun) and against the other hot days. Three events can show whether the idea works but cannot establish precision, so report it that way.

## Shortlist for the discovery call (4–7 Nov)

The kickoff deck says to rank 8–10 questions, since a 20-minute call won't cover more, and to send the agenda a day before. These are the eight questions on slide 8 of the Check-in 1 deck. Order:

1. Item 2 — demand-charge formula
2. Item 1 — CH-2
3. Item 5 — scoring weights
4. Item 14 — which hotels to demonstrate
5. Item 9 — comfort and safety limits
6. Item 10 — alert policy
7. Item 7 — savings baseline, and how finance verifies savings
8. Item 12 — deployment

The rest (items 3, 4, 6, 8, 11, 13) are defaults we state in the call and move on from.

**Asks of the owner:** sign-off on the answers above, and two engineers (or students) to rate 20 alerts.

