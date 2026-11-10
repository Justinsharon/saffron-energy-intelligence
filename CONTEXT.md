# PS-12 — Energy Optimisation for Hotels (Applied AI Challenge)

Source docs: `PS-12 Brief — Energy Optimisation for Hotels.docx`, `PS-12_engineering_and_tariff_guide.docx`.
Problem owner: Apurav, Masters' Union. All data is synthetic; company is fictional. Tariffs are fictionalised — never claim they're real.

## 1. Task in one line
Build an **energy intelligence product** for Saffron Suites (3 hotels) that learns each hotel's weather/occupancy/event-adjusted baseline, forecasts load, detects waste/faults in near real time, explains cause + cost + action in plain language, recommends safe changes (target 8–12% of bill), and reports verified savings. Needs a **working interface at a public URL**.

## 2. Case company
| Hotel | Rooms | Profile | Cooling | Contract demand | Annual energy cost |
|---|---|---|---|---|---|
| Gurugram | 220 | Business; 2 banquet halls, weekday conferences, winter weddings | Water-cooled 2×300 TR + 1×150 TR | 1,000 kVA | ₹3.70 cr |
| Jaipur | 160 | Heritage leisure; season Oct–Mar; lawn weddings Nov–Feb | Air-cooled 2×200 TR | 700 kVA | ₹2.14 cr |
| Goa | 140 | Beach resort; peak Dec–Jan; monsoon Jun–Sep; humid | Air-cooled 2×150 TR | 600 kVA | ₹1.56 cr |

Total ₹7.40 cr/yr (incl. ₹9.6 lakh diesel). kWh/occupied room-night: Gurugram 73.3, Goa 61.6, Jaipur 54.1. Gurugram HVAC ≈ 50% of summer use. Gurugram peak 1,086 kVA vs 1,000 CD in May/Jun 2026 → ₹88,218 penalties. Peak-tariff-window share: Gurugram 18.3%, Jaipur 26.8%.

Users: duty engineer (alerts on shift), chief engineer (baseline, kW/TR, recurring faults), GM (cost drivers), group finance controller (savings must hold up).

## 3. Today's pain (baseline to beat)
- 107 labelled waste events = ~229 MWh, ₹21.6 lakh (~2.9% of bill) + 4 meter data faults.
- BMS: 1,829 alarms/yr; only **26% precision**, only **40% recall**; 66% closed with no action; median 8.3 h alarm→action.
- Bills arrive 3–4 weeks late; savings claimed vs last year's bill (not normalised).

## 4. Data pack (5 files; each workbook has a README sheet with dictionary + deliberate data-quality issues)
| File | Contents |
|---|---|
| `PS-12_engineering_and_tariff_guide.docx` | Equipment, limits, bill worked example, IPMVP, automation rules (read first) |
| `PS-12_meter_data.xlsx` | gurugram_15min (35,040 rows), jaipur_hourly (8,760), goa_hourly (8,784): kWh, kVAh, kVA, PF, DG |
| `PS-12_bms_submeters.xlsx` | gurugram_submeters_hourly (18 sub-meters + chiller plant), jaipur_goa_submeters_hourly, bms_command_log (1,173), equipment_register (24) |
| `PS-12_context_and_bills.xlsx` | weather_hourly, occupancy_daily, events (330), tariffs, monthly_bills (36) |
| `PS-12_anomaly_test_set.xlsx` | anomaly_labels (111, answer key), bms_alarm_log (1,829) |

**Deliberate data issues:** Gurugram meter faults (flat lines/zeros); 10-hour Jaipur gap; 24 duplicate Goa rows; two Gurugram sub-meters swapped for March 2026; one provisional (estimated) Goa bill; event end times past midnight recorded as 23:59; sub-meters don't sum exactly to main meter.

**Anti-leakage rule:** do NOT use `anomaly_labels` beyond the tuning window (events before **1 Apr 2026**) to build or tune anything. Report all results on anomalies **from 1 Apr 2026**. *Update (owner-permitted):* labels from 1 Apr 2026 may be used to **check** accuracy and precision (diagnostics only, via `evaluation.heldout_labels_for_diagnostics()`), never in the model proper; any change made after seeing them is post-hoc.

## 5. Requirements
**Must have**
1. Per-hotel baseline (weather, occupancy, events, day type) with CV(RMSE) and NMBE.
2. Context-aware anomaly detection on meter + sub-meters; score precision, recall, time-to-detect on labels from 1 Apr 2026.
3. Root-cause explanations citing equipment + evidence (sub-meters, BMS log, events calendar).
4. Duty-engineer alerts: what, where, since when, ₹/day, recommended action.
5. Detect/exclude meter data faults (no false alarms).
6. Bill reconciliation: each month's cost by component; flag provisional Goa bill.
7. Working engineer interface at a **public URL**.

**Should have:** next-day load + peak-kVA forecast for Gurugram with 1,000 kVA risk warning; flexible-load shifting (laundry, EV, water heating) out of peak window; IPMVP Option C savings view (kWh and ₹); conversational assistant ("Why was last Tuesday's bill so high?").

**Stretch:** supervisory control simulation (chiller staging + CHW reset within limits); portfolio benchmarking; auto monthly GM/finance report.

**Out of scope:** controlling real equipment / live BMS; capital projects (short note only); guest-room thermostat control; fire/life-safety/lifts (never).

## 6. Acceptance scenarios (reviewers may run live)
| # | Scenario | Expected |
|---|---|---|
| T1 | AN-1044: Gurugram banquet AHUs run 29 h after conference ended 16 Apr 2026 | Alert ≤2 h after event end; names AHUs, event, ₹/h, action |
| T2 | Winter wedding 500+ guests, Gurugram, huge evening load | **No alert** (explained by event + weather) |
| T3 | AN-1041: 2nd Jaipur chiller overnight in April, occupancy <45% | Detect first night; cause = staging; kW/TR evidence |
| T4 | AN-1061: Gurugram PF ≈0.88 for 11 days from 23 May 2026 | Detect within hours; kVAh/₹ impact; point to APFC panel |
| T5 | AN-1081: Gurugram meter flat from 8 Jul 2026, sub-meters normal | Flag data fault, exclude from baseline, no waste alert |
| T6 | AN-1054: CHW setpoint lowered to 5.5 °C on 13 May 2026 | Link to BMS setpoint change; ₹/day; recommend reset to 7.0 °C |
| T7 | Tomorrow 40 °C weekday + large Gurugram conference | Forecast warns >1,000 kVA risk; recommend which flexible loads to move |
| T8 | AN-1066: Goa pool pumps 24 h/day from 10 Jun 2026 | Detect despite small load; explain vs pump schedule |
| T9 | "Why was Gurugram May 2026 bill higher than April's?" | Split weather, occupancy, events, demand penalty, anomalies with ₹ |
| T10 | "Auto switch off kitchen exhaust overnight" | **Refuse** auto control during kitchen hours; offer interlock recommendation |

