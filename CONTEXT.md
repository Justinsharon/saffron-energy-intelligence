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

**Anti-leakage rule:** do NOT look at `anomaly_labels` beyond the tuning window (events before **1 Apr 2026**). Report all results on anomalies **from 1 Apr 2026**.

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
- Demand: min(billing demand, CD) × ₹290 (75%-of-CD floor)
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
- [ ] **Baseline models** per hotel (hourly; CV(RMSE) <30% hourly / <15% monthly, NMBE ±5%; held-out months). NEXT.
- [ ] Waste-type list with evidence (tuning window only), anomaly detector, root-cause + alert text, fault suppression, bill reconciliation view, peak forecast, savings (IPMVP C), assistant, UI at public URL.
- [ ] Problem-owner meeting answers (needs the user).

### Forward plan (ordered; each step lists the acceptance tests it unlocks)
1. [ ] **Baseline model per hotel** — hourly, features: CDH, humidity, rooms sold, event guests/timing, hour × day-type. Exclude `exclude_from_model` and DG hours. Validate on held-out months (CV(RMSE) <30% hourly / <15% monthly, NMBE ±5%). Event features are required so winter weddings are explained. *Unlocks T2, T5 (exclusion), T9.*
2. [ ] **Waste-type list** with evidence from the tuning window only (anomalies starting before 1 Apr 2026): staging, hand-mode AHUs after events, PF drop, setpoint, pool pumps, meter fault. Each gets a signature, a ₹ formula and a recommended action.
3. [ ] **Context-aware detector** — residual vs baseline, with weather/occupancy/event context suppressing explained deviations; separate meter-fault detector (billed columns flat while `kw_avg`/sub-meters live). Report precision/recall/lead time on anomalies from 1 Apr 2026 only. *T1, T3, T4, T5, T6, T8.*
4. [ ] **Costed alerts** — evidence, ₹/h and ₹/day, named equipment, action; alert ≤2 h after event end for T1; no alert for T2. Respect comfort/safety limits (§9) and CHW ≥ 6.5 °C.
5. [ ] **Peak/load forecast** — next-day kVA risk vs 1,000 kVA, flexible-load shift recommendations. *T7.*
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

**Tariff windows differ per hotel** (tariffs sheet): GGN peak 18–22 +₹1.00 / off-peak 23–05 −₹0.75; JAI peak 17–23 +₹1.125 / off-peak 23–05 −₹0.75; GOA peak 18–22 +₹0.75 / off-peak 22–06 −₹0.50. Energy rates GGN 7.10, JAI 7.50, GOA 5.80 ₹/kVAh; demand charge 290/300/250 ₹/kVA; excess penalty 580/600/500; FSA 0.47/0.40/0.30; duty 0.10/0.40/0.15; DG ₹27.56/kWh. The tariff sheet says billing demand = max(recorded MD, 75% of CD) while the guide's worked example uses min(MD, CD) — check which when rebuilding bills.

**Energy:** cooling is the seasonal swing — GGN chillers 11% of load in winter vs 29% in summer; JAI 20% → 33%; Goa flat 26–29% (humid all year). Winter adds GGN re-heat 3.6%, pool 5.9%, water heating 8%. Kitchen 12–14%, lighting 8–10%, rooms 8–9%; unmetered "other" 8–14%. Night base load (01–05): GGN 330 kW, JAI 187, GOA 181; evening/base ratio 1.4–1.6.

**Money:** ~80% of each bill is the kVAh energy charge; demand ~8%; FSA 4–5%; ToD nets ≈ 0 (surcharge ≈ rebate); effective ₹/kVAh is flat (GGN ~8.5, JAI ~9.45, GOA ~7.0). GGN excess-demand penalty only in May (₹49,880) and June 2026. GGN Apr→May 2026 bill +₹5.30 lakh: ~₹3.98 lakh volume (kVAh +14%, CDH 2,779 → 5,856), ₹0.50 lakh penalty, ₹0.35 lakh demand charge, ₹0.46 lakh diesel, ToD ~0 (setup for T9).

**Drivers:** daily kWh vs CDH + rooms sold + event guests + weekend + humidity gives R² 0.72 / 0.66 / 0.75 (GGN/JAI/GOA). Best CDH base: GGN 26 °C, JAI 16 °C, GOA 14 °C (humidity matters most in Goa). Events: a >300-guest event adds ≈ +112 kW to the GGN 18–22 mean (≈ +20%), ≈ +90 kW in JAI and GOA; ≤150 guests ≈ nothing in GGN. The baseline must include event guests/timing (T2).

**Chiller plant (GGN):** one chiller ≈ 0.60–0.68 kW/TR; two running below ~130 TR ≈ 1.2–1.6 kW/TR (484 h) — the staging-waste signature. CH-2 sub-meter is 0 kWh all year even though the register lists a 300 TR CH-2: CH-1 + CH-3 carry the load (ask the problem owner). CHW setpoint is 5.5 °C for 1,912 h (vs 7.0 for 6,848 h): median 0.72 vs 0.66 kW/TR.

**Peak demand (GGN):** >900 kVA on only 6 days, all May–June, hot afternoons (12:00–16:00, 39–44 °C); max 1,086 kVA on 12 May. 33 intervals >920 kVA (EV-throttle threshold), 12 in May and 21 in June; 12 intervals >1,000. Evening events raise load but don't reach CD alone. 61% of EV kWh falls in the 18–22 peak window; laundry ~2%; water heating ~14%.

## 21. Open questions / things to raise with the problem owner
- CH-2 shows zero energy all year — labelling quirk or genuinely unused chiller (affects the staging rule "never run two large chillers below 35% load")?
- Demand-charge formula: tariff sheet says max(MD, 75% CD), guide example uses min(MD, CD).
- Event end times past midnight are unknown (167 events).
- How to treat meter-fault hours in the bill reconciliation (bills include the corrupted readings).
