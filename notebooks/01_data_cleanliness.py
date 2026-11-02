# %% [markdown]
# # 01 · Data cleanliness check — all workbooks, all sheets
# Checks each of the 5 PS-12 workbooks sheet by sheet: shape, dtypes, nulls, duplicates, timestamp coverage, value ranges,
# plus targeted tests for the **deliberate issues** listed in each README.
#
# **Anti-leakage:** `anomaly_labels` is only checked structurally; any row-level content shown is restricted to anomalies starting **before 1 Apr 2026** (tuning window).
#
# This notebook only *diagnoses*. It does not modify the source files.

# %%
from pathlib import Path
import numpy as np
import pandas as pd

pd.set_option("display.max_columns", 50, "display.width", 200, "display.max_rows", 100)

ROOT = Path.cwd()
if not (ROOT / "PS-12_meter_data.xlsx").exists():
    ROOT = ROOT.parent
FILES = {
    "meter": "PS-12_meter_data.xlsx",
    "bms": "PS-12_bms_submeters.xlsx",
    "context": "PS-12_context_and_bills.xlsx",
    "anomaly": "PS-12_anomaly_test_set.xlsx",
}
TUNING_END = pd.Timestamp("2026-04-01")

# Load every sheet of every workbook (README sheets are kept as text, not profiled as data)
raw = {}      # (workbook, sheet) -> DataFrame
for key, fname in FILES.items():
    xl = pd.read_excel(ROOT / fname, sheet_name=None)
    for sheet, df in xl.items():
        raw[(key, sheet)] = df
print(f"{'workbook':<9}{'sheet':<30}{'rows':>8}{'cols':>6}")
for (k, s), df in raw.items():
    print(f"{k:<9}{s:<30}{len(df):>8}{df.shape[1]:>6}")

# %% [markdown]
# ## Helpers

# %%
issues = []   # (workbook, sheet, severity, finding)

def flag(wb, sheet, severity, msg):
    issues.append((wb, sheet, severity, msg))
    print(f"  [{severity}] {msg}")

def data_sheets(wb):
    return {s: df for (k, s), df in raw.items() if k == wb and s != "README"}

def profile(wb, sheet, df, key_cols=None, ts_col=None):
    """Generic profile: dtypes, nulls, full-row duplicates, key duplicates, constant columns."""
    print(f"\n=== {wb} / {sheet}  ({len(df):,} rows x {df.shape[1]} cols)")
    nulls = df.isna().sum()
    out = pd.DataFrame({"dtype": df.dtypes.astype(str), "nulls": nulls,
                        "null_%": (nulls / len(df) * 100).round(2), "unique": df.nunique()})
    display(out)
    if nulls.sum():
        flag(wb, sheet, "warn", f"{int(nulls.sum())} null cells in {int((nulls > 0).sum())} column(s): {list(nulls[nulls > 0].index)}")
    n_dup = int(df.duplicated().sum())
    if n_dup:
        flag(wb, sheet, "warn", f"{n_dup} fully duplicated rows")
    if key_cols:
        n_key = int(df.duplicated(subset=key_cols).sum())
        if n_key:
            flag(wb, sheet, "warn", f"{n_key} duplicate keys on {key_cols}")
    const = [c for c in df.columns if df[c].nunique(dropna=True) <= 1]
    if const:
        flag(wb, sheet, "info", f"constant columns: {const}")
    if ts_col:
        ts = pd.to_datetime(df[ts_col], errors="coerce")
        bad = int(ts.isna().sum() - df[ts_col].isna().sum())
        if bad:
            flag(wb, sheet, "error", f"{bad} unparseable values in {ts_col}")
        print(f"  range: {ts.min()} -> {ts.max()}")

def numeric_summary(df, cols=None):
    cols = cols or df.select_dtypes("number").columns
    s = df[cols].describe().T[["min", "mean", "max"]]
    s["negatives"] = (df[cols] < 0).sum()
    s["zeros"] = (df[cols] == 0).sum()
    return s