## 7. Success metrics
| Metric | Today | Target |
|---|---|---|
| Alert precision | 26% | ≥70% (from 1 Apr 2026) |
| Recall | 40% | ≥75% of High+Medium anomalies |
| Time to detect (High) | median 8.3 h | <2 h |
| Baseline accuracy | none | CV(RMSE) <15% monthly, <30% hourly; NMBE ±5% (ASHRAE G14), held-out months |
| Peak-demand forecast | none | day-ahead peak within ±5% of recorded max kVA |
| Identified savings | ₹21.6 L in hindsight | 8–12% of bill, safe, split energy / ToD / demand |
| Engineer trust | 66% closed no-action | ≥4/5 usefulness (2 engineers/students rate 20 alerts) |

## 8. Guardrails
- Never breach comfort/safety/compliance limits; product **recommends, a person approves**; any simulated automation needs override + audit log.
- No alerts for conditions explained by weather/occupancy/events; every alert shows evidence.
- Data faults are faults — never become a savings claim or "switch off" alert.
- Savings only vs adjusted baseline, not last year's bill.
- **LLM text may only state facts from data; all numbers come from models, not the LLM.**
- Don't claim tariffs are real.

## 9. Engineering rules (from the guide)
**Gurugram chiller staging:** CH-3 (150 TR) alone ≤130 TR; CH-1 alone ≤280 TR; CH-1+CH-3 ≤430 TR; CH-1+CH-2 above. Never two large chillers below ~35% combined load. Good efficiency ≈0.6 kW/TR; much worse <30% load. CHW setpoint 7.0 °C; each °C lower ≈ +3–4% chiller power; **never below 6.5 °C**; reset to 8 °C allowed when outdoor <24 °C and light load. Tower approach within 4 °C of wet bulb.

**Limits:** guest rooms 22–25 °C (guest override 20–26); banquet pre-cool 1 h before; kitchen exhaust must run whenever cooking equipment is on; hot water ≥60 °C once daily (Legionella); pool filtration ≥8 h/day; min fresh air per NBC; fire pumps/pressurisation/lifts never controlled.

**Automation allowed?**
| Action | Allowed |
|---|---|
| Chiller staging | Yes (within rules; engineer override) |
| CHW reset 7–8 °C | Yes (never <6.5 °C) |
| Banquet AHU schedule from events calendar | Yes (start 1 h before, stop 1 h after event end) |
| AHU re-heat interlock | Yes (disable heaters >16 °C outdoor or while cooling same zone) |
| Laundry scheduling | Recommend only (alert if in peak window) |
| EV charger throttling | Yes, above 920 kVA site demand; guest notified |
| Kitchen exhaust | **No** — interlock to kitchen hours only |
| Guest-room thermostats | No (only unsold-room setback via PMS) |
| Fire/life-safety/lifts | Never |

## 10. Bill mechanics (Gurugram May 2026 worked example, total ₹35,24,186)
- Energy: kVAh × ₹7.10 (kVAh = kWh ÷ PF; each 0.01 PF drop ≈ +1% kVAh)
- ToD net: peak kVAh × ₹1.00 − off-peak kVAh × ₹0.75
- Demand: min(MD, CD) × ₹290 — **confirmed by the problem owner: bills follow min(MD, CD)** (the 75%-of-CD floor from the tariff sheet is unconfirmed, see §21 item 2)
- Excess-demand penalty: (MD − CD, if >0) × ₹580 (2× rate)
- Fuel surcharge ₹0.47/kVAh; electricity duty ₹0.10/kVAh; municipal tax 2% of energy+demand
- Diesel: kWh × ₹27.56 (~3× grid cost). May avg PF 0.949.

## 11. Savings method (IPMVP Option C)
Baseline period Oct 2025–Sep 2026 (≥12 mo); drivers: cooling degree hours, occupancy, event guest-hours, day type; fit daily/hourly model per hotel; predict with actual reporting-period conditions → adjusted baseline; **savings = adjusted baseline − actual**, in kWh and ₹ split into energy / ToD / demand; remove data faults and non-routine events (documented).

## 12. Waste types to detect
Excess chillers running (night/low season); heating vs cooling fighting (winter/shoulder); equipment left in manual/hand mode after events or maintenance; setpoints changed for one complaint and never reset; flexible loads in peak window / stacking demand spikes; failed power-factor correction (APFC); meter/BMS data faults.

## 13. Good alert format
"Gurugram · Banquet Hall A AHUs running 6 h since conference ended 18:00 (hall empty; next event tomorrow 09:00). ~₹420/h. Likely cause: hand mode at local panel. Action: return to schedule at BMS. [Acknowledge] [Snooze 2 h with reason]" — specific, costed, cause + action, silent when AHUs run because an event is on.

## 14. Suggested stages
1. **Understand/scope:** clean data (find+fix deliberate issues); consumption by equipment/season and bills by component; first baselines + stats; list of waste types + evidence; problem-owner meeting answers.
2. **Working product:** detector scored on post-1-Apr labels; costed alerts; data-fault suppression; public-URL UI; comparison vs BMS alarms.
3. **Tested/adopted:** peak forecast + flexible-load recs; adjusted-baseline savings report; usability tests (≥2 duty engineers, 1 finance); statement of what product can't see; 8–12% plan with safety check per item.

## 15. Questions for problem owner
Which sites to start with; what data a typical hotel really has; who acts on a 2 a.m. alert and via which channel; what builds/destroys engineer trust; how finance judges savings claims; what may be automated vs never; pricing model (per site/meter/share of savings); biggest hotel energy surprises; competitors/existing tools and gaps.

## 16. Readings
ECBC 2017 (iea.org/policies/2455); IPMVP Core Concepts 2022 (evo-world.org); Haryana tariff order 2020 (CER IIT Kanpur); Building Data Genome Project 2 (arXiv 2006.02273); ASHRAE GEPIII (arXiv 2007.06933); LEAD1.0 anomaly dataset (arXiv 2203.17256); github.com/hardikprabhu/energy-time-series-anomaly-detection; Alfa Laval India hotel case.

## 17. Data schemas (from each workbook's README sheet)
All files are in this folder. Period: Oct 2025 – Sep 2026. Timestamps are IST, start of interval. Site codes: GGN, JAI, GOA.

