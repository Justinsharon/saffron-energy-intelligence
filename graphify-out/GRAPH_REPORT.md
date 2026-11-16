# Graph Report - saffron-energy-intelligence  (2026-11-16)

## Corpus Check
- 321 files · ~821,211 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 77 file(s) not represented in the graph (top: .parquet 57, .ipynb 8, (none) 4)

## Summary
- 1328 nodes · 3156 edges · 65 communities (58 shown, 7 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 103 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `91b85c0f`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- make_live_year.py
- export_web_data.py
- Brief: Tests & Guardrails
- Web Assistant (TS)
- build_app_data.py
- parts.tsx
- Web Plan Logic (TS)
- Plan Check
- Challenge & API Deps
- Streamlit App
- numpy
- Web Dependencies
- EDA & Model Notebooks
- Plan API (FastAPI)
- Finance.tsx
- App.tsx
- Demand Planner Page
- Live Feed Gauges
- train_api_models.py
- Detector Evaluation
- operating_plan.py
- Plan Validation (TS)
- Plan Export Tools
- API Tests
- Feed Sources
- baseline.py
- savings.py
- detector.py
- Forecaster Model
- planApi.ts
- json
- Baseline Features & Scores
- Operating Plan Tests
- Findings & Option C
- data.ts
- TS Config
- Engineering.tsx
- attribution.py
- Demand & EV Rules
- night_baseload.py
- Peak Risk
- Data Cleanliness Notebook
- assistant.py
- Data Cleaning
- TodayPlan.tsx
- Ratings Function
- bills.py
- Chiller Waste Figure
- Load Shape Figure
- Load vs CDH Figure
- Bill Components Figure
- Equipment Monthly Figure
- test_site_plan.py
- graphify Trigger
- Project Metadata
- Original year (Oct 2025 – Sep 2026): the savings claim
- test_night_baseload.py
- plans.ts
- compose_day
- send
- risk_for

## God Nodes (most connected - your core abstractions)
1. `PS-12 Context document` - 43 edges
2. `TomorrowPlan()` - 30 edges
3. `inr()` - 28 edges
4. `n()` - 25 edges
5. `build_features()` - 23 edges
6. `Shift()` - 23 edges
7. `useData()` - 20 edges
8. `build()` - 19 edges
9. `react` - 19 edges
10. `main()` - 18 edges

## Surprising Connections (you probably didn't know these)
- `Cooling Degree Hours (site-specific base)` --conceptually_related_to--> `cooling_degree_hours()`  [INFERRED]
  docs/eda_figures/load_vs_cdh.png → src/features.py
- `main()` --uses--> `Ens`  [INFERRED]
  tools/export_plan_inputs.py → src/plan_models.py
- `tr_accuracy()` --uses--> `Ens`  [INFERRED]
  tools/export_plan_inputs.py → src/plan_models.py
- `fit_all()` --uses--> `Ens`  [INFERRED]
  tools/train_api_models.py → src/plan_models.py
- `frame()` --calls--> `build_features()`  [INFERRED]
  tools/train_api_models.py → src/baseline.py

## Import Cycles
- 2-file cycle: `web/src/App.tsx -> web/src/pages/GM.tsx -> web/src/App.tsx`
- 2-file cycle: `web/src/App.tsx -> web/src/pages/Shift.tsx -> web/src/App.tsx`
- 2-file cycle: `web/src/App.tsx -> web/src/pages/Demand.tsx -> web/src/App.tsx`
- 2-file cycle: `web/src/App.tsx -> web/src/pages/Finance.tsx -> web/src/App.tsx`
- 2-file cycle: `web/src/App.tsx -> web/src/pages/Engineering.tsx -> web/src/App.tsx`
- 2-file cycle: `web/src/App.tsx -> web/src/pages/Report.tsx -> web/src/App.tsx`
- 3-file cycle: `web/src/App.tsx -> web/src/pages/GM.tsx -> web/src/pages/Shift.tsx -> web/src/App.tsx`
- 3-file cycle: `web/src/App.tsx -> web/src/pages/Finance.tsx -> web/src/pages/Shift.tsx -> web/src/App.tsx`
- 3-file cycle: `web/src/App.tsx -> web/src/pages/Engineering.tsx -> web/src/pages/Shift.tsx -> web/src/App.tsx`

## Hyperedges (group relationships)
- **Peak-demand risk handling** — context_peak_forecast, context_load_stacking, context_stacking_watch, context_shift_plan, context_t7_peak_risk [EXTRACTED 1.00]
- **Live year generation and robustness check** — tools_make_live_year, data_live__report_synthetic_live_year, tools_run_live_year, data_live_results_frozen_detector, data_live_savings_live_savings_headline [INFERRED 0.85]
- **Deployed product stack** — claude_saffron_api, claude_netlify_web_app, api_requirements_plan_api_runtime, web_index_saffron_suites_energy_html [INFERRED 0.85]

## Communities (65 total, 7 thin omitted)

### Community 0 - "make_live_year.py"
Cohesion: 0.05
Nodes (36): Bills rebuild from meter check, Comms faults (one per site, frozen billed kWh), Live data year generation report, Injected anomalies at original yearly rates, Sub-meter vs main meter tolerance check, Synthetic live year Oct 2026 - Sep 2027, Baseline vs ASHRAE Guideline 14 targets, Live year pipeline results (+28 more)

### Community 1 - "export_web_data.py"
Cohesion: 0.15
Nodes (13): clean(), cross_year_pairs(), year(), export_alerts(), export_bills(), export_forecast(), export_hotels(), export_quality() (+5 more)

### Community 2 - "Brief: Tests & Guardrails"
Cohesion: 0.06
Nodes (57): Acceptance tests T1-T10, Good alert format, Automation allowed table, Per-hotel baseline (Ridge + LightGBM), Bill mechanics (energy, ToD, demand, penalty), BMS alarm baseline (26% precision), CH-2 unavailable, CHW setpoint floor 6.5 C (+49 more)

### Community 3 - "Web Assistant (TS)"
Cohesion: 0.06
Nodes (22): alertsNow(), billsNow(), changesNow(), HOURLY, J, LEVEL, NEVER, numbers() (+14 more)

### Community 4 - "build_app_data.py"
Cohesion: 0.26
Nodes (5): build_cards(), card_text(), fault_cards(), _meta(), main()

### Community 5 - "parts.tsx"
Cohesion: 0.15
Nodes (20): RATIO, SIG_COLORS, SIGNAL_LABEL, Status(), STEP, TAG, Waterfall(), BILL_STATUS (+12 more)

### Community 6 - "Web Plan Logic (TS)"
Cohesion: 0.06
Nodes (45): AHU, banquetDelta(), CD_KVA, CH1_MAX, CH3_MAX, CHW_FLOOR, CHW_MIN_H, CHW_RESET (+37 more)

### Community 7 - "Plan Check"
Cohesion: 0.12
Nodes (26): actual_stage(), _alert(), allowed_hours(), check_day(), check_site(), _checked(), _end(), finite() (+18 more)

### Community 8 - "Challenge & API Deps"
Cohesion: 0.07
Nodes (26): fastapi, lightgbm, pandas, Plan API runtime requirements (pinned), scikit_learn, Applied AI Challenge, Check-in 2 MVP (deployed URL + one-page note), Check-in 3 Internal Auction (16 Nov) (+18 more)

### Community 9 - "Streamlit App"
Cohesion: 0.15
Nodes (24): add_lines(), bills(), cards(), events(), evidence_chart(), explain(), faults(), fc() (+16 more)

### Community 10 - "numpy"
Cohesion: 0.10
Nodes (13): penalty_at_risk(), risk_level(), thermal_features(), upper_factor(), Ens, predict(), main(), alarm_log() (+5 more)

### Community 11 - "Web Dependencies"
Cohesion: 0.08
Nodes (30): @anthropic-ai/sdk, @netlify/functions, react-dom, @types/node, @types/react, @types/react-dom, typescript, vite (+22 more)

### Community 12 - "EDA & Model Notebooks"
Cohesion: 0.12
Nodes (4): compare(), typemask(), first(), first()

### Community 13 - "Plan API (FastAPI)"
Cohesion: 0.09
Nodes (23): _as_of(), check(), _check(), compute_plan(), _end_label(), _far_from(), _fold(), forecast_ep() (+15 more)

### Community 14 - "Finance.tsx"
Cohesion: 0.21
Nodes (19): MonthSavingsPanel(), CATEGORY, CONFIDENCE(), measureGroup(), measureName(), SITE_NAME, SITES, fmtMonth() (+11 more)

### Community 15 - "App.tsx"
Cohesion: 0.11
Nodes (23): react, App(), Clock, Ctx, MORE, OLD, PageId, PAGES (+15 more)

### Community 16 - "Demand Planner Page"
Cohesion: 0.10
Nodes (28): KVA(), LOAD, addMs(), iso(), n(), addDays(), BADGE, BookingRow() (+20 more)

### Community 17 - "Live Feed Gauges"
Cohesion: 0.14
Nodes (22): recharts, ICON, Ack, Gauge(), ForecastDay, Hotel, load(), COORDS (+14 more)

### Community 18 - "train_api_models.py"
Cohesion: 0.15
Nodes (18): accuracy(), build(), curve_at(), _end(), fit_all(), frame(), in_win(), kwtr_curve() (+10 more)

### Community 19 - "Detector Evaluation"
Cohesion: 0.10
Nodes (19): typed_overlap(), heldout_labels_for_diagnostics(), _labels(), onset_ttd(), _overlap(), score(), score_heldout(), score_heldout_onset() (+11 more)

### Community 20 - "operating_plan.py"
Cohesion: 0.12
Nodes (18): booking_minutes(), chw_pct(), curve_at(), held_note(), hh(), hm(), hold_setpoint(), hold_stages() (+10 more)

### Community 21 - "Plan Validation (TS)"
Cohesion: 0.21
Nodes (20): DayCheck, useDayCheck(), Action, CheckResult, applyEvent(), checkActions(), Entry, istStamp() (+12 more)

### Community 22 - "Plan Export Tools"
Cohesion: 0.15
Nodes (7): ahu_overrun(), data(), main(), matched_refs(), risk_calibration(), tr_frame(), with_events()

### Community 23 - "API Tests"
Cohesion: 0.20
Nodes (17): c(), joined(), post(), test_alias_conflict_is_noted(), test_aliases_are_used_and_unknown_fields_noted(), test_bad_date_and_uncovered_date_422(), test_bad_values_are_noted_not_errors(), test_chw_reason_uses_measured_penalty() (+9 more)

### Community 24 - "Feed Sources"
Cohesion: 0.15
Nodes (28): Alert, Bills, Fault, Hourly, Recon, Site, Feeds, fromFunction() (+20 more)

### Community 25 - "baseline.py"
Cohesion: 0.15
Nodes (8): lomo(), rolling(), build_features(), _event_hours(), fit_predict(), _ridge_features(), gurugram_hourly(), unified_hourly()

### Community 26 - "savings.py"
Cohesion: 0.12
Nodes (11): tool_savings_plan(), tariff(), _chw_per_degc(), _frame(), model_stats(), night_audit(), plan(), _plan_live() (+3 more)

### Community 27 - "detector.py"
Cohesion: 0.11
Nodes (18): alert_text(), _cost(), detect_all(), detect_meter_faults(), detect_site(), _episodes(), _event_context(), _evidence() (+10 more)

### Community 28 - "Forecaster Model"
Cohesion: 0.13
Nodes (7): build_frame(), cv_hourly(), daily_summary(), Forecaster, hot_reference(), shift_plan(), stack_allowance()

### Community 29 - "planApi.ts"
Cohesion: 0.15
Nodes (20): Form, Booking, byTime(), PlanDay, PlanSite, riskFor(), API_TIMEOUT_MS, apiPlan() (+12 more)

### Community 30 - "json"
Cohesion: 0.07
Nodes (23): _api(), _gist(), load(), rating_set(), rounds(), save(), _secret(), storage() (+15 more)

### Community 31 - "Baseline Features & Scores"
Cohesion: 0.25
Nodes (9): scores(), cv_rmse(), nmbe(), tr_accuracy(), _bmetrics(), freeze(), live(), main() (+1 more)

### Community 32 - "Operating Plan Tests"
Cohesion: 0.19
Nodes (10): all_days(), days(), random_bookings(), test_banquet_ahu_timing_and_laundry_peak(), test_ev_limit_only_above_920(), test_guardrails_on_generated_days(), test_plan_needs_reference(), test_setpoint_rule() (+2 more)

### Community 33 - "Findings & Option C"
Cohesion: 0.15
Nodes (14): ChatGPT session findings verified, IPMVP Option C, Kickoff deck constraints, OPEN_QUESTIONS.md suggestions, Problem B: avoidable waste not caught in time, Swapped lifts_kw/pool_kw sub-meters (Mar 2026), Modelling approach notes, LightGBM per-hotel baseline (+6 more)

### Community 34 - "data.ts"
Cohesion: 0.10
Nodes (31): BillChange, cache, Measure, NightAudit, NightRow, OptionC, PlanRow, Quality (+23 more)

### Community 35 - "TS Config"
Cohesion: 0.13
Nodes (14): compilerOptions, isolatedModules, jsx, lib, module, moduleResolution, noEmit, noUnusedLocals (+6 more)

### Community 36 - "Engineering.tsx"
Cohesion: 0.15
Nodes (21): Evidence(), SignalChart(), TagPlate(), tick(), Ticket(), useFaultsAt(), DATA_FIRST, LIVE_START (+13 more)

### Community 37 - "attribution.py"
Cohesion: 0.12
Nodes (11): _alert_kwh(), _counterfactual(), explain_change(), explain_frames(), f(), predict(), production_baseline(), make_gbm() (+3 more)

### Community 38 - "Demand & EV Rules"
Cohesion: 0.46
Nodes (4): all_additions(), demand_alerts(), ev_alerts(), _runs()

### Community 39 - "night_baseload.py"
Cohesion: 0.19
Nodes (10): _alert_hours(), audit(), audit_site(), _event_nights(), _flags(), _frame(), good_night(), _rate() (+2 more)

### Community 40 - "Peak Risk"
Cohesion: 0.36
Nodes (6): assess(), bias_factor(), breach_days(), exceed_prob(), _hist(), stacking_increment()

### Community 41 - "Data Cleanliness Notebook"
Cohesion: 0.22
Nodes (4): flag(), profile(), runs(), ts_regularity()

### Community 42 - "assistant.py"
Cohesion: 0.16
Nodes (15): page_assistant(), answer(), check_numbers(), _fallback_text(), guard(), _numbers(), _risk_out(), _route() (+7 more)

### Community 43 - "Data Cleaning"
Cohesion: 0.44
Nodes (8): clean_context(), clean_goa(), clean_gurugram(), clean_jaipur(), clean_submeters(), main(), read(), runs()

### Community 44 - "TodayPlan.tsx"
Cohesion: 0.38
Nodes (6): BADGE, hourOf(), span(), TodayPlanCard(), TAG, CheckStep

### Community 45 - "Ratings Function"
Cohesion: 0.43
Nodes (5): COLS, gh(), gistId(), parseCSV(), read()

### Community 46 - "bills.py"
Cohesion: 0.18
Nodes (8): components(), fault_months(), _in_window(), meter_quantities(), price(), reconcile(), reconcile_all(), unused_demand()

### Community 47 - "Chiller Waste Figure"
Cohesion: 0.40
Nodes (6): Chiller over-staging waste, Low CHW setpoint waste (5.5 C), Mean chillers running by hour (night peak 0-5h), Chiller plant EDA figure, kW/TR by CHW setpoint (5.5 vs 7.0 C), Chiller kW/TR vs plant load (1 vs 2 chillers running; 2 chillers at low load is inefficient staging)

### Community 48 - "Load Shape Figure"
Cohesion: 0.40
Nodes (5): Load shapes: mean kW by hour per hotel, season and weekday/weekend, Load dip at 17:00 then evening rise (Jaipur/Goa), Goa winter is the highest-load season (~330 kW midday), Gurugram summer weekday midday peak ~700 kW (cooling-driven), Seasonal daily load profile (summer/winter/monsoon, weekday vs weekend)

### Community 49 - "Load vs CDH Figure"
Cohesion: 0.40
Nodes (4): Daily MWh vs Cooling Degree Hours per hotel (coloured by occupancy), Cooling Degree Hours (site-specific base), Occupancy as load driver, cooling_degree_hours()

### Community 50 - "Bill Components Figure"
Cohesion: 0.50
Nodes (4): Bill line items (energy, ToD, demand, excess-demand penalty, FSA, duty, municipal tax, DG cost), Monthly bill components per hotel (stacked, ₹ lakh), Energy charge dominates monthly bill (~80%), Gurugram cost peaks May 2026 (~₹36 lakh) vs ~₹26 lakh Feb

### Community 51 - "Equipment Monthly Figure"
Cohesion: 0.50
Nodes (4): AHU re-heat spike in Jan 2026, Gurugram monthly MWh by equipment group (sub-meters), Chillers dominate summer load (~35 MWh Feb to ~115 MWh Jun), Other (unmetered) residual load

### Community 52 - "test_site_plan.py"
Cohesion: 0.17
Nodes (16): c(), _hours(), joined(), post(), test_check_approved_plan(), test_forecast_and_risk_endpoints(), test_guardrails_hold_every_day(), test_hold_setpoint_prefers_7() (+8 more)

### Community 56 - "Original year (Oct 2025 – Sep 2026): the savings claim"
Cohesion: 0.17
Nodes (11): Goa — ₹0/yr (0.00 % of the year's bill ₹155.9 lakh), Goa — ₹16,681/yr (0.10 % of the year's bill ₹159.2 lakh), Gurugram — ₹0/yr (0.00 % of the year's bill ₹369.9 lakh), Gurugram — ₹51,649/yr (0.13 % of the year's bill ₹391.7 lakh), Jaipur — ₹0/yr (0.00 % of the year's bill ₹214.2 lakh), Jaipur — ₹37,519/yr (0.17 % of the year's bill ₹221.4 lakh), Live year (Oct 2026 – Sep 2027, synthetic): a check, not a claim, Night base-load audit (00:00–05:00) (+3 more)

### Community 57 - "test_night_baseload.py"
Cohesion: 0.33
Nodes (5): _judge(), _nights(), test_must_run_channels_never_claimed_and_original_year_result(), test_persistent_excess_is_claimed(), test_random_scatter_is_not_claimed()

### Community 58 - "plans.ts"
Cohesion: 0.42
Nodes (6): SITES, configured(), gh(), gistId(), readJSON(), writeJSON()

### Community 59 - "compose_day"
Cohesion: 0.33
Nodes (3): banquet_delta(), compose_day(), parse_booking()

### Community 61 - "send"
Cohesion: 0.50
Nodes (4): site(), decide(), send(), setPlannerName()

## Knowledge Gaps
- **59 isolated node(s):** `ps12-energy`, `Good alert format`, `BMS alarm baseline (26% precision)`, `Data schemas`, `Post-hoc demand & EV rules` (+54 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 452 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `react` connect `App.tsx` to `data.ts`, `Engineering.tsx`, `parts.tsx`, `Web Dependencies`, `Finance.tsx`, `Demand Planner Page`, `Live Feed Gauges`, `Plan Validation (TS)`, `Feed Sources`?**
  _High betweenness centrality (0.010) - this node is a cross-community bridge._
- **What connects `ps12-energy`, `Good alert format`, `BMS alarm baseline (26% precision)` to the rest of the system?**
  _59 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `make_live_year.py` be split into smaller, more focused modules?**
  _Cohesion score 0.05451127819548872 - nodes in this community are weakly interconnected._
- **Why does `us()` connect `make_live_year.py` to `numpy`, `train_api_models.py`?**
  _High betweenness centrality (0.008) - this node is a cross-community bridge._
- **Should `Brief: Tests & Guardrails` be split into smaller, more focused modules?**
  _Cohesion score 0.056107539450613676 - nodes in this community are weakly interconnected._
- **Should `Web Assistant (TS)` be split into smaller, more focused modules?**
  _Cohesion score 0.06025369978858351 - nodes in this community are weakly interconnected._
- **Should `parts.tsx` be split into smaller, more focused modules?**
  _Cohesion score 0.14855072463768115 - nodes in this community are weakly interconnected._