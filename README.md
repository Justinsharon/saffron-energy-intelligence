# Saffron Suites — Energy Intelligence

An energy-intelligence product for Saffron Suites, a fictional three-hotel group (Gurugram 220 rooms, Jaipur 160, Goa 140), built for the Masters' Union Applied AI Challenge (PS-12).

It learns each hotel's weather-, occupancy- and event-adjusted baseline, forecasts load and Gurugram peak kVA, and detects waste and faults without alerting on conditions that weather, occupancy or events explain. Each finding comes with evidence, a ₹ cost and a recommended action. It also reconciles monthly bills by component and reports savings against an adjusted IPMVP Option C baseline.

The product **recommends and never controls equipment**. All data is synthetic and the tariffs are fictionalised.

## Status

| Stage | State |
|---|---|
| Environment, data audit, cleaning | Done |
| Hourly feature table, EDA | Done |
| Per-hotel baseline (CV(RMSE) 8.3 / 5.0 / 5.4 % hourly, NMBE ±0.1 %) | Done |
| Context-aware detector + meter-fault stream (held-out precision 98 %, recall 96 %, TTD 1.0 h) | Done |
| Costed alert cards (evidence, ₹/h, ₹/day, cause, action, guardrail) | Done |
| Bill reconciliation (36 bills rebuilt line by line; fault months billed vs corrected; provisional Goa bill) | Done |
| Bill-change explanation (T9: weather / occupancy / events / anomalies / demand / diesel) | Done |
| Gurugram day-ahead peak forecast + stacking watch + shift plan (T7) | Done |
| Savings plan (energy / ToD / demand) + IPMVP Option C statistics | Done |
| Assistant (Claude + tools, guardrails, number check; rules fallback) | Done |
| Streamlit app (`app.py`) | Done — deploy on Streamlit Community Cloud |

The detailed progress log, acceptance tests (T1–T10), data schemas and findings are in [CONTEXT.md](CONTEXT.md).

## Web app (new UI, `web/`)

A React + TypeScript front end built around the four users in the brief (duty engineer, chief engineer, GM, finance), with role tabs
Shift / Demand / Engineering / GM / Finance / Ask and a replay clock. It reads static JSON exported from the models and uses two Netlify
functions: `assistant` (Claude with tools, safety guard and number check) and `ratings` (alert ratings in a GitHub Gist).

```bash
uv run python src/build_app_data.py && uv run python tools/export_web_data.py   # refresh web/public/data/
cd web && npm install && npm run dev                                              # http://localhost:5173
```
Deploy on Netlify: import the repo, base directory `web`; environment variables `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, `RATINGS_GIST_ID`.

## Run the Streamlit app

```bash
uv sync
uv run python src/build_app_data.py      # precompute data/app/*.parquet (already committed)
uv run streamlit run app.py
```

Claude answers in the Assistant need `ANTHROPIC_API_KEY` in `.streamlit/secrets.toml` (or the Streamlit Cloud secrets box). Without it the
assistant uses the built-in rules engine with the same tools.

## Repository layout

| Path | Contents |
|---|---|
| `src/clean_data.py` | Cleaning rules: raw workbooks to `data/clean/*.parquet` |
| `src/features.py` | Hourly Gurugram table, unified hourly table for all hotels, cooling degree hours |
| `src/baseline.py`, `detector.py`, `waste_types.py`, `evaluation.py` | Baseline, detector, waste catalogue, scoring |
| `src/forecast.py`, `demand_ev_rules.py` | Day-ahead kVA forecast; post-hoc demand / EV rules |
| `src/bills.py`, `attribution.py` | Bill reconciliation; bill-change attribution (T9) |
| `src/alert_cards.py`, `savings.py`, `assistant.py` | Alert presentation, savings plan + Option C, assistant |
| `app.py`, `src/build_app_data.py`, `data/app/` | Web app and its precomputed inputs |
| `data/clean/` | Cleaned parquet tables (generated; rebuild rather than edit) |
| `src/baseline.py`, `detector.py`, `evaluation.py`, `waste_types.py` | Baseline model, rule + residual detector, scoring with the tune/report split, waste-type catalogue |
| `src/forecast.py`, `demand_ev_rules.py` | Day-ahead kVA forecast and stacking watch; post-hoc demand and EV-charger rules |
| `notebooks/` | `01`–`08`: data cleanliness, EDA, baseline, waste types, detector, held-out diagnostics, forecast, demand/EV rules (`.py` sources and executed `.ipynb`) |
| `tools/build_notebook.py` | Compiles a `# %%` percent-format script into an executed notebook |
| `docs/modelling_approach.md` | Modelling approach |
| `CONTEXT.md` | Full brief, requirements, schemas, findings, progress log |
| `OPEN_QUESTIONS.md` | Questions for the problem owner |
| `CLAUDE.md` | Working rules and conventions for the project |

The two `.docx` files are the source briefs. The raw `PS-12_*.xlsx` workbooks are not in the repository; place them in the project root to re-run the cleaning step.

## Getting started

The project uses [uv](https://docs.astral.sh/uv/) with Python 3.11.

```bash
uv sync                                   # create the environment
uv run python src/clean_data.py           # raw .xlsx -> data/clean/*.parquet (needs the workbooks)
uv run python src/features.py             # -> data/clean/meter_hourly_all.parquet
uv run python tools/build_notebook.py notebooks/02_eda.py notebooks/02_eda.ipynb
```

Edit the notebook `.py` file and rebuild; don't hand-edit the `.ipynb`. On Windows, set `PYTHONIOENCODING=utf8` when printing ₹, ° or × in a shell.

## Data handling rules

- **No label leakage.** The detector is tuned only on anomalies starting before 1 Apr 2026 and scored on those from 1 Apr 2026.
- **Cleaned tables only,** honouring the flags `exclude_from_model` (Gurugram meter faults), `is_imputed` (Jaipur gap), `is_dg`, `is_provisional` (Goa Jul 2026 bill) and `ends_after_midnight` (events).
- **Total site energy** is `grid_kwh + dg_kwh`.
- **Time-of-day windows differ per hotel.**
- **Bills are never corrected,** even where they contain corrupted meter readings.

## Product guardrails

- Recommend, never control. Kitchen exhaust, guest-room thermostats and fire/life-safety/lifts are never automated.
- Never recommend a CHW setpoint below 6.5 °C or breach the comfort and safety limits.
- No alerts for conditions explained by weather, occupancy or events. Every alert shows its evidence, and meter faults are suppressed.
- Any text from an LLM may only state facts present in the data; all numbers come from the models.
- Savings are claimed only against an adjusted (IPMVP Option C) baseline.
