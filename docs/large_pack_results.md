# Large pack (data/large): results of the project analyses

Same analyses as the one-year pack, run on 7 years (Oct 2019 – Sep 2026) and 9 metered hotels. Reproduce:

```
uv run python src/clean_large.py                 # data/large/*.csv -> data/clean_large/*.parquet  (+ _cleaning_report.csv)
uv run python tools/large_run.py all             # check, baseline, detector, bills, forecast, demand_ev, ipmvp  -> data/clean_large/results/
```

`tools/large_run.py` sets `PS12_DATA=clean_large` so `src/*` read the large pack. Nothing under `data/clean` is touched, and the original
three-hotel detector still produces the identical 146 alerts.

## Read this first: why these numbers are not independent evidence

- The pack is the one real year resampled by week, plus injected anomalies at rates and types taken from the **full** label set (including labels from 1 Apr 2026).
  Earlier years are near-copies of the last year. Out-of-fold baseline error is therefore optimistic, and the detector's profiles are fitted on data from the same family
  that it is then scored on. The pack's own README says the same. Treat the figures as "does the pipeline scale and hold up", not as new held-out accuracy.
- The detector was **not changed**. Every threshold is the frozen one. The only edits to shared code make modules read a data folder and a site→archetype map
  (defaults reproduce the old behaviour).
- Only 5 of the 9 hotels have sub-meters (GGN, JAI, UDR, GOA, GO2), and the rule layer needs them. JA2, JA3, GO3, GO4 get the baseline, bills and IPMVP only.

## 1. Cleaning (src/clean_large.py)

Rules are generic detections; the answer key (`_injected_issues.csv`) is used only to score them.

| Planted fault | Planted | Caught |
|---|---|---|
| GGN 15-min comms faults (frozen / zero billed columns) | 23 | 23 |
| Jaipur-type hourly comms faults (blank / frozen) | 17 | 17 |
| Goa-type hourly comms faults | 25 | 24 |
| GGN lifts/pool channel swaps (3 planted + the original March 2026) | 4 | 4 |
| Bills whose components do not sum (Actual status, ≥0.5 %) | ~300 | 249 (the rest are <0.5 %) |
| Weather values left outside −5…52 °C after cleaning | – | 0 |

Also handled: duplicates, absent timestamps (re-inserted empty and excluded), DD/MM dates, site-code variants, negatives, Wh-for-kWh, ×10 spikes, PF > 1, kVAh < kWh, DG labelled GRID,
stuck sensors, °F days, −999 sentinels, 0–100 occupancy, 12-hour event times, end-before-start, sign-flipped off-peak rebate, label start/end swaps.
Missing tariff rates (100): 68 recovered from the bills they were applied to, 32 interpolated (flagged `rate_source`). Conflicting duplicate rates (600 rows) resolved the same way.
Full counts: `data/clean_large/_cleaning_report.csv`. Bills are never edited, only flagged.

## 2. Baseline (src/baseline.py, out-of-fold by tariff year)

All nine hotels meet ASHRAE Guideline 14 (hourly CV(RMSE) < 30 %, monthly < 15 %, |NMBE| < 5 %). Ensemble of ridge + boosted trees:

| Site | GGN | JAI | GOA | UDR | JA2 | JA3 | GO2 | GO3 | GO4 |
|---|---|---|---|---|---|---|---|---|---|
| Hourly CV(RMSE) % | 8.4 | 5.3 | 5.5 | 5.6 | 5.2 | 5.2 | 5.4 | 5.6 | 5.2 |
| Monthly CV(RMSE) % | 2.8 | 2.3 | 2.9 | 2.4 | 1.9 | 2.1 | 2.5 | 2.8 | 2.3 |
| NMBE % | 0.35 | −0.01 | −0.02 | 0.02 | 0.00 | −0.04 | −0.01 | 0.00 | 0.02 |

Optimistic for the reason above (a held-out year is close to a copy of training data).

## 3. Detector (frozen; 5 sub-metered hotels)

| Window | Labels | Alerts | Precision | Recall (High+Medium) | Median time to detect (High) |
|---|---|---|---|---|---|
| Before 1 Apr 2026 (tuning window) | 794 | 1,577 | 89 % | 99 % | 1 h |
| From 1 Apr 2026 (original report window) | 80 | 134 | 94 % | 96 % | 3 h from label start |
| All 7 years | 874 | 1,711 | 90 % | 99 % | 1 h |

- All 50 data-fault labels were matched by a meter-fault notice (T5). The post-hoc gain check (15 Nov) fires on nothing in this pack; alerts and notices are unchanged (1,711 and 71). Cost found: 97 % of labelled ₹.
- Precision by hotel: GGN 93 %, JAI 96 %, UDR 94 %, **GOA 83 %, GO2 76 %**. By year: 82–97 %, no trend.
- Lowest-precision rules: HEAT_COOL_FIGHT 67 %, RESIDUAL_UNEXPLAINED 33 % (12 alerts). Unmatched alerts are small: median ₹170–280 each, mostly CHILLER_PART_LOAD_INEFFICIENCY at GOA/GO2
  and LAUNDRY_IN_PEAK at GO2. GO2 is a 1.3× scaled Goa, so the absolute-kW floors and kW/TR margin (set on the 140-room Goa) are a plausible cause. **That is a hypothesis; not tested, nothing was re-tuned.**
