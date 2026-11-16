# CLAUDE.md — PS-12 Energy Optimisation for Hotels (Applied AI Challenge)

Build an energy-intelligence product for Saffron Suites (fictional; Gurugram 220 rooms / Jaipur 160 / Goa 140): per-hotel baseline, load/peak forecast,
context-aware anomaly detection, costed explanations and alerts, bill reconciliation, IPMVP Option C savings, and an engineer-facing UI at a public URL.
Full brief, acceptance tests (T1–T10), metrics, schemas, findings and progress log: **read `CONTEXT.md` first.** Source briefs are the two `.docx` files.

## Commands (Windows; Python is NOT on PATH — always go through uv)
- Run a script: `uv run python <file>`; add a package: `uv add <pkg>` (dev: `uv add --dev <pkg>`); rebuild env: `uv sync`. Never `pip install`.
- Rebuild clean data: `uv run python src/clean_data.py` (reads the raw `.xlsx`, writes `data/clean/*.parquet`).
- Rebuild unified hourly table: `uv run python src/features.py` (→ `data/clean/meter_hourly_all.parquet`).
- Notebooks are authored as `# %%` percent-format scripts in `notebooks/*.py` and compiled + executed into `.ipynb`:
  `uv run python tools/build_notebook.py notebooks/02_eda.py notebooks/02_eda.ipynb`. Edit the `.py`, then rebuild; don't hand-edit the `.ipynb`.
- Set `PYTHONIOENCODING=utf8` when printing ₹ / ° / × in a Windows shell, otherwise printing raises UnicodeEncodeError.

## Layout
- `PS-12_*.xlsx` / `.docx` — raw inputs. Never modify.
- `src/clean_data.py` — cleaning rules. `src/features.py` — `gurugram_hourly()`, `unified_hourly()`, `cooling_degree_hours()`, site constants.
- `data/clean/` — cleaned parquet (14 tables + `meter_hourly_all`). Generated; rebuild rather than edit.
- `notebooks/01_data_cleanliness`, `02_eda` — `.py` source + executed `.ipynb`.
- `tools/build_notebook.py` — percent-script → executed notebook.

## Data rules you must respect
- **Label leakage:** `anomaly_labels` must not inform the detector beyond the tuning window. Tune on anomalies starting **before 1 Apr 2026**; report results on those **from 1 Apr 2026**. The owner has allowed post-April labels to be used to *check* accuracy/precision (diagnostics only, via `evaluation.heldout_labels_for_diagnostics()`, as in notebook 06) but never to fit rules, thresholds, profiles or models; any change made after looking is post-hoc and must be labelled so. The cleaned `anomaly_labels.parquet` is a plain copy.
- **Use cleaned tables**, not raw workbooks. Honour the flags: `exclude_from_model` (Gurugram meter-fault intervals), `is_imputed` (Jaipur 10 h), `is_dg`, `is_provisional` (Goa Jul 2026 bill), `ends_after_midnight` (events).
- Total site energy = `grid_kwh + dg_kwh`. During DG the grid columns read 0 and Gurugram `kw_avg` is 0 — use `total_kwh` for load and drop DG hours when comparing against sub-meters.
- Gurugram meter faults corrupt only the billed columns (`kw_avg`/PF stay valid). Cleaned values are rebuilt from `kw_avg`; raw kept in `*_raw`. The Gurugram Jan/Jul/Aug **bills** still contain the corrupted readings — never "fix" bills.
- ToD windows differ per hotel (GGN peak 18–22, JAI 17–23, GOA 18–22 / off-peak 22–06). Don't reuse one window for all.
- Hourly Gurugram = sum of energy, **max** of 15-min kVA, PF = kWh/kVAh. Always build it with `gurugram_hourly()`.
- Pool genuinely rises in winter (heating); don't treat it as a fault. CHW setpoint 5.5 °C hours are real operational waste, not data errors — keep them.

## Product guardrails (from the brief — non-negotiable)
- Recommend, never control; any simulated automation needs an override + audit log. Kitchen exhaust, guest-room thermostats, fire/life-safety/lifts are never auto-controlled (T10 must refuse).
- Never recommend CHW setpoint < 6.5 °C, or breach the comfort/safety limits in `CONTEXT.md` §9.
- No alert for conditions explained by weather, occupancy or events. Every alert shows its evidence. Meter faults are suppressed (T5), never alerts or savings.
- **LLM text may only state facts present in the data; all numbers come from the models, not the LLM.**
- Savings only against an adjusted (IPMVP Option C) baseline. Don't claim the tariffs are real.

