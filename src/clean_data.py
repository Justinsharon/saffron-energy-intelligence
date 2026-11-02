"""Clean the PS-12 workbooks and write analysis-ready tables to data/clean/.

Rules (see notebooks/01_data_cleanliness.ipynb for the evidence):
  * Gurugram meter faults: grid_kwh / grid_kvah / kva_demand freeze or read 0 on GRID while kw_avg, power_factor
    and the sub-meters stay live. Flag the rows, keep the raw values in *_raw, rebuild the billed columns from kw_avg.
    Rows are excluded from model fitting and detector scoring (exclude_from_model).
  * Jaipur 10-hour gap: estimate from the sub-meter total scaled by the site's median main/sub ratio. Flagged imputed.
  * Goa: drop the 24 exact duplicate rows.
  * Gurugram lifts_kw / pool_kw swapped for March 2026: swap back, flagged.
  * Bills are never edited. Provisional Goa bill is flagged; events ending 23:59 get ends_after_midnight.
  * anomaly_labels is passed through untouched (leakage rules are applied at scoring time).
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "clean"
MIN_FAULT_INTERVALS = 4          # >= 1 h of 15-min readings identical in all billed columns
SWAP_MONTH = ("2026-03-01", "2026-04-01")


def read(file, sheet):
    return pd.read_excel(ROOT / file, sheet_name=sheet)


def runs(mask):
    m = np.asarray(mask, dtype=bool)
    d = np.diff(np.r_[0, m.astype(int), 0])
    starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
    return list(zip(starts, ends - starts))


def clean_gurugram():
    g = read("PS-12_meter_data.xlsx", "gurugram_15min").sort_values("timestamp").reset_index(drop=True)
    billed = ["grid_kwh", "grid_kvah", "kva_demand"]
    repeat = (g[billed].diff() == 0).all(axis=1)
    run_len = g.groupby((~repeat).cumsum())["grid_kwh"].transform("size")
    fault = (run_len >= MIN_FAULT_INTERVALS) & g["supply_source"].eq("GRID")

    for c in billed:
        g[f"{c}_raw"] = g[c]
    g["is_meter_fault"] = fault
    pf = g["power_factor"]
    g.loc[fault, "grid_kwh"] = g.loc[fault, "kw_avg"] * 0.25
    g.loc[fault, "grid_kvah"] = g.loc[fault, "grid_kwh"] / pf[fault]
    g.loc[fault, "kva_demand"] = g.loc[fault, "kw_avg"] / pf[fault]
    g["is_dg"] = g["supply_source"].eq("DG")
    g["total_kwh"] = g["grid_kwh"] + g["dg_kwh"]
    g["exclude_from_model"] = g["is_meter_fault"]
    return g


def clean_jaipur(sub):
    j = read("PS-12_meter_data.xlsx", "jaipur_hourly").sort_values("timestamp").reset_index(drop=True)
    gap = (j["grid_kwh"].isna() | j["kw_avg"].isna()).to_numpy()
    s = sub[sub.site == "JAI"].set_index("timestamp")
    sub_total = s[[c for c in s.columns if c.endswith("_kw")]].sum(axis=1)
    j = j.set_index("timestamp")
    ratio = (j["kw_avg"] / sub_total).where(~gap & (j["dg_kwh"].to_numpy() == 0)).median()
    pf_med = j["power_factor"].median()
    est = sub_total.reindex(j.index) * ratio
    for c in ["grid_kwh", "grid_kvah", "kw_avg", "kva_max_in_hour", "power_factor"]:
        j[f"{c}_raw"] = j[c]
    j["is_imputed"] = gap
    gi = j["is_imputed"]
    j.loc[gi, "kw_avg"] = est[gi]
    j.loc[gi, "grid_kwh"] = est[gi]
    j.loc[gi, "power_factor"] = pf_med
    j.loc[gi, "grid_kvah"] = est[gi] / pf_med
    # peak kVA within the hour is not recoverable; approximate from neighbouring peak/avg ratio
    pk = (j["kva_max_in_hour"] / (j["kw_avg"] / j["power_factor"])).where(~gi).median()
    j.loc[gi, "kva_max_in_hour"] = (est[gi] / pf_med) * pk
    j["is_dg"] = j["dg_kwh"] > 0
    j["total_kwh"] = j["grid_kwh"] + j["dg_kwh"]
    j["exclude_from_model"] = False          # imputed hours kept; filter on is_imputed if you prefer strictness
    print(f"  Jaipur: imputed {int(gi.sum())} h using main/sub ratio {ratio:.3f}")
    return j.reset_index()


def clean_goa():
    go = read("PS-12_meter_data.xlsx", "goa_hourly")
    n0 = len(go)
    go = go.drop_duplicates().sort_values("timestamp").reset_index(drop=True)
    assert not go.timestamp.duplicated().any(), "duplicate timestamps remain with differing values"
    go["is_dg"] = go["dg_kwh"] > 0
    go["total_kwh"] = go["grid_kwh"] + go["dg_kwh"]
    go["exclude_from_model"] = False
    print(f"  Goa: dropped {n0 - len(go)} duplicate rows")
    return go


def clean_submeters():
    gs = read("PS-12_bms_submeters.xlsx", "gurugram_submeters_hourly").sort_values("timestamp").reset_index(drop=True)
    m = (gs.timestamp >= SWAP_MONTH[0]) & (gs.timestamp < SWAP_MONTH[1])
    gs["lifts_pool_swapped_fixed"] = m
    gs.loc[m, ["lifts_kw", "pool_kw"]] = gs.loc[m, ["pool_kw", "lifts_kw"]].values
    jg = read("PS-12_bms_submeters.xlsx", "jaipur_goa_submeters_hourly").sort_values(["site", "timestamp"]).reset_index(drop=True)
    gs["kw_per_tr"] = np.where(gs.chiller_load_tr > 0, gs[["chiller_ch1_kw", "chiller_ch2_kw", "chiller_ch3_kw"]].sum(axis=1) / gs.chiller_load_tr, np.nan)
    print(f"  Gurugram sub-meters: swapped lifts/pool back for {int(m.sum())} h")
    return gs, jg


def clean_context():
    w = read("PS-12_context_and_bills.xlsx", "weather_hourly")
    o = read("PS-12_context_and_bills.xlsx", "occupancy_daily")
    ev = read("PS-12_context_and_bills.xlsx", "events")
    ev["ends_after_midnight"] = ev["end_time"].astype(str).eq("23:59")
    t = read("PS-12_context_and_bills.xlsx", "tariffs")
    b = read("PS-12_context_and_bills.xlsx", "monthly_bills")
    b["is_provisional"] = b["bill_status"].ne("Actual")
    return w, o, ev, t, b


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("Cleaning ...")
    gs, jg = clean_submeters()
    ggn = clean_gurugram()
    print(f"  Gurugram: {int(ggn.is_meter_fault.sum())} fault intervals flagged and rebuilt from kw_avg")
    jai = clean_jaipur(jg)
    goa = clean_goa()
    w, o, ev, t, b = clean_context()
    lab = read("PS-12_anomaly_test_set.xlsx", "anomaly_labels")
    alarms = read("PS-12_anomaly_test_set.xlsx", "bms_alarm_log")
    cmd = read("PS-12_bms_submeters.xlsx", "bms_command_log")
    reg = read("PS-12_bms_submeters.xlsx", "equipment_register")
    tables = {"meter_ggn_15min": ggn, "meter_jai_hourly": jai, "meter_goa_hourly": goa,
              "sub_ggn_hourly": gs, "sub_jai_goa_hourly": jg, "bms_command_log": cmd, "equipment_register": reg,
              "weather_hourly": w, "occupancy_daily": o, "events": ev, "tariffs": t, "monthly_bills": b,
              "anomaly_labels": lab, "bms_alarm_log": alarms}
    for name, df in tables.items():
        df.to_parquet(OUT / f"{name}.parquet", index=False)
    print(f"Wrote {len(tables)} tables to {OUT}")


if __name__ == "__main__":
    main()