- CONTRACT_DEMAND_BREACH: the frozen detector covers 8 of 15; the post-hoc demand rule (src/demand_ev_rules.py) catches 15 of 15 with no unlabelled breach alerts (plus 6 near-limit alerts, which are not breaches).
  EV_CHARGER_NIGHT_ON catches 7 of 7. Both rules are post-hoc.

## 4. Bill reconciliation (src/bills.py, year-specific tariffs)

- 9 metered hotels, 756 bills (re-run 15 Nov after the revised-bill and tariff-date fixes): **713 reconciled**, 34 meter-fault months, 8 provisional, 1 Check.
  The Check is the revised Gurugram bill for Nov 2020 (kVAh 1.5 % below the meter); it was counted as a provisional bill before the fix (9 provisional). Its original row stays
  Reconciled and is marked `superseded`. Billed minus corrected over fault months: GGN −₹2.37 lakh (billed low, 23 months), GOA −₹5,400 (4 months), other hotels +₹1,900–2,300 each.
  These are dispute candidates, not savings, and no bill was altered.
  **Earlier figures explained (15 Nov):** the previous text (GGN −₹2.29 lakh, +₹1,900–2,300 for "every other hotel") was stale and incomplete, not a different result. It came from a first run
  (GGN −₹2,28,695) made before `clean_tariffs` was changed to recover a missing rate from the bills it applied to instead of only interpolating between years; GGN has one such imputed rate.
  The final cleaned tables give −₹2,37,220, and the text was not updated. Putting the interpolation back in a scratch copy reproduces −₹2,28,695 exactly. Goa was −₹5,423 in every run; the old text left it out
  of the range. The 9 → 8 provisional and 0 → 1 Check change is the revised-bill fix: reverting it gives 713 / 34 / 9 / 0. Source: the 14 Nov bills runs in the original large-pack session's transcript.
  Re-cleaning from the raw pack gives tables identical to the saved ones, so the current figures stand.
- Provisional bills: 8 bills priced ₹12.2 lakh above the meter-based figure; median kVAh 14.6 % high.
- Tariff-only check on all 3,000 sites (no meter exists for most): **99 % of 249,102 Actual bills reproduce within 1 % on every line**; 0 of 2,498 provisional do.
  About 30 sites have a tariff-sheet contract demand 100 kVA different from the bill (2,514 bills), and 89 % of those fail the check.

## 5. Day-ahead kVA forecast, Gurugram (src/forecast.py, leave-one-year-out)

| Metric | Large pack | One-year pack |
|---|---|---|
| Daily-peak MAPE | 5.6 % | 5.4 % |
| Days within ±5 % | 56 % | 59 % |
| Hourly kVA CV(RMSE) | 8.0 % | – |
| Days actually > 1,000 kVA | 15 (14 flagged) | 3 |
| Days actually > 920 kVA | 20 (19 flagged) | – |

The 90 % upper-bound multiplier is 1.32 (was 1.16), so the warning band is wider: 388 of 2,557 days (15 %) are WARNING or BREACH RISK, against 20 days that really exceeded 920 kVA (about 5 % precision).
That is warning fatigue. I did not change the design.

## 6. IPMVP Option C (adjusted baseline)

Minimum verifiable saving over a reporting year at the usual 50 % uncertainty: 1.0 % of load (1.5 % at GGN). Placebo test: "verify" Oct 2025 – Sep 2026, where the true saving from a measure is zero.

| | GGN | JAI | GOA | UDR | JA2 | JA3 | GO2 | GO3 | GO4 |
|---|---|---|---|---|---|---|---|---|---|
| Baseline fitted on 6 years, "saving" % | −3.1 | −3.2 | −1.2 | −3.5 | −2.0 | −2.5 | −1.5 | −1.2 | −1.1 |
| Baseline fitted on 12 months before, "saving" % | −0.6 | −2.0 | +2.0 | −2.0 | −1.3 | −1.6 | +1.8 | +2.1 | +1.7 |

The last year's actual use is 1–3 % **above** a baseline fitted on older years (the pack adds about 1.2 %/yr growth, plus real waste in the final year). A 6-year-old baseline would
report negative savings; the 12-month pre-period reduces but does not remove the bias (Goa-type hotels swing positive). Verified savings need the baseline refitted on the period just before go-live,
and any claim under about 2 % at these hotels is within the placebo error. `savings.plan()` (sized measures) was not run: it needs the web-app frames, which are built only from the one-year pack.

## Not done

Notebooks 01/02 (cleanliness, EDA) were not re-run on the large pack (section 1 replaces 01); the UI, assistant and alert cards were not rebuilt; the residual layer for the four hotels without sub-meters;
re-tuning anything.