## Conventions
- Site codes `GGN`, `JAI`, `GOA`; timestamps are IST, start-of-interval. Period Oct 2025–Sep 2026.
- pandas 3.x / numpy 2.x: strings are `str` dtype, use `Series.dt.day_of_week` (not `dayofweek`), `include_groups=False` in `groupby.apply`; align boolean masks by index or use `.to_numpy()`.
- Match existing style: short module docstrings explaining *why*, comments only where the reason isn't obvious.
- Verify before claiming: results are checked against the brief's own numbers (see `CONTEXT.md` §20); keep doing that for new results.

## API (Cloud Run)
- Service `saffron-api`, project `saffron-suites`, region `asia-south1`: https://saffron-api-579804303171.asia-south1.run.app.
  The Netlify site proxies `/api/*` to it (`web/netlify.toml`), e.g. `/api/health`, `POST /api/plan`.
- `api/main.py` (FastAPI): `GET /health`; `POST /plan` {date, rooms, guests, covers, tmax | temps[24], bookings[{hall A/B/A+B, start, end, guests}]}
  returns hourly forecast (kW, peak kVA, cooling TR), peak risk, the operating plan (`src/operating_plan.py`) and plain-English `notes`.
  Odd inputs are clamped/flagged in `notes`, never an error; only a date outside the live year returns 422. Recommend only.
- Jaipur / Goa (16 Nov): `site` JAI / GOA on `/plan`, `/forecast`, `/risk`, `/check`, `/savings`. Venues validated per hotel (aliases like "lawns",
  "ballroom"; unknown venues skipped with a note). Plan uses only levers their sub-meters can check (`operating_plan.plan_site`): staging (checked by
  total kW/TR), CHW 7.0/8.0 °C (shown, never counted: no setpoint meter), event lighting ±30 min, Goa pool filtration (≥ 8 h), laundry, demand watch
  (step only within 8 % of 700 / 600 kVA). Models: `uv run python tools/train_api_models.py` (hourly CV(RMSE) JAI kW 5.0 / TR 4.5 / kVA 5.3 %,
  GOA 5.4 / 5.4 / 4.9 %); also run at the end of `export_api_models.py`. The web plans Jaipur / Goa through the API only (no offline estimate).
- Models in `models/` are trained on **Oct 2025 – Sep 2026 only** and never refitted at run time; rebuild with
  `uv run python tools/export_api_models.py` (also writes the live-year context, matched-day refs and meta). The image reads no `data/`.
- Redeploy from the repo root (Dockerfile at root; `.gcloudignore` uploads only Dockerfile, `api/`, `src/`, `models/`):
  `gcloud run deploy saffron-api --source . --region asia-south1 --allow-unauthenticated --min-instances 1 --max-instances 3 --memory 1Gi --cpu 1 --timeout 30 --project saffron-suites`
- **min-instances is 1 only to keep it warm for the demos on 16 and 18 Nov 2026. Set it back to 0 afterwards:**
  `gcloud run services update saffron-api --region asia-south1 --min-instances 0 --project saffron-suites`
- Windows curl to `*.run.app` may fail with `CRYPT_E_REVOCATION_OFFLINE`; use `curl --ssl-no-revoke`.