def ts_regularity(wb, sheet, ts, freq):
    """Missing / duplicate timestamps against an expected regular grid."""
    ts = pd.to_datetime(ts).dropna()
    full = pd.date_range(ts.min(), ts.max(), freq=freq)
    dup = int(ts.duplicated().sum())
    missing = full.difference(ts.unique())
    print(f"  expected {len(full):,} @ {freq}, got {len(ts):,} rows ({ts.nunique():,} unique); missing={len(missing)}, duplicate={dup}")
    if dup:
        flag(wb, sheet, "warn", f"{dup} duplicate timestamps")
    if len(missing):
        flag(wb, sheet, "warn", f"{len(missing)} missing timestamps, first {missing[:3].tolist()}")
    return missing

def runs(mask):
    """Return (start_idx, length) of consecutive True runs in a boolean array."""
    m = np.asarray(mask, dtype=bool)
    if not m.any():
        return []
    d = np.diff(np.r_[0, m.astype(int), 0])
    return list(zip(np.where(d == 1)[0], (np.where(d == -1)[0] - np.where(d == 1)[0])))

# %% [markdown]
# ## READMEs — the datasets' own list of known issues (for reference)

# %%
for (k, s), df in raw.items():
    if s == "README":
        txt = df.fillna("").astype(str).apply(lambda r: " ".join(v for v in r if v), axis=1)
        hit = txt[txt.str.startswith("•")]
        print(f"\n{FILES[k]}")
        for line in hit:
            print("  ", line)

# %% [markdown]
# # 1 · PS-12_meter_data.xlsx
# Sheets: `gurugram_15min`, `jaipur_hourly`, `goa_hourly`.
# Known issues: Gurugram comms faults (flat/zero), Jaipur 10-hour gap, Goa 24 duplicate rows, DG periods read 0 on grid columns.

# %%
M = data_sheets("meter")
for s, df in M.items():
    profile("meter", s, df, key_cols=["timestamp"], ts_col="timestamp")
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    display(numeric_summary(df))

# %%
# Regular grid + duplicates, per sheet
ts_regularity("meter", "gurugram_15min", M["gurugram_15min"]["timestamp"], "15min")
ts_regularity("meter", "jaipur_hourly", M["jaipur_hourly"]["timestamp"], "h")
ts_regularity("meter", "goa_hourly", M["goa_hourly"]["timestamp"], "h")

# %%
# Gurugram: flat lines and zeros while supplied by GRID  (candidate meter comms faults)
g = M["gurugram_15min"].sort_values("timestamp").reset_index(drop=True)
grid = g["supply_source"].eq("GRID")
# Fault signature: grid_kwh, grid_kvah and kva_demand all repeat the previous value (flat line) or sit at 0 while on GRID.
# Natural load noise never repeats to 2 d.p. for >= 1 h; DG periods are excluded because grid columns are legitimately 0 there.
rep = (g[["grid_kwh", "grid_kvah", "kva_demand"]].diff() == 0).all(axis=1)
run_id = (~rep).cumsum()                                  # a flat run = first reading + its repeats
run_len = g.groupby(run_id)["grid_kwh"].transform("size")
flat = (run_len >= 4) & grid                              # >= 1 h of 15-min intervals
fault_cands = []
for start, ln in runs(flat):
    kind = "zeros on GRID" if g.loc[start, "grid_kwh"] == 0 else "flat line"
    fault_cands.append((kind, g.loc[start, "timestamp"], g.loc[start + ln - 1, "timestamp"], ln, g.loc[start, "grid_kwh"]))
fc = pd.DataFrame(fault_cands, columns=["type", "from", "to", "intervals", "stuck_grid_kwh"])
display(fc)
if len(fc):
    w0 = g[(g.timestamp >= fc.loc[0, "from"]) & (g.timestamp <= fc.loc[0, "to"])]
    print("kw_avg during first fault window (does it also freeze?):", w0.kw_avg.nunique(), "distinct values over", len(w0), "rows")
if len(fc):
    flag("meter", "gurugram_15min", "warn", f"{len(fc)} meter-fault run(s) (>=1 h) in grid_kwh/kvah/kVA ({fc['from'].dt.strftime('%d %b').tolist()}) -> mask from baseline; kw_avg and PF stay live and track the sub-meters (checked), so the billed columns are corrupted, not the load; rebuild them from kw_avg")
print("DG intervals:", int((g.supply_source == 'DG').sum()),
      "| DG rows with non-zero grid kWh:", int(((g.supply_source == 'DG') & (g.grid_kwh > 0)).sum()),
      "| GRID rows with dg_kwh>0:", int(((g.supply_source == 'GRID') & (g.dg_kwh > 0)).sum()))

