# PS-12 — Open Questions for the Problem Owner

Four items that block modelling and bill reconciliation. Source: `CONTEXT.md` §21.

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
- The waste signature we found is two chillers running below about 130 TR combined, at 1.2–1.6 kW/TR. That is about 484 hours, against 0.60–0.68 kW/TR for a single chiller.
- That finding assumes only CH-1 and CH-3 exist as working machines.
- If CH-2 is really in use and the meter is mislabelled or unwired, its energy is hiding in another meter. Our kW/TR numbers and the "two large chillers" count would then be wrong.
- If CH-2 is genuinely idle, the staging table above 430 TR can never fire. The rule "never run two large chillers below 35% load" then reduces to CH-1+CH-3.
- If the owner doesn't know, we can still treat CH-2 as unavailable. We should state that as an assumption in the alert evidence.

**What to ask**
- Is CH-2 out of service, standby only, or mis-metered?
- If it is mis-metered, which meter carries its energy?

## 2. Demand-charge formula

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