## Status
Done: environment, data audit, cleaning, Gurugram hourly feature, EDA, hourly baseline per hotel (`src/baseline.py`, `notebooks/03_baseline`; out-of-fold predictions in `data/clean/baseline_oof.parquet`). waste-type catalogue (`src/waste_types.py`, notebook 04), detector (`src/detector.py`, `src/evaluation.py`, notebook 05; alerts in `data/clean/alerts.parquet`). Held-out: precision 98%, recall 96%, time-to-detect met (1.0 h median from first appearance in the data, the owner-confirmed definition; 3.0 h from label start is secondary); post-hoc rules for contract-demand breach and EV charger night draw now exist (`src/demand_ev_rules.py`, notebook 08; 5 alerts, 5 matching labels, 0 false; not clean held-out). The detector is frozen: further changes are post-hoc, not clean held-out. Day-ahead kVA forecast + stacking watch + flexible-load shift plan done (`src/forecast.py`, notebook 07): daily-peak MAPE 5.4%, 59% of days within ±5% (per-day ±5% not achievable: noise floor); the three >1,000 kVA days are load stacking, caught only by the stacking watch (in-sample). Post-hoc: demand and EV rules (notebook 08). Built 10 Nov: bill reconciliation (`src/bills.py`; all 36 bills rebuild; demand = min(max(MD, 75% CD), CD) × rate + penalty on MD > CD), T9 attribution (`src/attribution.py`), alert cards, savings plan + Option C stats (`src/savings.py`; identified 3.0% of bill — below the 8–12% target, stated honestly), assistant (`src/assistant.py`), Streamlit app (`app.py`, data from `src/build_app_data.py`). Built 10 Nov (later, post-hoc): `src/peak_risk.py` (T7: bias correction, P(>1,000 kVA), stacking scenario from earlier breach days → T7 passes), `src/recalibration.py` (kW/TR staging rule — BMS chillers_running undercounts; threshold from the empty gap in March kW/TR; CHW cost from metered 6.5–10 % penalty; staging ₹ 0.23→1.04× key, CHW 0.5→0.9×), savings: two totals, 5.9% from operations · 7.1% with one capital item (pump VFDs); live year 6.0% · 7.2% incl. the daily plan's non-overlapping demand saving (`tools/plan_savings_live.py`, `data/live/savings_live.md`). Verified plan ₹ (approved steps) is an operational measure on the plan pages and monthly report, never in the savings headline. Rating set frozen as 20 IDs in `src/feedback.py`. Linux/cloud: `uv sync --python <system python>` works without the Windows .venv. Details in `CONTEXT.md` §18, §22.
Live year and feed (15 Nov): `data/live/` is a **synthetic** year, 1 Oct 2026 – 30 Sep 2027 (`tools/make_live_year.py`: source weeks of the original year,
labelled waste removed, new anomalies at the original yearly rates, 1 comms fault per site, tariffs +3 %, bills issued on the 5th of the next month; report in
`data/live/_report.md`). `SAFFRON_DATA=data/live` points every module at it (`src/features.py`: `CLEAN`, `APP`). `tools/run_live_year.py` runs the frozen pipeline
on it with nothing refitted (detector profiles, recalibration and baseline from the original year; only the tariff rates are re-read) and writes
`data/live/results.md` (a robustness check on synthetic data, not a clean held-out test). `tools/export_web_data.py --live` writes `web/public/data/live_feed/` and
a copy bundled with the Netlify functions. The web app runs on the real IST clock with no replay offset. Today reads `/.netlify/functions/feed` (refreshed every
5 min; falls back to the static files when the function is unavailable). Equipment, Costs, Bills and Ask show the original year plus the live year up to the
current hour, and live bills once issued (Nov 2026 appears from 5 Dec). One rule, `web/src/feedcore.ts` (shared by the browser and the functions): no row after
the current hour is ever shown, and a running alert is cut to its readings so far. Look back covers any hour from 1 Oct 2025 to now. Bill-change splits work within
one data year only, so Oct 2026 has no pair with Sep 2026. Peak demand: Tomorrow / Plan ahead use the Open-Meteo forecast with per-date scenarios from
`tools/export_live_forecast.py <first_date> <days>` (files in `web/public/data/live/`; re-run before 9 Jan 2027), plus today's actual peak so far from the feed.
Rebuild order after a data change: make_live_year → run_live_year → export_web_data (both modes) → acceptance.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- When graphify-out/graph.json exists, run `graphify query "<question>"` before your first grep, search or source-file read for a codebase question, and put this rule in every subagent prompt that explores code. Read raw files only for lines the graph or an earlier read already located. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. When the answer is under a Markdown heading, `graphify section "<heading>"` prints that section's text, so the .md need not be opened. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
- A committed graphify-out/graph.json is rewritten whole on every build, so a large diff to it in a pull request is expected. Do not flag it as churn or suggest skipping the graph rebuild or its hooks.