# %%
# Physical consistency: kVAh >= kWh, PF in (0,1], kVA >= kW
for s, df in M.items():
    grid_rows = df[df["grid_kwh"] > 0]
    bad_kvah = int((grid_rows["grid_kvah"] < grid_rows["grid_kwh"] - 1e-6).sum())
    bad_pf = int(((grid_rows["power_factor"] > 1) | (grid_rows["power_factor"] <= 0)).sum())
    print(f"{s}: kVAh<kWh rows={bad_kvah}, PF out of (0,1]={bad_pf}, PF min={grid_rows['power_factor'].min():.3f}")
    if bad_kvah or bad_pf:
        flag("meter", s, "error", f"kVAh<kWh in {bad_kvah} rows / bad PF in {bad_pf} rows")

# %%
# Jaipur: blank block (the 10-hour gap)
j = M["jaipur_hourly"].sort_values("timestamp").reset_index(drop=True)
blank = j["grid_kwh"].isna() | j["kw_avg"].isna()
for start, ln in runs(blank):
    print(f"Jaipur blank block: {j.loc[start,'timestamp']} for {ln} h")
    flag("meter", "jaipur_hourly", "warn", f"blank block of {ln} h starting {j.loc[start,'timestamp']} -> interpolate or exclude")

# Goa: duplicates
go = M["goa_hourly"]
dups = go[go.duplicated("timestamp", keep=False)].sort_values("timestamp")
print(f"Goa duplicate-timestamp rows: {len(dups)} ({go.duplicated('timestamp').sum()} extras); identical copies: "
      f"{go.duplicated().sum()}")
display(dups.head(6))

# %% [markdown]
# # 2 · PS-12_bms_submeters.xlsx
# Sheets: `gurugram_submeters_hourly`, `jaipur_goa_submeters_hourly`, `bms_command_log`, `equipment_register`.
# Known issues: Gurugram `lifts_kw` / `pool_kw` swapped in March 2026; sub-meters ±1% and don't sum to main meter; command log is thinned.

# %%
B = data_sheets("bms")
profile("bms", "gurugram_submeters_hourly", B["gurugram_submeters_hourly"], key_cols=["timestamp"], ts_col="timestamp")
profile("bms", "jaipur_goa_submeters_hourly", B["jaipur_goa_submeters_hourly"], key_cols=["site", "timestamp"], ts_col="timestamp")
profile("bms", "bms_command_log", B["bms_command_log"], ts_col="timestamp")
profile("bms", "equipment_register", B["equipment_register"], key_cols=["site", "equipment_id"])

# %%
gs = B["gurugram_submeters_hourly"].copy()
gs["timestamp"] = pd.to_datetime(gs["timestamp"])
display(numeric_summary(gs))
ts_regularity("bms", "gurugram_submeters_hourly", gs["timestamp"], "h")
jg = B["jaipur_goa_submeters_hourly"].copy()
jg["timestamp"] = pd.to_datetime(jg["timestamp"])
for site, d in jg.groupby("site"):
    print(site, end=" ")
    ts_regularity("bms", f"jaipur_goa_submeters_hourly[{site}]", d["timestamp"], "h")
display(numeric_summary(jg))

# %%
# Lifts vs pool swap: monthly mean of each. Lifts ~ small & flat-ish; pool has own level. Look for March reversal.
mm = gs.set_index("timestamp")[["lifts_kw", "pool_kw"]].resample("MS").mean().round(2)
mm["lifts_vs_median_%"] = ((mm.lifts_kw / mm.lifts_kw.median() - 1) * 100).round(0)
display(mm)
# Pool is genuinely seasonal (winter heating), so test the stable meter: lifts should hover near its median every month.
odd = mm[mm["lifts_vs_median_%"].abs() > 25]
if len(odd):
    flag("bms", "gurugram_submeters_hourly", "warn", f"lifts_kw level abnormal in {[d.strftime('%Y-%m') for d in odd.index]} (pool_kw carries the lifts level) -> lifts/pool swapped; swap back")

