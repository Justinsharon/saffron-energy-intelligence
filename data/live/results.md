# Live year (Oct 2026 – Sep 2027): pipeline results

> **Robustness check on synthetic data, not a clean held-out test.** The live year is generated (`tools/make_live_year.py`) and its anomalies were injected with the type mix and rates of the *full* original label set, including labels from 1 Apr 2026. The models are not refitted: detector profiles and thresholds, the recalibration fit and the baseline were all fitted on Oct 2025 – Sep 2026 (`tools/run_live_year.py`). The only refreshed input is the tariff sheet (₹ rates +3 %).

## Detector (frozen), scored with `evaluation.score`

| metric | original held-out (Apr–Sep 2026) | live year | target |
|---|---:|---:|---|
| Precision (alert overlaps a labelled waste anomaly, same site) | 98% | 88% | ≥ 70 % |
| Precision, type-matched | 96% | 83% | |
| Recall, High + Medium | 96% (46) | 99% (73) | ≥ 80 % |
| Recall, all severities | 96% | 99% | |
| Time to detect, High, median, from first appearance in the data | 1.0 h (13 scored) | 1.0 h (22 scored, max 1.0 h, 100% ≤ 2 h) | < 2 h |
| Time to detect, High, median, from label start (secondary) | 3.0 h | 1.0 h | |
| Alerts / waste labels | 105 / 69 | 181 / 107 | |
| Labelled ₹ found (share of excess cost on detected labels) | 94% | 96% | |
| Meter-data-fault labels found by the fault stream | 2 / 2 | 3 / 3 | all |

High labels: 28; onset found 25, pre-alerted 3, no scoreable onset or no alert 3. Label start → onset median 0.0 h.

### Recall by label type (live)

| type | labels | detected | pre-alerted | median TTD from label start |
|---|---:|---:|---:|---:|
| AHU_SCHEDULE_OVERRIDE | 16 | 16 | 0 | 2.0 h |
| CHILLER_ON_LOW_LOAD | 25 | 25 | 0 | 2.0 h |
| CHW_SETPOINT_LOWERED | 8 | 8 | 0 | 1.0 h |
| CONTRACT_DEMAND_BREACH | 3 | 2 | 2 | — |
| EVENT_LIGHTING_LEFT_ON | 9 | 9 | 0 | 2.0 h |
| EV_CHARGER_FAULT | 2 | 2 | 2 | — |
| KITCHEN_EXHAUST_LEFT_ON | 10 | 10 | 0 | 3.0 h |
| LAUNDRY_PEAK_TARIFF | 19 | 19 | 0 | 1.0 h |
| POOL_PUMPS_24H | 3 | 3 | 0 | 3.0 h |
| POWER_FACTOR_DROP | 3 | 3 | 0 | 1.0 h |
| SIMULTANEOUS_HEAT_COOL | 9 | 9 | 2 | 1.0 h |

### Precision by rule (live)

| rule | alerts | overlap a label | type-matched |
|---|---:|---:|---:|
| AHU_HAND_MODE | 26 | 88% | 85% |
| CHILLER_PART_LOAD_INEFFICIENCY | 47 | 91% | 91% |
| CHILLER_STAGING_LOW_LOAD | 25 | 96% | 96% |
| CHW_SETPOINT_LOW | 9 | 100% | 100% |
| HEAT_COOL_FIGHT | 17 | 94% | 53% |
| KITCHEN_EXHAUST_OFF_HOURS | 10 | 100% | 100% |
| LAUNDRY_IN_PEAK | 19 | 100% | 100% |
| LIGHTING_LEFT_ON | 10 | 90% | 90% |
| POOL_PUMP_OFF_SCHEDULE | 3 | 100% | 100% |
| POWER_FACTOR_DROP | 3 | 100% | 100% |
| RESIDUAL_UNEXPLAINED | 12 | 0% | 0% |

## With the post-hoc rules (alert cards: detector + demand/EV + kW/TR staging)

Precision 84% over 222 alerts; recall High+Medium 100%, all 100%; labelled ₹ found 100%. Post-hoc alerts: {'STAGING_KWTR': 26, 'DEMAND_NEAR_CONTRACT': 13, 'EV_CHARGER_NIGHT_ON': 2}. These rules were written after the original held-out window was seen, so they are post-hoc there too.

## Meter faults (T5)

- GGN 13 Aug 2027 11:00 – 16:00: flat line, detected 12:00; billed kWh frozen at 131.45 for 19 intervals while kW stays live (mean 508 kW)
- JAI 22 Jul 2027 00:00 – 10:00: flat line, detected 03:00; 10 h with flat line on the billed meter
- GOA 13 Sep 2027 19:00 – 06:00: flat line, detected 22:00; 11 h with flat line on the billed meter

Alert cards overlapping a detected fault window: 0 (must be 0).

## Baseline (fitted on Oct 2025 – Sep 2026, predicting the live year)

ASHRAE Guideline 14 targets: hourly CV(RMSE) < 30 %, monthly < 15 %, NMBE within ±5 %. Original = leave-one-month-out on its own year.

| hotel | hourly CV(RMSE) orig → live | monthly CV(RMSE) orig → live | NMBE (hourly) orig → live | monthly NMBE live | valid hours | pass |
|---|---:|---:|---:|---:|---:|---|
| GGN | 8.3 % → 8.5 % | 3.4 % → 2.7 % | +0.08 % → +1.74 % | +1.91 % | 8,713 | yes |
| GOA | 5.4 % → 5.2 % | 2.8 % → 2.4 % | +0.02 % → +0.87 % | +0.94 % | 8,697 | yes |
| JAI | 5.0 % → 4.7 % | 1.1 % → 1.2 % | -0.06 % → +0.53 % | +0.58 % | 8,728 | yes |

The live load includes +1.2 % growth and the injected waste, which the baseline (fitted a year earlier) does not know about; a positive NMBE (actual above prediction) is the expected direction.
