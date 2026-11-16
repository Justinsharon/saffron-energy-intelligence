# Graph Report - saffron-energy-intelligence  (2026-11-16)

## Corpus Check
- Large corpus: 321 files · ~799,124 words. Semantic extraction will be expensive (many Claude tokens). Consider running on a subfolder.

## Summary
- 1176 nodes · 2781 edges · 56 communities (52 shown, 4 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 94 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Live Year & Data Quality
- Bills & Savings Engine
- Brief: Tests & Guardrails
- Web Assistant (TS)
- Alert Cards
- Web UI Components
- Web Plan Logic (TS)
- Plan Check
- Challenge & API Deps
- Streamlit App
- Peak-kVA Forecast
- Web Dependencies
- EDA & Model Notebooks
- Plan API (FastAPI)
- Bills & Charts UI
- Web App Shell
- Demand Planner Page
- Live Feed Gauges
- Python Assistant
- Detector Evaluation
- Operating Plan
- Plan Validation (TS)
- Plan Export Tools
- API Tests
- Feed Sources
- Baseline Models
- Web Data Types
- UI Copy Text
- Forecaster Model
- Plan Booking Form
- Feedback Ratings
- Baseline Features & Scores
- Operating Plan Tests
- Findings & Option C
- Monthly Savings Panel
- TS Config
- Live Forecast & Reports
- T9 Attribution
- Demand & EV Rules
- kW/TR Recalibration
- Peak Risk
- Data Cleanliness Notebook
- Plan Parity Tests
- Data Cleaning
- Forecast UI Wrapper
- Ratings Function
- Today Plan Card
- Chiller Waste Figure
- Load Shape Figure
- Load vs CDH Figure
- Bill Components Figure
- Equipment Monthly Figure
- graphify Trigger
- Project Metadata

## God Nodes (most connected - your core abstractions)
1. `PS-12 Context document` - 43 edges
2. `TomorrowPlan()` - 29 edges
3. `inr()` - 27 edges
4. `n()` - 25 edges
5. `Shift()` - 23 edges
6. `build_features()` - 21 edges
7. `useData()` - 20 edges
8. `react` - 19 edges
9. `main()` - 18 edges
10. `Engineering()` - 17 edges

## Surprising Connections (you probably didn't know these)
- `Cooling Degree Hours (site-specific base)` --conceptually_related_to--> `cooling_degree_hours()`  [INFERRED]
  docs/eda_figures/load_vs_cdh.png → src/features.py
- `read_bookings()` --calls--> `booking_hours()`  [INFERRED]
  api/main.py → src/plan_models.py
- `compute_plan()` --calls--> `add_bookings()`  [INFERRED]
  api/main.py → src/plan_models.py
- `explain()` --calls--> `explain_change()`  [INFERRED]
  app.py → src/attribution.py
- `mv_stats()` --calls--> `model_stats()`  [INFERRED]
  app.py → src/savings.py

## Import Cycles
- 2-file cycle: `web/src/App.tsx -> web/src/pages/GM.tsx -> web/src/App.tsx`
- 2-file cycle: `web/src/App.tsx -> web/src/pages/Demand.tsx -> web/src/App.tsx`
- 2-file cycle: `web/src/App.tsx -> web/src/pages/Finance.tsx -> web/src/App.tsx`
- 2-file cycle: `web/src/App.tsx -> web/src/pages/Report.tsx -> web/src/App.tsx`
- 2-file cycle: `web/src/App.tsx -> web/src/pages/Engineering.tsx -> web/src/App.tsx`
- 2-file cycle: `web/src/App.tsx -> web/src/pages/Shift.tsx -> web/src/App.tsx`
- 3-file cycle: `web/src/App.tsx -> web/src/pages/GM.tsx -> web/src/pages/Shift.tsx -> web/src/App.tsx`
- 3-file cycle: `web/src/App.tsx -> web/src/pages/Finance.tsx -> web/src/pages/Shift.tsx -> web/src/App.tsx`
- 3-file cycle: `web/src/App.tsx -> web/src/pages/Engineering.tsx -> web/src/pages/Shift.tsx -> web/src/App.tsx`

## Hyperedges (group relationships)
- **Deployed product stack** — claude_saffron_api, claude_netlify_web_app, api_requirements_plan_api_runtime, web_index_saffron_suites_energy_html [INFERRED 0.85]
- **Peak-demand risk handling** — context_peak_forecast, context_load_stacking, context_stacking_watch, context_shift_plan, context_t7_peak_risk [EXTRACTED 1.00]
- **Live year generation and robustness check** — tools_make_live_year, data_live__report_synthetic_live_year, tools_run_live_year, data_live_results_frozen_detector, data_live_savings_live_savings_headline [INFERRED 0.85]

## Communities (56 total, 4 thin omitted)

### Community 0 - "Live Year & Data Quality"
Cohesion: 0.05
Nodes (38): Bills rebuild from meter check, Comms faults (one per site, frozen billed kWh), Live data year generation report, Injected anomalies at original yearly rates, Sub-meter vs main meter tolerance check, Synthetic live year Oct 2026 - Sep 2027, Baseline vs ASHRAE Guideline 14 targets, Live year pipeline results (+30 more)

### Community 1 - "Bills & Savings Engine"
Cohesion: 0.06
Nodes (31): tool_savings_plan(), components(), fault_months(), _in_window(), meter_quantities(), price(), reconcile(), reconcile_all() (+23 more)

### Community 2 - "Brief: Tests & Guardrails"
Cohesion: 0.06
Nodes (57): Acceptance tests T1-T10, Good alert format, Automation allowed table, Per-hotel baseline (Ridge + LightGBM), Bill mechanics (energy, ToD, demand, penalty), BMS alarm baseline (26% precision), CH-2 unavailable, CHW setpoint floor 6.5 C (+49 more)

### Community 3 - "Web Assistant (TS)"
Cohesion: 0.05
Nodes (29): alertsNow(), billsNow(), changesNow(), HOURLY, J, LEVEL, NEVER, numbers() (+21 more)

### Community 4 - "Alert Cards"
Cohesion: 0.08
Nodes (23): build_cards(), card_text(), fault_cards(), _meta(), main(), alert_text(), _cost(), detect_all() (+15 more)

### Community 5 - "Web UI Components"
Cohesion: 0.12
Nodes (30): Evidence(), KVA(), RATIO, SIG_COLORS, SIGNAL_LABEL, SignalChart(), STEP, TAG (+22 more)

### Community 6 - "Web Plan Logic (TS)"
Cohesion: 0.07
Nodes (35): AHU, banquetDelta(), CD_KVA, CH1_MAX, CH3_MAX, CHW_FLOOR, CHW_RESET, CHW_STD (+27 more)

### Community 7 - "Plan Check"
Cohesion: 0.13
Nodes (23): actual_stage(), _alert(), allowed_hours(), check_day(), _checked(), _end(), _hm(), hour_of() (+15 more)

### Community 8 - "Challenge & API Deps"
Cohesion: 0.07
Nodes (26): fastapi, lightgbm, pandas, Plan API runtime requirements (pinned), scikit_learn, Applied AI Challenge, Check-in 2 MVP (deployed URL + one-page note), Check-in 3 Internal Auction (16 Nov) (+18 more)

### Community 9 - "Streamlit App"
Cohesion: 0.15
Nodes (24): add_lines(), bills(), cards(), events(), evidence_chart(), explain(), faults(), fc() (+16 more)

### Community 10 - "Peak-kVA Forecast"
Cohesion: 0.10
Nodes (12): penalty_at_risk(), risk_level(), thermal_features(), upper_factor(), add_bookings(), booking_hours(), predict(), main() (+4 more)

### Community 11 - "Web Dependencies"
Cohesion: 0.08
Nodes (30): @anthropic-ai/sdk, @netlify/functions, react-dom, @types/node, @types/react, @types/react-dom, typescript, vite (+22 more)

### Community 12 - "EDA & Model Notebooks"
Cohesion: 0.12
Nodes (3): gurugram_hourly(), unified_hourly(), first()

### Community 13 - "Plan API (FastAPI)"
Cohesion: 0.14
Nodes (14): _as_of(), check(), _check(), compute_plan(), _end_label(), _fold(), health(), _hhmm() (+6 more)

### Community 14 - "Bills & Charts UI"
Cohesion: 0.16
Nodes (25): recharts, Status(), Waterfall(), BillChange, SITE_NAME, useBillsAt(), useChangesAt(), fmtMonth() (+17 more)

### Community 15 - "Web App Shell"
Cohesion: 0.12
Nodes (19): react, App(), Clock, Ctx, ICON, MORE, OLD, PageId (+11 more)

### Community 16 - "Demand Planner Page"
Cohesion: 0.12
Nodes (24): addMs(), addDays(), BADGE, BookingRow(), DAYS, dow(), END_H, Field() (+16 more)

### Community 17 - "Live Feed Gauges"
Cohesion: 0.15
Nodes (22): Ack, Gauge(), ForecastDay, load(), Site, iso(), COORDS, fetchWeather() (+14 more)

### Community 18 - "Python Assistant"
Cohesion: 0.15
Nodes (16): page_assistant(), answer(), check_numbers(), _fallback_text(), guard(), _numbers(), _risk_out(), _route() (+8 more)

### Community 19 - "Detector Evaluation"
Cohesion: 0.16
Nodes (13): typed_overlap(), heldout_labels_for_diagnostics(), _labels(), onset_ttd(), _overlap(), score(), score_heldout(), score_heldout_onset() (+5 more)

### Community 20 - "Operating Plan"
Cohesion: 0.13
Nodes (12): banquet_delta(), chw_pct(), compose_day(), hh(), in_win(), kwtr_plan(), parse_booking(), plan_day() (+4 more)

### Community 21 - "Plan Validation (TS)"
Cohesion: 0.22
Nodes (19): DayCheck, useDayCheck(), validate(), checkPlan(), CheckResult, applyEvent(), checkActions(), Entry (+11 more)

### Community 22 - "Plan Export Tools"
Cohesion: 0.13
Nodes (8): _event_hours(), ahu_overrun(), data(), main(), matched_refs(), risk_calibration(), tr_frame(), with_events()

### Community 23 - "API Tests"
Cohesion: 0.18
Nodes (17): c(), joined(), post(), test_alias_conflict_is_noted(), test_aliases_are_used_and_unknown_fields_noted(), test_bad_date_and_uncovered_date_422(), test_bad_values_are_noted_not_errors(), test_chw_reason_uses_measured_penalty() (+9 more)

### Community 24 - "Feed Sources"
Cohesion: 0.20
Nodes (20): Bills, Fault, Recon, Feeds, fromFunction(), localSource(), useFeeds(), clipAlert() (+12 more)

### Community 25 - "Baseline Models"
Cohesion: 0.12
Nodes (9): lomo(), rolling(), fit_predict(), make_gbm(), make_ridge(), _ridge_features(), Ens, verify() (+1 more)

### Community 26 - "Web Data Types"
Cohesion: 0.12
Nodes (17): Alert, cache, Hotel, Measure, OptionC, PlanRow, Quality, Risk (+9 more)

### Community 27 - "UI Copy Text"
Cohesion: 0.16
Nodes (18): BILL_STATUS, CATEGORY, CONFIDENCE(), DRIVER, EQUIPMENT, LOAD, measureGroup(), measureName() (+10 more)

### Community 28 - "Forecaster Model"
Cohesion: 0.13
Nodes (7): build_frame(), cv_hourly(), daily_summary(), Forecaster, hot_reference(), shift_plan(), stack_allowance()

### Community 29 - "Plan Booking Form"
Cohesion: 0.16
Nodes (17): Form, Action, Booking, byTime(), PlanDay, riskFor(), API_TIMEOUT_MS, apiPlan() (+9 more)

### Community 30 - "Feedback Ratings"
Cohesion: 0.23
Nodes (9): _api(), _gist(), load(), rating_set(), rounds(), save(), _secret(), storage() (+1 more)

### Community 31 - "Baseline Features & Scores"
Cohesion: 0.22
Nodes (10): scores(), build_features(), cv_rmse(), nmbe(), tr_accuracy(), _bmetrics(), freeze(), live() (+2 more)

### Community 32 - "Operating Plan Tests"
Cohesion: 0.19
Nodes (10): all_days(), days(), random_bookings(), test_banquet_ahu_timing_and_laundry_peak(), test_ev_limit_only_above_920(), test_guardrails_on_generated_days(), test_plan_needs_reference(), test_setpoint_rule() (+2 more)

### Community 33 - "Findings & Option C"
Cohesion: 0.15
Nodes (14): ChatGPT session findings verified, IPMVP Option C, Kickoff deck constraints, OPEN_QUESTIONS.md suggestions, Problem B: avoidable waste not caught in time, Swapped lifts_kw/pool_kw sub-meters (Mar 2026), Modelling approach notes, LightGBM per-hotel baseline (+6 more)

### Community 34 - "Monthly Savings Panel"
Cohesion: 0.23
Nodes (13): MonthSavingsPanel(), Hourly, SITES, useHourlyAll(), alertRupees(), MonthSavings, ms(), rateOf() (+5 more)

### Community 35 - "TS Config"
Cohesion: 0.13
Nodes (14): compilerOptions, isolatedModules, jsx, lib, module, moduleResolution, noEmit, noUnusedLocals (+6 more)

### Community 36 - "Live Forecast & Reports"
Cohesion: 0.24
Nodes (6): main(), add_month(), growth_factor(), load(), main(), saved_plans()

### Community 37 - "T9 Attribution"
Cohesion: 0.22
Nodes (6): _alert_kwh(), _counterfactual(), explain_frames(), f(), predict(), production_baseline()

### Community 38 - "Demand & EV Rules"
Cohesion: 0.29
Nodes (7): compare(), typemask(), first(), all_additions(), demand_alerts(), ev_alerts(), _runs()

### Community 39 - "kW/TR Recalibration"
Cohesion: 0.23
Nodes (6): chw_recost(), fit(), _frame(), _rate(), _runs(), staging_kwtr_alerts()

### Community 40 - "Peak Risk"
Cohesion: 0.36
Nodes (6): assess(), bias_factor(), breach_days(), exceed_prob(), _hist(), stacking_increment()

### Community 41 - "Data Cleanliness Notebook"
Cohesion: 0.22
Nodes (4): flag(), profile(), runs(), ts_regularity()

### Community 42 - "Plan Parity Tests"
Cohesion: 0.29
Nodes (4): original_totals(), cases(), python_plan(), test_python_and_typescript_plans_match()

### Community 43 - "Data Cleaning"
Cohesion: 0.44
Nodes (8): clean_context(), clean_goa(), clean_gurugram(), clean_jaipur(), clean_submeters(), main(), read(), runs()

### Community 44 - "Forecast UI Wrapper"
Cohesion: 0.33
Nodes (4): assess(), day_view(), scenario(), state()

### Community 45 - "Ratings Function"
Cohesion: 0.43
Nodes (5): COLS, gh(), gistId(), parseCSV(), read()

### Community 46 - "Today Plan Card"
Cohesion: 0.38
Nodes (6): BADGE, hourOf(), span(), TodayPlanCard(), TAG, CheckStep

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

## Knowledge Gaps
- **59 isolated node(s):** `ps12-energy`, `Four Stages (Understand/Talk/Build/Get bid on)`, `Check-in 2 MVP (deployed URL + one-page note)`, `Check-in 3 Internal Auction (16 Nov)`, `Five-Step Method (Frame/Find/Map/Build/Prove)` (+54 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 393 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `us()` connect `Live Year & Data Quality` to `Demand & EV Rules`?**
  _High betweenness centrality (0.018) - this node is a cross-community bridge._
- **What connects `ps12-energy`, `Four Stages (Understand/Talk/Build/Get bid on)`, `Check-in 2 MVP (deployed URL + one-page note)` to the rest of the system?**
  _59 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Live Year & Data Quality` be split into smaller, more focused modules?**
  _Cohesion score 0.05191256830601093 - nodes in this community are weakly interconnected._
- **Why does `build_features()` connect `Baseline Features & Scores` to `Bills & Savings Engine`, `Alert Cards`, `T9 Attribution`, `Demand & EV Rules`, `Peak-kVA Forecast`, `EDA & Model Notebooks`, `Plan Export Tools`, `Baseline Models`, `Forecaster Model`?**
  _High betweenness centrality (0.012) - this node is a cross-community bridge._
- **Should `Bills & Savings Engine` be split into smaller, more focused modules?**
  _Cohesion score 0.0576271186440678 - nodes in this community are weakly interconnected._
- **Should `Brief: Tests & Guardrails` be split into smaller, more focused modules?**
  _Cohesion score 0.056107539450613676 - nodes in this community are weakly interconnected._
- **Should `Web Assistant (TS)` be split into smaller, more focused modules?**
  _Cohesion score 0.05297532656023222 - nodes in this community are weakly interconnected._