# %%
# Chiller consistency: chillers_running vs number of chillers with kW > 0; kW/TR efficiency sanity
ch = gs[["chiller_ch1_kw", "chiller_ch2_kw", "chiller_ch3_kw"]]
n_on = (ch > 1).sum(axis=1)
mismatch = (n_on != gs["chillers_running"])
print("chillers_running != count(kW>1):", int(mismatch.sum()), "hours")
if mismatch.sum():
    flag("bms", "gurugram_submeters_hourly", "info", f"{int(mismatch.sum())} h where chillers_running disagrees with chiller kW")
loaded = gs[gs["chiller_load_tr"] > 20].copy()
loaded["kw_per_tr"] = ch.loc[loaded.index].sum(axis=1) / loaded["chiller_load_tr"]
print("kW/TR (load>20 TR) quantiles:"); display(loaded["kw_per_tr"].describe(percentiles=[.01, .5, .99]).round(3))
print("CHW setpoint values:", sorted(gs["chw_setpoint_c"].dropna().unique())[:12])
low_sp = gs.loc[gs.chw_setpoint_c < 6.5, "timestamp"]
print("setpoint < 6.5 C (operational breach of guide limit, not a data error):", len(low_sp), "h",
      f"| first {low_sp.min()} last {low_sp.max()}")
if len(low_sp):
    flag("bms", "gurugram_submeters_hourly", "info", f"{len(low_sp)} h with CHW setpoint 5.5 C (< 6.5 C guide limit) - real operational waste, keep in data; do not 'clean'")

# %%
# Sub-meter total vs main meter (hourly), Gurugram
gm = M["gurugram_15min"].copy()
main_h = gm.set_index("timestamp")["kw_avg"].resample("h").mean()
sub_cols = [c for c in gs.columns if c.endswith("_kw")]
sub_sum = gs.set_index("timestamp")[sub_cols].sum(axis=1)
cmp_ = pd.concat([main_h.rename("main"), sub_sum.rename("subs")], axis=1).dropna()
cmp_ = cmp_[cmp_.main > 0]
rel = (cmp_.subs - cmp_.main) / cmp_.main
print(f"sub-sum vs main: median diff {rel.median():.2%}, 5-95% [{rel.quantile(.05):.2%}, {rel.quantile(.95):.2%}]  (incl. other_kw)")
big = (rel.abs() > 0.1).sum()
print("hours where |diff| > 10%:", int(big), "(these overlap meter-fault periods if main meter was flat/zero)")

# %%
# BMS command log
cl = B["bms_command_log"].copy()
cl["timestamp"] = pd.to_datetime(cl["timestamp"])
print(cl.groupby(["site", "point"]).size().unstack(0).fillna(0).astype(int))
print("changed_by:", cl.changed_by.value_counts().to_dict())
print("source:", cl.source.value_counts().to_dict())
print("hand-mode (new_value==2) entries:", int((cl.new_value == 2).sum()))
unsorted = not cl["timestamp"].is_monotonic_increasing
print("sorted by time:", not unsorted)
# old_value should equal the previous new_value per point (continuity); thinned log will break this
cl = cl.sort_values(["site", "point", "timestamp"])
cont = cl.groupby(["site", "point"]).apply(lambda d: (d["old_value"].values[1:] != d["new_value"].values[:-1]).sum(), include_groups=False)
print("continuity breaks old_value != previous new_value:\n", cont[cont > 0])
display(B["equipment_register"])

# %%
# Follow-up 1: are the big sub-meter vs main-meter gaps explained? (|diff| > 10%)
big = cmp_[rel.abs() > 0.10]
dg_h = (M["gurugram_15min"].set_index("timestamp").supply_source.eq("DG").astype(int).resample("h").max() > 0)
in_dg = dg_h.reindex(big.index).fillna(False)
in_fault = pd.Series(False, index=big.index)
for _, r in fc.iterrows():
    in_fault |= (big.index >= r["from"].floor("h")) & (big.index <= r["to"])
print(f"{len(big)} large-gap hours | on diesel (main kw_avg reads 0): {int(in_dg.sum())} | inside meter-fault windows: {int(in_fault.sum())} | unexplained: {int((~in_dg & ~in_fault).sum())}")
if (~in_dg & ~in_fault).sum():
    flag("bms", "gurugram_submeters_hourly", "warn", f"{int((~in_dg & ~in_fault).sum())} sub-vs-main gaps >10% unexplained by DG or meter faults")
