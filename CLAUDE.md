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
- **Label leakage:** `anomaly_labels` must not inform the detector beyond the tuning window. Tune on anomalies starting **before 1 Apr 2026**; report results on those **from 1 Apr 2026**. Do not browse post-April label rows. The cleaned `anomaly_labels.parquet` is a plain copy.
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

## Status
Done: environment, data audit, cleaning, Gurugram hourly feature, EDA. Next: hourly baseline model per hotel (CV(RMSE)/NMBE on held-out months), then waste-type list, detector, alerts, UI. Details in `CONTEXT.md` §18.
