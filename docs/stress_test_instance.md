# Stress-test data: handoff for the injection and testing instance

Written 14 Nov 2026. Read `CLAUDE.md` and `CONTEXT.md` first; this file only adds what is specific to the large pack and the stress-test work.

## 1. Where things stand

- `data/large/` (16 CSVs, ~355 MB, 210k–256k rows each) is a **synthetic seven-year pack** (Oct 2019 – Sep 2026) built by `tools/make_large_dataset.py`
  (seeded, ~30 s). Only the last year of GGN / JAI / GOA is the real workbook data; earlier years are whole-week resamples of it. Full description,
  site coverage and planted data-quality faults: `data/large/README.md`. The answer key for planted faults is `data/large/_injected_issues.csv`.
- **Another Claude instance is analysing this pack right now** (14 Nov, ~22:40 IST). It has written `src/clean_large.py` → `data/clean_large/*.parquet`
  (cleaning finished 22:39) and `tools/large_run.py` (stages `check baseline detector bills all`, writes `data/clean_large/results/`). It sets
  `PS12_DATA=clean_large` so `src/*` read the large pack instead of `data/clean`. Baseline, detector and bills outputs had not appeared when last
  checked. **Do not touch `data/large/`, `data/clean_large/`, `src/clean_large.py` or `tools/large_run.py`** until that instance is idle.

## 2. Are more rows needed? No

| File(s) | Rows | Verdict |
|---|---|---|
| `gurugram_15min`, `gurugram_submeters_15min` | ~246k each (1 site) | Plenty for baseline, day-ahead kVA forecast, stacking watch |
| `jaipur_hourly`, `goa_hourly`, `jaipur_goa_submeters_hourly`, `weather_hourly` | ~246k each (4 sites) | Plenty; extra sites test generalisation |
| `anomaly_labels` (metered sites only) | 1,364 | Fine for common types (GGN 30–90 each; chiller-on-low-load 25–50 per site) |
| `events`, `occupancy_daily`, `bms_*`, `equipment_register` | 235k–256k | Fine, mostly portfolio padding |
| `monthly_bills` (252k), `tariffs` (210k) | | Row count comes from 3,000 sites; only 9 have meter data, so only ~750 bills can be reconciled |

The limit is independent information, not rows: seven years from one real year means no new weather regimes, event mixes or failure modes.

Rare anomaly types on the nine metered sites over seven years: `EV_CHARGER_FAULT` 7 (GGN only), `CONTRACT_DEMAND_BREACH` 15 (GGN only),
`POWER_FACTOR_DROP` 35 (5 sites), `METER_DATA_FAULT` 69 (9 sites). Enough to sanity-check the post-hoc rules in notebook 08, too few to tune
thresholds. The cause is the per-year rates copied from the original labels (2–3 a year); regenerating would repeat them.

## 3. What to add instead (stress-test pack)

Priority order; items 2 and 3 test the two guardrails the brief cares most about.

1. **Rare GGN anomalies, varied.** EV charger night draw at several powers and durations (2 kW × 3 h, 12 kW × 8 h, a stuck-on weekend);
   contract-demand breaches from different causes (laundry + banquet AHU stacking, chiller restart after a power cut, DG-to-grid changeover);
   PF drops of different depth and shape (0.93, 0.82, slow drift over weeks); meter faults of new kinds (intermittent flicker, a fault starting
   during a DG hour).
2. **Hard negatives** (must **not** alert): 41 °C day + 300-guest wedding + 95% occupancy; January cold snap with legitimate pool heating;
   holiday weekend occupancy jump; planned chiller changeover for maintenance.
3. **Different weather years** (not resampled weeks): heatwave year (+2 °C summer, long 40 °C+ run); weak and very wet monsoon; early or late winter.
4. **Business changes:** renovation year (30 rooms closed); a more efficient chiller replacing an old one (tests IPMVP Option C baseline
   adjustment); a mid-period tariff change (tests bill reconciliation).
5. **Bill-reconciliation edge cases (metered sites only):** components off by a few rupees vs hundreds; provisional bill then revision; a
   meter-fault month where the bill is wrong but rebuilt kW is right.

## 4. Rules for this work

- **Write to a new folder, e.g. `data/large_stress/`.** Never edit or regenerate `data/large/` in place: it is seeded and reproducible, and the other
  instance's results depend on it. Give the new folder its own `README.md`, labels file and an issues/answer-key file; mark every injected case.
- Write the generator as a new script (e.g. `tools/make_stress_dataset.py`), seeded, that takes `data/large/` or `data/clean/` as input and does
  not modify it. Keep sub-meters, main meter, bills, labels and command log consistent for the nine metered sites.
- **The detector stays frozen** (`src/detector.py`). Run it on the stress pack as a robustness check and report results as such. Do not tune on this
  pack and then call the numbers clean held-out: the injected types and rates derive from the full label set, including labels from 1 Apr 2026.
  Anything changed after looking is post-hoc and must be labelled so.
- Honour the data rules in `CLAUDE.md`: `exclude_from_model`, `is_imputed`, `is_dg`, `is_provisional`, `ends_after_midnight`; per-hotel ToD windows;
  total site energy = `grid_kwh + dg_kwh`; never "fix" bills; pool winter rise and CHW 5.5 °C hours are real.
- Product guardrails still apply to anything the instance produces: recommend, never control; no CHW setpoint < 6.5 °C; no alert for weather,
  occupancy or event-explained conditions; meter faults suppressed; LLM text states only facts in the data.
- Windows: run everything through `uv run python ...`; set `PYTHONIOENCODING=utf8` when printing ₹ / ° / ×.

## 5. Model choice for the instance

- **Generator design and writing: Opus 5.5** (or Fable 5.2 if cost is no object). Cross-table consistency, leakage awareness and building hard
  negatives that look like waste but are explained are easy to get subtly wrong, and a flawed generator corrupts every result downstream.
- **Running the frozen detector, scoring, comparison tables: Sonnet 5.5.** Mostly executing existing code and checking numbers against known answers.
- **Haiku 5.5:** only mechanical jobs (reformatting, running build commands).

## 6. Done when

- `data/large_stress/` exists with a README, labels and answer key, and `data/large/` is byte-for-byte unchanged (check with `git status` /
  timestamps).
- The frozen detector has been scored on it: precision, recall, time-to-detect (onset definition, `evaluation.onset_ttd`), and false alerts on every
  hard negative reported separately.
- Results and any post-hoc observations are logged in `CONTEXT.md` §18, clearly labelled as stress-test, not held-out.

## 7. Status (15 Nov)

Done: `data/large_stress/` (README, `_stress_cases.csv`, 17 labels), `tools/make_stress_dataset.py`, `tools/stress_run.py`, results in `docs/stress_pack_results.md`.
`data/large` and `data/clean_large` were not modified by the generator (asserted on every run). Frozen detector scored: 12 of 12 planted anomalies caught, 5 of 7 hard negatives quiet,
whole-pack precision 89.6 % / recall 98.7 % / median time to detect 1 h. Three post-hoc fixes came out of it (tariff by date, gain-error check, revised bill); they are labelled post-hoc and are not held-out.
Note: the 15 Nov large-pack bill re-run overwrote `data/clean_large/results/bill_reconciliation.parquet`. The earlier docs figures (GGN −₹2.29 lakh) were a stale first run, now explained in `docs/large_pack_results.md` §4. Back up result files before re-running.
Not done: forecast, savings plan, assistant and UI on the stress pack; flicker and alternate-blank meter faults; hourly-meter gain check.