else:
    flag("bms", "gurugram_submeters_hourly", "info", "all >10% sub-vs-main gaps fall in diesel hours (main kw_avg=0 on DG); exclude DG hours when comparing")

# %%
# Follow-up 2: text-field consistency (whitespace, case variants, small category sets) across all data sheets
txt_issues = []
for (wb, sheet), df in raw.items():
    if sheet == "README":
        continue
    for c in df.columns:
        if pd.api.types.is_string_dtype(df[c]) or df[c].dtype == object:
            s = df[c].dropna().astype(str)
            if (s != s.str.strip()).any() or s.str.contains(r"\s{2,}").any():
                txt_issues.append((sheet, c, "stray whitespace"))
            u = s.unique()
            if len(u) < 60 and len({x.lower().strip() for x in u}) < len(u):
                txt_issues.append((sheet, c, "case/spacing variants of same value"))
print("text issues:", txt_issues or "none")
if txt_issues:
    flag("all", "multiple", "warn", f"text inconsistencies: {txt_issues}")
# BMS command log: hand-mode entries never have a matching return-to-auto entry
cl2 = B["bms_command_log"]
print("Banquet AHU mode transitions seen:", cl2[cl2.point == "Banquet AHU mode"][["old_value", "new_value"]].drop_duplicates().values.tolist())
flag("bms", "bms_command_log", "info", "Banquet AHU mode log only records 1->2 (to hand mode); returns to auto are not logged - infer hand-mode end from sub-meter kW/schedule")

# %% [markdown]
# # 3 · PS-12_context_and_bills.xlsx
# Sheets: `weather_hourly`, `occupancy_daily`, `events`, `tariffs`, `monthly_bills`.
# Known issues: Goa July 2026 bill provisional (+14%); event end 23:59 = past midnight.

# %%
C = data_sheets("context")
profile("context", "weather_hourly", C["weather_hourly"], key_cols=["site", "timestamp"], ts_col="timestamp")
profile("context", "occupancy_daily", C["occupancy_daily"], key_cols=["site", "date"], ts_col="date")
profile("context", "events", C["events"])
profile("context", "tariffs", C["tariffs"])
profile("context", "monthly_bills", C["monthly_bills"], key_cols=["site", "billing_month"])

# %%
w = C["weather_hourly"].copy(); w["timestamp"] = pd.to_datetime(w["timestamp"])
for site, d in w.groupby("site"):
    print(site, end=" "); ts_regularity("context", f"weather_hourly[{site}]", d["timestamp"], "h")
display(w.groupby("site")[["temp_c", "rel_humidity_pct", "rain_mm"]].agg(["min", "mean", "max"]).round(1))
out_rng = int(((w.rel_humidity_pct < 0) | (w.rel_humidity_pct > 100) | (w.temp_c < -5) | (w.temp_c > 50) | (w.rain_mm < 0)).sum())
print("physically implausible weather rows:", out_rng)
if out_rng: flag("context", "weather_hourly", "error", f"{out_rng} implausible weather rows")

# %%
o = C["occupancy_daily"].copy(); o["date"] = pd.to_datetime(o["date"])
for site, d in o.groupby("site"):
    full = pd.date_range(d.date.min(), d.date.max(), freq="D")
    print(site, "days", len(d), "missing", len(full.difference(d.date)))
over = int((o.rooms_sold > o.rooms_available).sum())
pct_err = int(((o.rooms_sold / o.rooms_available - o.occupancy_pct).abs() > 0.005).sum())
print("rooms_sold > available:", over, "| occupancy_pct inconsistent:", pct_err)
display(o.groupby("site")[["rooms_available", "occupancy_pct", "guests_in_house", "covers_served_fnb"]].agg(["min", "mean", "max"]).round(2))
if over or pct_err: flag("context", "occupancy_daily", "error", f"rooms_sold>available {over}; pct inconsistent {pct_err}")