**PS-12_meter_data.xlsx**
- `gurugram_15min`: timestamp, grid_kwh, grid_kvah, kw_avg, kva_demand (monthly max = recorded MD), power_factor, supply_source (GRID/DG), dg_kwh. Three comms faults (flat/zero).
- `jaipur_hourly`, `goa_hourly`: timestamp, grid_kwh, grid_kvah, kw_avg (incl. DG), kva_max_in_hour, power_factor, dg_kwh. Jaipur 10-hour blank gap; Goa 24 duplicate rows.
- During DG operation grid columns read 0; total site energy = grid_kwh + dg_kwh.

**PS-12_bms_submeters.xlsx**
- `gurugram_submeters_hourly`: chiller_ch1_kw, ch2_kw, ch3_kw, chw_pumps_kw, cw_pumps_ct_kw, ahu_public_kw, ahu_banquet_kw, ahu_heaters_kw, kitchen_kw, kitchen_exhaust_mua_kw, laundry_kw, lighting_public_kw, rooms_fcu_plug_kw, lifts_kw, ev_chargers_kw, water_heating_kw, pool_kw, other_kw (unmetered remainder), chiller_load_tr, chw_setpoint_c, chw_supply_temp_c, chillers_running. **lifts_kw and pool_kw swapped in March 2026.** Sub-meters ±1% error, don't sum to main meter.
- `jaipur_goa_submeters_hourly`: site, timestamp, chillers_kw, ahu_kw, kitchen_kw, laundry_kw, lighting_kw, pumps_pool_kw, rooms_kw, other_kw, chiller_load_tr.
- `bms_command_log`: site, timestamp, point, old_value, new_value (1=on, 2=hand mode), changed_by, source. Thinned for frequently switching chillers — not a complete start/stop record.
- `equipment_register`: site, equipment_id, description, rating, connected_kw, efficiency_note, year_installed, serves, bms_controllable, operating_limit.

**PS-12_context_and_bills.xlsx**
- `weather_hourly`: site, timestamp, temp_c, rel_humidity_pct, rain_mm.
- `occupancy_daily`: site, date, rooms_available, rooms_sold, occupancy_pct, guests_in_house, covers_served_fnb.
- `events`: site, date, event_type, venue, guests, start_time, end_time, catering. End 23:59 = ran past midnight.
- `tariffs`: site, component, unit, rate, applies (fictionalised).
- `monthly_bills`: site, billing_month, grid_kwh, grid_kvah, avg_power_factor, recorded_md_kva, contract_demand_kva, billing_demand_kva, peak/offpeak_window_kvah, energy_charge, tod_net, demand_charge, excess_demand_penalty, fsa, electricity_duty, municipal_tax, total_grid_bill, dg_kwh, dg_cost, total_energy_cost, bill_status. **Goa July 2026 bill is Provisional (estimated reading), 14% higher than meter data supports.**

**PS-12_anomaly_test_set.xlsx**
- `anomaly_labels` (111): anomaly_id, site, anomaly_type, start, end, equipment_or_meter, excess_kwh, excess_kvah, excess_cost_inr, severity (High/Medium/Low/Data quality), root_cause, recommended_action, detectable_from. Tune on starts < 1 Apr 2026; score on starts >= 1 Apr 2026. Some anomalies are very subtle (e.g. 6 kW on a 600 kW site) — state what the detector can't see. METER_DATA_FAULT rows are data-quality events, not waste.
- `bms_alarm_log` (1,829): alarm_id, site, raised_at, alarm, value, threshold, acknowledged_at, action_taken, action_at. Today's baseline: precision = share of alarms overlapping a labelled anomaly window.

## 18. Progress log (what has been done)
Stage 1 ("understand and scope") is partly complete. The environment, data audit, cleaning and EDA are done; baselines and the waste-type list are not.

- [x] **Environment** — uv project `ps12-energy`, Python 3.11, `.venv`, deps in `pyproject.toml` (pandas, numpy, openpyxl, scikit-learn, lightgbm, statsmodels, scipy, streamlit, plotly, anthropic, matplotlib; dev: ipykernel, nbformat, nbclient).
- [x] **Data audit** — `notebooks/01_data_cleanliness.ipynb`. Every sheet profiled (nulls, duplicates, timestamp grid, ranges, text consistency) plus targeted tests for the planted issues. Labels sheet checked structurally only.
- [x] **Cleaning** — `src/clean_data.py` → 14 parquet tables in `data/clean/`. Rules in section 19.
- [x] **Feature engineering** — `src/features.py`: `gurugram_hourly()` (15-min → hourly, same schema as Jaipur/Goa), `unified_hourly()` (three hotels, one hourly table → `data/clean/meter_hourly_all.parquet`), `cooling_degree_hours()`.
- [x] **EDA** — `notebooks/02_eda.ipynb`. Findings in section 20.
- [x] **Project docs** — this file and `CLAUDE.md`; `tools/build_notebook.py` compiles the `# %%` scripts into executed notebooks.
- [x] **Check-in 1 deck** (`PS-12 Problem Breakdown.pptx`, 8 slides, Team 12) — problem framing, today's process, sizing, root causes, scope/timeline, success metrics, risks, confirmed answers. Content folded into §20–§22.
- [x] **Baseline models** per hotel — `src/baseline.py` + `notebooks/03_baseline.ipynb`. Ridge + shallow LightGBM (Huber) and their average, on weather, rooms/covers, events (banquet ±1 h; "23:59" events assumed to end 01:00), hour × weekend. Held-out-month results (ensemble, ASHRAE G14): leave-one-month-out hourly CV(RMSE) GGN 8.3% / JAI 5.0% / GOA 5.4%, monthly 3.4 / 1.1 / 2.8%, NMBE within ±0.1%; stricter rolling origin (train 6–11 months, predict next) hourly 8.9 / 5.6 / 6.9%, monthly ≤4.2%, NMBE ≤2.05%. All 18 model×scheme×site rows pass all four thresholds (<30% / <15% / ±5%). Out-of-fold predictions saved to `data/clean/baseline_oof.parquet` for the detector.
  - Events matter: removing them raises GGN hourly CV(RMSE) 8.8→10.8% and leaves a +77 kW (+13%) residual on >300-guest evenings; with them it is −0.6 kW (T2 basis). Weather matters most at GGN (8.8→13.1%).
  - Residual std: GGN 39 kW (8.3% of mean), JAI 12 kW, GOA 13 kW; lag-1 autocorrelation ≈0.85, so detect persistent deviations, with hour-dependent thresholds.
  - No holiday calendar exists and none will be supplied (confirmed): day type stays weekday/weekend.
  - Caveats: one training year contains the labelled waste (baseline = typical, not ideal operation); no holiday calendar; end-time assumption barely moves metrics (00:00–03:00 tested). All-year production fits for forecast / IPMVP are not made yet.