# %%
ev = C["events"].copy(); ev["date"] = pd.to_datetime(ev["date"])
print(ev.groupby(["site", "event_type"]).size().unstack(0).fillna(0).astype(int))
et = ev["end_time"].astype(str)
st = ev["start_time"].astype(str)
past_mid = et.str.startswith("23:59")
print("events with end 23:59 (ran past midnight):", int(past_mid.sum()))
if past_mid.any(): flag("context", "events", "info", f"{int(past_mid.sum())} events end '23:59' = actually past midnight; true end unknown")
neg = ((et < st) & ~past_mid).sum()
print("end before start (excluding 23:59):", int(neg), "| guests <= 0:", int((ev.guests <= 0).sum()), "| catering:", ev.catering.value_counts().to_dict())
print("events on a day with no occupancy row:", int((~ev.set_index(['site','date']).index.isin(o.set_index(['site','date']).index)).sum()))
print("multiple events same site/venue/day:", int(ev.duplicated(['site','date','venue']).sum()))

# %%
display(C["tariffs"])
# Demand / bills: recompute totals and check against reported
b = C["monthly_bills"].copy()
comp = ["energy_charge_inr", "tod_net_inr", "demand_charge_inr", "excess_demand_penalty_inr", "fsa_inr", "electricity_duty_inr", "municipal_tax_inr"]
b["recomputed_total"] = b[comp].sum(axis=1)
b["total_diff"] = (b["recomputed_total"] - b["total_grid_bill_inr"]).round(0)
b["total_energy_diff"] = (b["total_grid_bill_inr"] + b["dg_cost_inr"] - b["total_energy_cost_inr"]).round(0)
b["pf_check"] = (b.grid_kwh / b.grid_kvah - b.avg_power_factor).abs().round(4)
b["md_over_cd"] = b.recorded_md_kva - b.contract_demand_kva
print("max |recomputed - reported| total:", b.total_diff.abs().max(), "| max PF mismatch:", b.pf_check.max())
display(b[["site", "billing_month", "bill_status", "total_grid_bill_inr", "total_diff", "total_energy_diff", "pf_check", "md_over_cd", "excess_demand_penalty_inr"]])
bad_tot = b[(b.total_diff.abs() > 5) | (b.pf_check > 0.005)]
print("rows where components != total (>Rs5) or kWh/kVAh != reported PF:", bad_tot[["site", "billing_month", "bill_status", "total_diff", "pf_check"]].values.tolist())
if len(bad_tot): flag("context", "monthly_bills", "warn", f"internally inconsistent bill rows (components/total/PF): {bad_tot[['site','billing_month']].values.tolist()} - status {bad_tot.bill_status.unique().tolist()}")
print(b.bill_status.value_counts().to_dict())
prov = b[b.bill_status != "Actual"]
display(prov[["site", "billing_month", "bill_status"]])
if len(prov): flag("context", "monthly_bills", "warn", f"{len(prov)} non-Actual bill(s): {prov[['site','billing_month']].values.tolist()}")

# %%
# Reconcile bills with meter data: monthly grid kWh / kVAh / max kVA from meters vs bill
def monthly_from_meter(df, kva_col, site):
    d = df.copy(); d["month"] = d.timestamp.dt.to_period("M").astype(str)
    return d.groupby("month").agg(meter_kwh=("grid_kwh", "sum"), meter_kvah=("grid_kvah", "sum"), meter_md=(kva_col, "max")).assign(site=site)

mg = M["gurugram_15min"]; mj = M["jaipur_hourly"].drop_duplicates("timestamp"); mgo = M["goa_hourly"].drop_duplicates("timestamp")
meter_m = pd.concat([monthly_from_meter(mg, "kva_demand", "GGN"), monthly_from_meter(mj, "kva_max_in_hour", "JAI"),
                     monthly_from_meter(mgo, "kva_max_in_hour", "GOA")]).reset_index().rename(columns={"index": "month"})
rec = b.merge(meter_m, left_on=["site", "billing_month"], right_on=["site", "month"], how="left")
rec["kwh_diff_%"] = ((rec.grid_kwh - rec.meter_kwh) / rec.meter_kwh * 100).round(2)
rec["kvah_diff_%"] = ((rec.grid_kvah - rec.meter_kvah) / rec.meter_kvah * 100).round(2)
rec["md_diff"] = (rec.recorded_md_kva - rec.meter_md).round(1)
display(rec[["site", "billing_month", "bill_status", "kwh_diff_%", "kvah_diff_%", "md_diff"]])
worst = rec.loc[rec["kvah_diff_%"].abs().nlargest(3).index, ["site", "billing_month", "bill_status", "kvah_diff_%"]]
print("largest bill-vs-meter kVAh gaps:"); display(worst)
print("(Gurugram months containing meter faults may show a gap due to flat/zero data; Goa July 2026 should stand out ~ +14%)")

# %% [markdown]
# # 4 · PS-12_anomaly_test_set.xlsx
# Sheets: `anomaly_labels`, `bms_alarm_log`.
# **Leakage guard:** only schema/nulls/ID checks over all rows; any content shown is limited to anomalies starting before 1 Apr 2026.

# %%
A = data_sheets("anomaly")
lab = A["anomaly_labels"].copy()
for c in ["start", "end"]:
    lab[c] = pd.to_datetime(lab[c], errors="coerce")
print(f"anomaly_labels: {len(lab)} rows | null cells per column (structural check only):")
display(lab.isna().sum()[lambda s: s > 0].to_frame("nulls"))
print("ids unique:", lab.anomaly_id.is_unique, "| end<start:", int((lab.end < lab.start).sum()),
      "| sites:", sorted(lab.site.dropna().unique()))
print("rows by window -> tuning (<1 Apr 2026):", int((lab.start < TUNING_END).sum()), "| scoring (>=1 Apr 2026):", int((lab.start >= TUNING_END).sum()))
print("severity counts (all):", lab.severity.value_counts().to_dict())
tune = lab[lab.start < TUNING_END]
print("\nTuning-window anomaly types:"); display(tune.anomaly_type.value_counts().to_frame("n"))
display(tune.head(5)[["anomaly_id", "site", "anomaly_type", "start", "end", "equipment_or_meter", "severity"]])

# %%
al = A["bms_alarm_log"].copy()
profile("anomaly", "bms_alarm_log", al, key_cols=["alarm_id"])
for c in ["raised_at", "acknowledged_at", "action_at"]:
    al[c] = pd.to_datetime(al[c], errors="coerce")
print("ack before raised:", int((al.acknowledged_at < al.raised_at).sum()), "| action before raised:", int((al.action_at < al.raised_at).sum()))
print("action_taken:", al.action_taken.value_counts().to_dict())
print("action_taken='no action' but action_at filled:", int((al.action_taken.str.contains('no action', case=False, na=False) & al.action_at.notna()).sum()))
display(al.alarm.value_counts().to_frame("n"))
print("date range:", al.raised_at.min(), "->", al.raised_at.max(), "| sites:", al.site.value_counts().to_dict())

# %% [markdown]
# # 5 · Cross-file checks

# %%
# Common time grid & site coverage across files
spans = {
    "meter GGN": (M["gurugram_15min"].timestamp.min(), M["gurugram_15min"].timestamp.max()),
    "meter JAI": (M["jaipur_hourly"].timestamp.min(), M["jaipur_hourly"].timestamp.max()),
    "meter GOA": (M["goa_hourly"].timestamp.min(), M["goa_hourly"].timestamp.max()),
    "sub GGN": (gs.timestamp.min(), gs.timestamp.max()),
    "sub JAI/GOA": (jg.timestamp.min(), jg.timestamp.max()),
    "weather": (w.timestamp.min(), w.timestamp.max()),
    "occupancy": (o.date.min(), o.date.max()),
    "events": (ev.date.min(), ev.date.max()),
}
display(pd.DataFrame(spans, index=["start", "end"]).T)
print("sites in weather/occupancy/events/bills:", {n: sorted(x.site.unique()) for n, x in
      [("weather", w), ("occupancy", o), ("events", ev), ("bills", b)]})
# Event guests vs capacity sanity: events on days with zero rooms sold would be odd, check rooms_sold 0 days
print("days with 0 rooms sold:", int((o.rooms_sold == 0).sum()))

# %% [markdown]
# # 6 · Summary of findings

# %%
summ = pd.DataFrame(issues, columns=["workbook", "sheet", "severity", "finding"])
order = {"error": 0, "warn": 1, "info": 2}
summ = summ.sort_values(["severity", "workbook", "sheet"], key=lambda s: s.map(order) if s.name == "severity" else s)
display(summ.style.set_properties(subset=["finding"], **{"text-align": "left", "white-space": "pre-wrap"}))
print(summ.severity.value_counts().to_dict())