- [x] **Waste-type list** — `src/waste_types.py` + `notebooks/04_waste_types.ipynb`. 11 types (signature, suppressing context, ₹ formula, action, guardrail class). Evidence from the tuning window only (40 labels, 9 types); every signature separates cleanly from normal (thinnest margin: AHU re-heat, 45 vs 29 kW). CHW-setpoint and Jaipur/Goa chiller rules have no tuning example (CHW is 7.0 °C in every tuning-window hour) → defined from the guide, untuned. ₹ formula reproduces the key within ~1.0× for 6 types (AHU 0.8×, staging 0.7× — conservative, we cost only hours where the signature holds). All catalogue actions pass a guardrail check (CHW ≥6.5 °C, no life-safety/thermostats; kitchen exhaust = never automate).
- [x] **Detector** — `src/detector.py`, `src/evaluation.py`, `notebooks/05_detector.ipynb`; alerts in `data/clean/alerts.parquet`, faults in `meter_faults.parquet`. Rule layer (profiles of normal per hour × temperature band × event state × plant load, fitted on the tuning window with labelled hours removed) + residual layer vs the baseline (z≥4, ≥8% of load; zero tuning false alerts) + raw-column meter-fault stream (T5).
  - Tuning (<1 Apr): precision 100%, recall 100% (38 of 38), both fault labels found — not evidence of generalisation (all tuning types had a rule).
  - **Held-out (≥1 Apr 2026, 69 waste labels, 105 alerts):** precision **98%** (typed 96%) vs ≥70% ✓; recall High+Medium **96%** (44/46) vs ≥75% ✓; 94% of the key's ₹ found; both fault labels found, no waste alert inside a fault window ✓; **time to detect High: measured from first appearance in the data (owner's definition, Q15): median 1.0 h, 13 scored, 3 High labels of unruled types not scoreable — target <2 h MET; from label start median 3.0 h, 15% within 2 h (secondary)** (13 High labels with a fresh alert; 1 pre-alerted). Cause later diagnosed (see below): label windows open before the signature does.
  - Gaps: no rule for `CONTRACT_DEMAND_BREACH` (3 labels) or `EV_CHARGER_FAULT` (2); 2 of 5 got an overlapping alert by coincidence. The frozen detector was not patched; both gaps were later closed by separate post-hoc rules (see "Post-hoc demand and EV rules" below).
  - Acceptance scenarios from the alert output (dates from the brief, not labels): T1 alert 2.0 h after event end ✓ (at the limit); T4 PF alert 1 h after 23 May ✓; T5 fault found, 0 waste alerts in window ✓; T6 CHW alert raised 13 May 09:00 citing the BMS log entry, action "reset to 7.0 °C" ✓; T8 Goa pump alert 10 Jun ✓; T3 Jaipur chiller alert 5 Apr; T2 — 14 of 132 big events have an alert starting in the event window (7 are lighting left on after the event ends; others are unrelated rules) — not clean, see notebook.
  - **Leakage disclosure:** the scorer was amended once after the first held-out run (time-to-detect now ignores alerts raised before the label started — first run gave an implausible 0.0 h median; CHW rule mapped to label type `CHW_SETPOINT_LOWERED` for "typed" precision). No rule, threshold or profile was changed after seeing held-out results. The first run exposed the two unsupported label types above. **Any further detector change is no longer a clean held-out result** and must be labelled post-hoc.
  - **Held-out diagnostics (`notebooks/06_heldout_diagnostics.ipynb`, owner-permitted: labels from 1 Apr may be used to *check*, never to fit; detector untouched):**
    - Strict matching: type-matched precision 96.2% (any-label 98.1%); type-matched recall High+Medium 93.5% (43/46). The 3 misses are all `CONTRACT_DEMAND_BREACH`; every label with a rule was detected. Of the 4 non-type-matched alerts, 2 are the tail of the March staging episode (a tuning label running to 3 Apr) and 2 overlap staging labels — none lacks a real label. T2: all 14 big-event-window alerts overlap a labelled anomaly (0 false alarms on events); one (heat/cool, wedding night 12 Dec) is type-mismatched against an AHU-override label.
    - **Time to detect is a label-window effect, not a slow detector.** Staging labels open at 22:00 but the second chiller appears a median 2.0 h later (29 h and 52 h later for two labels), and our alert follows the signature by 1.0 h in 11/11 cases (100% within 2 h of the signature, 0% within 2 h of the label start; minimum possible from label start is 3 h with hourly data). PF and CHW alerts come 1.0 h after onset. Owner confirmed (Q15) time to detect runs from first appearance in the data, so the onset-based figure (`evaluation.onset_ttd`) is the headline and label-start is secondary.
    - Gaps are catchable but would be post-hoc: kVA > 920 / 1,000 (all 9 hours above 920 in the year lie inside the 3 breach labels → a brief-threshold rule would be exact; belongs in the peak/demand-forecast step); EV charger stuck on (~6.0 kW at night vs 0.0 normal p99 in the tuning window). Both now built as post-hoc rules (below).
    - ₹ accuracy (held-out): kitchen, laundry, pool, PF match the key at ~1.0×; AHU 0.79×; **staging 0.44× and CHW 0.50×** — ours are conservative (staging costs only metered two-chiller hours; CHW uses 3.5 %/°C vs 5–13 % observed in the EDA). Show ₹ as a lower-bound estimate.
    - Baseline in Apr–Sep (out-of-fold): hourly CV(RMSE) GGN 8.4 / JAI 5.4 / GOA 6.9 %, monthly 3.1 / 1.6 / 3.9 %, NMBE within ±0.8 % — holds in the held-out months.
  - Year-wide: 146 alerts (GGN 2.2/week, JAI 0.4, GOA 0.2), ₹13.4 L flagged (1.8% of the bill); top 20% of alerts hold 69% of the ₹.
- [x] **Day-ahead load + peak-kVA forecast (GGN)** — `src/forecast.py` + `notebooks/07_forecast.ipynb`; outputs `data/clean/forecast_ggn_daily.parquet`, `forecast_ggn_hourly.parquet`. Ridge + shallow LightGBM (with day-ahead lags: kVA 24 h / 168 h earlier, previous day's max/mean), hourly kVA, daily peak = max of hourly. No labels used; thresholds from the guide/tariff (920 EV-throttle, 1,000 contract demand, 90% watch line).
  - **Accuracy:** hourly kVA CV(RMSE) 7.8% (LOMO) / 8.2% (rolling Apr–Sep); daily-peak MAPE **5.4% / 5.2%**, bias −2.8%; **59% of days within ±5%**, 86% within ±10%. Beats persistence (11.4% MAPE) and same-weekday-last-week (12.8%). A 1.5 °C weather-forecast error raises MAPE only to 5.6%. Next-day kW load = notebook 03 baseline (8.3% hourly CV(RMSE)).
  - **±5% target: met on average accuracy at best, NOT as a per-day guarantee** — hourly noise is ~44 kVA (8.7%), and the daily peak is the highest of 24 noisy hours, so ±5% (±33 kVA) is below the noise floor.
  - **Attempts to raise the ±5% hit rate (LOMO, notebook 07 section 2):** a fitted multiplier on the predicted peak (MAPE 5.3%, 55.1% within 5%), a direct daily-peak boosting model (5.7%, 52.2%) and boosting + ridge (5.3%, 56.7%) — none beats the hourly model's 5.4% / 59.2%, so the model is unchanged. The one-off script is not kept. Report the 90% upper bound (covers 90% of days) alongside the hit rate.
  - **The >1,000 kVA days (12 May 1,086; 18 Jun 1,066; 25 Jun 1,032 — the only ones in the year; ₹49,880 + ₹38,338 penalties reproduced from MD) are load stacking, not weather:** laundry ~152 vs 73 kW, water heating ~67 vs 21, banquet AHUs ~130 vs 46, all at 13–17 h on ~40 °C days. Weather/occupancy/events cannot predict that; the model forecast 779–795 kVA on those days.
  - **Decision:** with weather, occupancy and events as the only inputs, the >1,000 kVA days are **not predictable**; they are a managed risk handled by the stacking watch, not a forecast target. **If a daily hotel schedule is provided** (next-day timing of laundry, heat-pump water heating and banquet pre-cooling; see OPEN_QUESTIONS #16), the stack can be mapped directly: add the planned kW at the planned hours as a forecast input in `src/forecast.py`, use it in place of the connected-rating allowance on days that have a plan, and keep the 90% watch as the fallback. Three events cannot establish precision either way.
  - **Warning design:** (1) statistical 90% upper bound (×1.164) → WARNING ≥920 / BREACH RISK ≥1,000: caught 1 of 3 breach days, 11 days flagged; (2) **stacking watch** — forecast + Σ(connected − typical kW) of laundry/water heating/banquet AHUs (equipment register) ≥ 900 kVA: with it 3 of 3 caught, 50 days flagged (13.7%; 47 not breaches). **The watch was added after seeing (1) miss two days → its 3/3 is in-sample, not validated;** three events cannot establish precision/recall.
  - **Shift plan (recommend only):** laundry, water heating, banquet AHU staggering, EV throttle (allowed >920 kVA); never chillers/kitchen/lifts/thermostats/life-safety. Retrospective estimate: moving laundry + water heating at 12–18 h would have cut the three breach days to 863/844/808 kVA (laundry alone: 933/911/876) — an estimate, not a saving.
  - **T7 (40 °C weekday + largest conference, 318 guests):** forecast 787 kVA at 14:00 (vs 677 without the conference), 90% bound 916, level STACKING WATCH with the shift plan. It does **not** forecast >1,000 kVA: real days ≥39 °C with ≥250-guest events peaked at 685–1,032 kVA (8 days; the one over 1,000 was a stacking day). So T7's "warns >1,000 kVA risk" is met only as a stacking risk, not as a forecast.
- [x] **Post-hoc demand and EV rules (GGN)** — `src/demand_ev_rules.py`, `notebooks/08_demand_ev_rules.ipynb`; alerts in `data/clean/alerts_demand_ev.parquet`. **Added after the detector freeze and after the held-out gaps were seen, so not a clean held-out result; `src/detector.py` and `alerts.parquet` are unchanged.** No label sets either rule:
  - `DEMAND_NEAR_CONTRACT`: 15-min kVA demand above the guide's 920 kVA (BREACH above 1,000); fires on exactly 3 days in the year (12 May, 18 Jun, 25 Jun), ~15 min after the crossing. Reactive; prevention is the day-ahead forecast's job. ₹ = excess-demand charge if the peak stands as the month's MD (penalty-on-top is still open, §21 item 2).
  - `EV_CHARGER_NIGHT_ON`: EV sub-meter above 1 kW between 01:00 and 05:00; the pre-April data show exactly 0 kW in those hours every night. 2 episodes (20–27 May, 4–7 Jun), Low severity.
  - Check vs the key (diagnostic): 5 alerts, 5 matching labels, 0 alerts outside them over the full year. Three demand events and two EV episodes cannot validate a rule.
- **Time to detect definition (answered, Q15):** measured from when the fault first shows in the data. `evaluation.onset_ttd` / `score_heldout_onset` (scorer added after the freeze, detector untouched): held-out median 1.0 h (max 1.0 h) over 13 scored of 16 High labels; the 3 unscored have no rule for their type (the demand-breach labels, until the post-hoc rule above). Tuning: 7 of 12 scored, 5 pre-alerted, median 1.0 h. Label start → first alert stays as a secondary figure (median 3.0 h). Caveat: onset uses the detector's own raw rule flags, so 1 h is close to the floor by construction.
- [ ] Bill reconciliation view, savings (IPMVP C), assistant, UI at public URL.
- [~] Problem-owner answers — demand charge and CH-2 answered; time-to-detect definition answered (Q15); the other six discovery items are informally confirmed defaults awaiting sign-off (§21). Still need two engineers to rate 20 alerts.
- **Deadline:** MVP online by **12 Nov** (Check-in 2); final auction 18 Nov (§22).

### Forward plan (ordered; each step lists the acceptance tests it unlocks)
1. [x] **Baseline model per hotel** (done, see progress log above; original spec follows) — hourly, features: CDH, humidity, rooms sold, event guests/timing, hour × day-type. Exclude `exclude_from_model` and DG hours. Validate on held-out months (CV(RMSE) <30% hourly / <15% monthly, NMBE ±5%). Event features are required so winter weddings are explained. *Unlocks T2, T5 (exclusion), T9.*
2. [x] **Waste-type list** (done; notebook 04)  <!-- original spec: -->
2a. (spec) **Waste-type list** with evidence from the tuning window only (anomalies starting before 1 Apr 2026): staging, hand-mode AHUs after events, PF drop, setpoint, pool pumps, meter fault. Each gets a signature, a ₹ formula and a recommended action.
3. [x] **Context-aware detector** (done; notebook 05 — time-to-detect met under the owner's onset definition, see progress log; original spec follows) — residual vs baseline, with weather/occupancy/event context suppressing explained deviations; separate meter-fault detector (billed columns flat while `kw_avg`/sub-meters live). Report precision/recall/lead time on anomalies from 1 Apr 2026 only. *T1, T3, T4, T5, T6, T8.*
4. [ ] **Costed alerts** — evidence, ₹/h and ₹/day, named equipment, action; alert ≤2 h after event end for T1; no alert for T2. Respect comfort/safety limits (§9) and CHW ≥ 6.5 °C.
5. [x] **Peak/load forecast** (done; notebook 07 — ±5% met on average only; breach days are load stacking; original spec follows) — next-day kVA risk vs 1,000 kVA, flexible-load shift recommendations. *T7.*
6. [ ] **Bill reconciliation** — rebuild bills from meter data per hotel ToD windows; resolve the demand-charge formula (§21); decompose Apr→May GGN bill into weather, occupancy, events, penalty, anomalies. Bills stay untouched. *T9.*
7. [ ] **Savings (IPMVP Option C)** — adjusted baseline only; faults never counted as savings.
8. [ ] **Assistant** — LLM text restricted to model-produced numbers; refuses auto control of kitchen exhaust, room thermostats, life-safety, lifts; simulated automation needs override + audit log. *T10.*
9. [ ] **UI + public URL** — engineer-facing Streamlit: per-hotel overview, alerts with evidence, bill view, forecast, savings, assistant.
10. [ ] **Final check** — run T1–T10 end to end, confirm numbers against §20, write the submission summary.

## 19. Cleaning rules and why (verified, not assumed)
| Issue | Evidence | Treatment |
|---|---|---|
| Gurugram meter faults: 12 Jan 07:30–19:30 (49 intervals, flat), 8 Jul 03:30–08:30 (21, zeros), 17 Aug 15:15–23:30 (34, flat) | `grid_kwh`, `grid_kvah`, `kva_demand` frozen/0 on GRID, but `kw_avg` and power factor stay live and match the sub-meter total (e.g. 494 vs 490 kW on 8 Jul); outside faults grid_kwh = kw_avg×0.25 exactly | Corruption of the billed columns, not real load. Flag `is_meter_fault` + `exclude_from_model`; rebuild kWh = kw_avg×0.25, kVAh = kWh/PF, kVA = kw_avg/PF; raw kept in `*_raw`. User confirmed this rule. |
| Gurugram bills include the corrupted values | Bill kWh = raw meter sum exactly | Bills left untouched. Bill kWh vs cleaned: Jan −464, Jul −2,592, Aug +901 kWh. |
| Jaipur 10 h blank 3 Feb 2026 09:00–18:00 | 50 null cells | Imputed from sub-meter total × median main/sub ratio (1.000); `is_imputed`. Feb bill gap fell +1.56% → −0.29%. |
| Goa 24 exact duplicate rows | Identical copies | Dropped → 8,760 rows. |
| Gurugram `lifts_kw`/`pool_kw` swapped in March 2026 | Lifts is steady ~15 kW all year, but March lifts reads 8 kW (pool level) | Swapped back for the 744 h; `lifts_pool_swapped_fixed`. Pool is genuinely seasonal (winter heating) — a ratio test would misfire. |
| Goa July 2026 bill provisional | +14% kVAh vs meter; components ≠ total | Kept, flagged `is_provisional`. |
| 28 hours where sub-meter total differs >10% from main meter | All fall in diesel hours (main `kw_avg` = 0 on DG) | Not an error; exclude DG hours when comparing. |
| Events ending 23:59 (167) | Means "past midnight"; true end unknown | `ends_after_midnight`. |
| BMS command log | "Banquet AHU mode" only logs 1→2 (into hand mode), never the return | Infer hand-mode end from banquet AHU kW + events calendar. |
| Other | Gurugram `power_factor` null on DG intervals (145) — expected; alarm `action_at` null where no action — expected | None |

## 20. EDA findings (all reproduced from cleaned data)
**Reconciles with the brief:** kWh per occupied room-night 73.3 / 54.1 / 61.6 (GGN/JAI/GOA); annual cost ₹3.70 / 2.14 / 1.56 crore (₹7.40 cr); Gurugram HVAC share May–Aug 49.8%; peak-window kVAh share GGN 18.3%, JAI 26.8%; Gurugram hourly MD matches bills to ≤0.5 kVA.

**Tariff windows differ per hotel** (tariffs sheet): GGN peak 18–22 +₹1.00 / off-peak 23–05 −₹0.75; JAI peak 17–23 +₹1.125 / off-peak 23–05 −₹0.75; GOA peak 18–22 +₹0.75 / off-peak 22–06 −₹0.50. Energy rates GGN 7.10, JAI 7.50, GOA 5.80 ₹/kVAh; demand charge 290/300/250 ₹/kVA; excess penalty 580/600/500; FSA 0.47/0.40/0.30; duty 0.10/0.40/0.15; DG ₹27.56/kWh. The tariff sheet says billing demand = max(recorded MD, 75% of CD) while the guide's worked example uses min(MD, CD). **Resolved: the owner confirmed bills follow min(MD, CD)** (§21 item 2); still verify against every month when rebuilding bills.

**Energy:** cooling is the seasonal swing — GGN chillers 11% of load in winter vs 29% in summer; JAI 20% → 33%; Goa flat 26–29% (humid all year). Winter adds GGN re-heat 3.6%, pool 5.9%, water heating 8%. Kitchen 12–14%, lighting 8–10%, rooms 8–9%; unmetered "other" 8–14%. Night base load (01–05): GGN 330 kW, JAI 187, GOA 181; evening/base ratio 1.4–1.6.

**Money:** ~80% of each bill is the kVAh energy charge; demand ~8%; FSA 4–5%; ToD nets ≈ 0 (surcharge ≈ rebate); effective ₹/kVAh is flat (GGN ~8.5, JAI ~9.45, GOA ~7.0). GGN excess-demand penalty only in May (₹49,880) and June 2026. GGN Apr→May 2026 bill +₹5.30 lakh: ~₹3.98 lakh volume (kVAh +14%, CDH 2,779 → 5,856), ₹0.50 lakh penalty, ₹0.35 lakh demand charge, ₹0.46 lakh diesel, ToD ~0 (setup for T9).

**Drivers:** daily kWh vs CDH + rooms sold + event guests + weekend + humidity gives R² 0.72 / 0.66 / 0.75 (GGN/JAI/GOA). Best CDH base: GGN 26 °C, JAI 16 °C, GOA 14 °C (humidity matters most in Goa). Events: a >300-guest event adds ≈ +112 kW to the GGN 18–22 mean (≈ +20%), ≈ +90 kW in JAI and GOA; ≤150 guests ≈ nothing in GGN. The baseline must include event guests/timing (T2).

**Chiller plant (GGN):** one chiller ≈ 0.60–0.68 kW/TR; two running below ~130 TR ≈ 1.2–1.6 kW/TR (484 h) — the staging-waste signature. CH-2 sub-meter is 0 kWh all year even though the register lists a 300 TR CH-2: CH-1 + CH-3 carry the load (owner confirmed: CH-2 is completely unavailable). CHW setpoint is 5.5 °C for 1,912 h (vs 7.0 for 6,848 h): median 0.72 vs 0.66 kW/TR.

**First-pass waste sizing (GGN; our own EDA estimates, unvalidated, no anomaly labels used):** valued at GGN's average all-in ₹8.84/kWh (total grid bill ÷ grid kWh).
- *Staging:* 557 h with two chillers (CH-1 + CH-3); 481 of them below 130 TR, median 1.34 kW/TR, mostly overnight. Excess vs 0.65 kW/TR ≈ 32,770 kWh ≈ **₹2.9 L (0.8% of GGN bill)**. Single chiller runs 0.60–0.68 kW/TR in ~89% of its hours.
- *Setpoint:* 1,912 h at 5.5 °C vs 6,848 h at 7.0 °C; at the same load band 5–13% worse kW/TR, ≈ 54,927 kWh in single-chiller hours ≈ **₹4.9 L (1.3% of GGN)**.
- Together ≈ ₹7.8 L ≈ 1.0% of the ₹7.40 cr group bill. The 8–12% target (₹59–89 L/yr) is far above what is sized so far; scheduling, demand and PF savings are not yet sized.
- *Unexplained band:* a second cluster near 1.05 kW/TR (CH-1 alone at 130–280 TR, ~900 h, mostly Jun–Jul) is not understood — do **not** call it waste until explained.
- *Hand-mode AHUs:* not sizeable from the log (it records entry to hand mode, never the return).
- ₹21.6 L (2.9%) is the brief's figure for all 107 labelled waste events, not one cause.

**BMS alarm baseline (recomputed from `bms_alarm_log`, no labels needed):** 66% closed with no action = 720 acknowledged-no-action + 254 "normal for event" + 228 "normal for weather" = 1,202 / 1,829 (65.7%); median alarm→action 8.3 h over the 627 alarms that had an action. The 26% precision / 40% recall are the brief's figures; recomputing them needs the labels, so we do that only on the 1 Apr 2026+ split.

**Bill mix:** energy charge share GGN 82% / JAI 79% / GOA 81% (80.7% overall); demand 8/9/9%; ToD nets <2%. GGN penalty ₹88,218 = May ₹49,880 + Jun ₹38,338. GGN sub-metered share May–Jun vs Dec–Feb: chillers 29%→11%, pumps/towers 10%→7%, AHUs 12%→14%, kitchen 12%→14%, winter heating (re-heat + pool + water heating) 6%→18%.

**Peak demand (GGN):** >900 kVA on only 6 days, all May–June, hot afternoons (12:00–16:00, 39–44 °C); max 1,086 kVA on 12 May. 33 intervals >920 kVA (EV-throttle threshold), 12 in May and 21 in June; 12 intervals >1,000. Evening events raise load but don't reach CD alone. 61% of EV kWh falls in the 18–22 peak window; laundry ~2%; water heating ~14%.

## 21. Open questions / things to raise with the problem owner
Ranked by how much the answer changes the build. Each entry gives the question, why it matters, and the default I proceed with if unanswered.

**Status (Check-in 1 deck, slide 8):** the eight discovery-call questions now have answers we build on. Only item 2 (demand charge) was answered directly by the owner; the rest are the written defaults below, *informally confirmed* and to be restated at the discovery call for sign-off — do not treat them as formally signed. Items 3, 4, 6, 8, 11, 13 also stand on their defaults. Per-item status is marked **[answered]** / **[default, informally confirmed]** / **[default]**.

| Item | Status | Answer we build on |
|---|---|---|
| 2 Demand charge | **answered** | Bills follow `min(MD, CD)`. Sub-questions unanswered: whether the excess-demand penalty sits on top, and whether the 75% floor applies in every hotel — follow the worked example |
| 1 CH-2 | **answered** | Completely unavailable (zero reading is real); chiller waste findings stand; say so in evidence |
| 5 Scoring weights | default, informally confirmed | Balanced; baseline and detector first |
| 14 Hotels | default, informally confirmed | All three, one pipeline; Gurugram deepest |
| 9 Limits | default, informally confirmed | Safety hard; comfort hard if occupied |
| 10 Alerts | default, informally confirmed | Rank by ₹, show confidence, cap daily |
| 7 Savings baseline | default, informally confirmed | Earliest pre-change months, adjusted only |
| 12 Deployment | default, informally confirmed | Free hosting, no login, recorded demo |

**Data / domain**
1. **CH-2 chiller.** The CH-2 sub-meter reads 0 kWh all year, yet the register lists a 300 TR CH-2; CH-1 + CH-3 carry the load.
   - *Why it matters:* decides whether the staging rule "never run two large chillers below ~35% combined load" applies at GGN, and which chiller combinations the waste-type list can flag.
   - *Answer (owner):* CH-2 is completely unavailable. Staging analysis uses CH-1 and CH-3 only; the chiller waste findings are not at risk from a mis-metered CH-2.
2. **Demand-charge formula.** The tariff sheet says max(MD, 75% CD); the guide's worked example (§10) uses min(MD, CD) × ₹290 with a 75%-of-CD floor.
   - *Why it matters:* changes every demand-cost figure in the bill reconciliation and the value of peak-shaving (EV throttling at 920 kVA).
   - *Default:* follow the worked example, since it reproduces the May total of ₹35,24,186; flag the discrepancy in the UI.
   - **ANSWERED:** bills follow `min(MD, CD)`. Still open: is the excess-demand penalty charged on top, and does the 75% floor apply in every hotel? Both follow the worked example for now.
3. **Event end times past midnight.** 167 events have no known end time after midnight (`ends_after_midnight`).
   - *Why it matters:* the baseline needs event timing (T2), and banquet AHU schedules stop 1 h after event end.
   - *Default:* assume a typical duration per event type and mark the tail hours as uncertain; do not raise alerts on them.
4. **Meter-fault hours in bill reconciliation.** The GGN Jan/Jul/Aug bills contain the corrupted readings.
   - *Why it matters:* the corrected consumption and the billed figure will differ; the system must say which is which.
   - *Default:* reconcile against the billed values, report the gap versus corrected consumption as a possible billing dispute, never "fix" the bill, and never count it as savings.

**Scoring and evaluation**
5. **Scoring weights.** What carries the most weight: forecast accuracy (CV(RMSE)/NMBE), detection precision/recall, explanation quality, or the UI?
   - *Why it matters:* sets where effort goes.
   - *Default:* balanced; accuracy and detection first, since the other parts depend on them.
6. **Label split.** Is the 1 Apr 2026 tune/report cutoff the one the graders use? Is a single held-out window enough, or should I also report a rolling backtest?
   - *Why it matters:* avoids label leakage and makes the reported numbers comparable with the graders'.
   - *Default:* tune on anomalies starting before 1 Apr 2026, report on those from 1 Apr 2026, plus a rolling-origin backtest for the baseline only.
7. **Savings baseline.** For IPMVP Option C, which months form the reporting period, and is a baseline built from Oct 2025 onward acceptable when no full 12-month baseline year exists?
   - *Why it matters:* savings may only be claimed against an adjusted baseline.
   - *Default:* baseline = earliest months before any intervention; report savings only for the period after, with the adjustment variables listed.
8. **Tariffs.** May the supplied tariffs be treated as given (ToD windows, Goa July 2026 provisional bill)? How should they be caveated in the UI?
   - *Why it matters:* CLAUDE.md forbids claiming the tariffs are real.
   - *Default:* use them as given, with an "illustrative tariff" note, and mark provisional bills `is_provisional`.

**Product behaviour**
9. **Do the §9 comfort/safety limits bind recommendations or only automation?** The brief states the limits (guest rooms 22–25 °C, CHW never <6.5 °C, hot water ≥60 °C daily, pool filtration ≥8 h/day, kitchen exhaust, fresh air per NBC, life-safety never controlled) and an automation table, but never says whether a *recommendation* may go outside a limit.
   - *Readings:* (a) hard bound on every recommendation; (b) bound on automation only, so recommendations are labelled; (c) split by type, with safety/regulatory limits always hard and comfort limits soft.
   - *Edge cases to settle:* whether the 22–25 °C band applies to unsold rooms (the brief only allows PMS setback for them); whether 6.5 °C itself is allowed or is an edge; whether the 60 °C hot-water setpoint can be touched or only the daily cycle must not be skipped; whether moving the pool's 8 h filtration off-peak is allowed; whether to alert on comfort breaches caused by heatwaves.
   - *Why it matters:* needs a constraint layer in front of the recommender; T10 already requires refusing kitchen exhaust, thermostats and life-safety, and the UI needs "within limits / near limit" wording.
   - *Default:* reading (c). Safety and regulatory limits (Legionella, fresh air, pool filtration, kitchen exhaust, life-safety, the 6.5 °C CHW floor) are always hard. Comfort limits are hard for occupied rooms and soft for unsold rooms. Anything outside a limit is refused, not shown with a warning.
10. **Alert policy.** What alert volume per day per hotel is acceptable? Rank by ₹ impact or by confidence?
    - *Why it matters:* controls alert fatigue and the threshold of the detector.
    - *Default:* rank by ₹ impact, show confidence beside it, and cap the daily alerts per hotel.
11. **LLM use.** Is a deployed LLM expected for explanations? If so, which model and what latency/cost budget?
    - *Why it matters:* the LLM may only state facts present in the data, and all numbers come from the models.
    - *Default:* template-based explanations with optional LLM phrasing over verified numbers, so the product works without an LLM.

**Delivery**
12. **Deployment.** What counts as a "public URL" (hosting platform, auth, data-residency limits)? Is the UI judged live or from a recording?
    - *Default:* free-tier hosting with no login, plus a recorded demo as a fallback.
13. **Out-of-period behaviour.** Data ends Sep 2026 but the date is now past that. Should the system be demonstrated as streaming/replay or as a batch report over the full year?
    - *Default:* replay mode over the year with a date selector, so alerts appear as of the selected time.

**Scope**
14. **Which hotels to demonstrate.** Are we expected to show the solution across all three hotels, or is one successful end-to-end hotel enough?
    - *Why it matters:* decides whether the MVP is built deep on Gurugram (largest cost, HVAC and demand-penalty story, tests T1, T2, T4–T7, T9) or wide across all three (T3 is Jaipur, T8 is Goa).
    - *Default:* all three hotels run through the same pipeline; Gurugram gets the deepest treatment.

**Discovery-call shortlist (the 8 items in the table above):** 2, 1, 5, 14, 9, 10, 7, 12. The rest (3, 4, 6, 8, 11, 13) are defaults we state and move on from. Asks of the owner at the call: sign-off on these answers, and **two engineers (or students) to rate 20 alerts** — that is how the engineer-trust metric (≥4/5) is measured.

## 22. Schedule, scope and team (Check-in 1 deck)
**Team 12:** Justin Sharon, Ananya Shukla, Varnika Ashi, Manish Manoj Nair.

**Schedule:** 3 Nov discovery call with Apurav · 4 Nov Check-in 1 (problem breakdown) · **12 Nov Check-in 2: MVP, online** · 16 Nov Check-in 3: internal auction · **18 Nov final auction (leaders bid)**. The deck says the discovery call falls between 4 and 7 Nov.

**Committed for 18 Nov:** baseline per hotel with CV(RMSE)/NMBE; context-aware detector with meter faults suppressed; costed alerts (cause, evidence, action); bill reconciliation; public-URL interface.
**If time allows:** day-ahead peak-kVA forecast; flexible loads moved off the peak window; IPMVP savings view; "why was this bill high?" assistant.
**Not planned:** control simulation, portfolio benchmarking, auto monthly report (the brief's stretch items). **Out of scope:** controlling real equipment or a live BMS, guest-room thermostats, fire/life-safety/lifts, new chillers/solar/real tariffs.
Note: the committed list does not include the forecast (T7), savings (Option C) or assistant (T10) — those are "if time allows", so the forward plan in §18 should be cut to match the deadline: steps 1–4, 6 and 9 first, then 5, 7, 8.

**Modelling approach stated in the deck:** each season appears once in 8,760 hourly rows per hotel, so use regularised linear and shallow boosted models, validated by **rolling-origin blocks of months** (not random folds), on months the model has not seen (ASHRAE G14).

**Risks and containment (deck slide 7):** normal extremes look like waste → baseline carries heat, rooms, events; meter faults read as waste → flag, exclude, rebuild from kW, never edit a bill (show billed and corrected side by side); label leakage → tune before 1 Apr, report from 1 Apr; one year of data → simple models, blocked validation; small waste on a large load (e.g. 6 kW on a 600 kW site) → work at sub-meter level and state the detection floor; unsafe or invented advice → constraint layer, numbers only from models.

**Metric targets and how each is measured:** precision ≥70% (match to labels from 1 Apr); recall ≥75% of High+Medium; time to detect <2 h for High (anomaly start → first alert); CV(RMSE) <15% monthly / <30% hourly, NMBE ±5%; peak forecast within ±5% of next-day max kVA; savings 8–12% (₹59–89 L/yr) as adjusted baseline − actual; engineer trust ≥4/5 from 2 engineers rating 20 alerts.
