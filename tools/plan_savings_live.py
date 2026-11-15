"""What would the daily operating plan have saved over the live year (Oct 2026 - Sep 2027, synthetic)?

Counterfactual, hour by hour, Gurugram only (the only hotel with per-chiller, banquet-AHU, laundry and water-heating sub-meters):
  * Each evening the engineer enters the next day's bookings (the live year's actual events) and the frozen models (models/, trained on
    Oct 2025 - Sep 2026 only) forecast hourly cooling load (TR) and kVA. The plan follows src/operating_plan.py's rules.
  * Actual = the live year's sub-meters. Planned = what the same hour would have drawn under the plan. Saving = actual - planned, never negative.
  * Chillers + CHW: only hours where the plan changes what was done count (two chillers where the forecast says one, setpoint below 7.0 C,
    reset to 8.0 C when outdoor < 24 C and one chiller). If the real load is above what the planned chiller can carry, that hour counts zero.
  * Banquet AHUs: on from 1 h before each booking to 1 h after; draw outside those windows is saved.
  * Laundry out of 18-22 (peak surcharge); water heating above its daily floor moved to 23-05 (surcharge + rebate).
  * Demand: monthly maximum demand rebuilt with the moved loads (and EV held back when forecast > 920 kVA); bill rule max(MD, 75 % CD) up to CD,
    penalty above CD.
Most of this is the same waste the alerts already count in src/savings.py; only the non-overlapping part is added there (see plan_increment).
Run: uv run python tools/plan_savings_live.py
"""
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import operating_plan as OP  # noqa: E402
import plan_models as PM  # noqa: E402

LIVE, M = ROOT / "data" / "live", ROOT / "models"
META = json.loads((M / "meta.json").read_text(encoding="utf-8"))
T, PF = META["tariff"], META["pf"]
RKWH = (T["energy"] + T["fsa"] + T["duty"]) / PF
EDGES, VALS = META["curve"]["edges"], META["curve"]["values"]
HALL = {"Banquet Hall A": "A", "Banquet Hall B": "B", "Banquet Hall A + B": "A+B"}
CD, FLOOR, DRATE, PEN = 1000.0, 750.0, 298.7, T["penalty"]
TAX = 1.02


def curve(tr):
    return np.select([tr <= e for e in EDGES[1:]], VALS, VALS[-1])


def forecast():
    ctx = pd.read_parquet(M / "context.parquet")
    ev = pd.read_parquet(LIVE / "events.parquet").query("site == 'GGN'")
    x = ctx.copy()
    for d, g in ev.groupby("date"):
        day = pd.Timestamp(d)
        bk = [dict(hall=HALL[r.venue], start=r.start_time, end=r.end_time, guests=r.guests) for r in g.itertuples()]
        w = (x.timestamp >= day - pd.Timedelta(hours=2)) & (x.timestamp < day + pd.Timedelta(hours=27))
        part = PM.add_bookings(x[w].assign(**{c: 0.0 for c in PM.EV_COLS}), day, bk)
        for c in PM.EV_COLS:
            x.loc[w, c] = x.loc[w, c].to_numpy() + part[c].to_numpy()
    p = PM.predict(joblib.load(M / "plan_models.joblib"), x)
    return pd.DataFrame(dict(timestamp=x.timestamp, f_tr=p["tr"], f_kva=p["kva"], temp=x.temp_c)), ev


def run():
    f, ev = forecast()
    d = pd.read_parquet(LIVE / "sub_ggn_hourly.parquet").merge(f, on="timestamp")
    hr = d.timestamp.dt.hour
    ch = d.chiller_ch1_kw + d.chiller_ch2_kw + d.chiller_ch3_kw
    stage = d.f_tr.map(OP.stage)
    cap = stage.map({"CH-3": 150.0, "CH-1": 300.0, "CH-1+CH-3": 450.0})
    single_ok = (stage != "CH-1+CH-3") & (d.chiller_load_tr <= cap)
    sp_plan = np.where((d.temp < OP.RESET_BELOW_C) & single_ok, OP.CHW_RESET, OP.CHW_STD)
    two = (d.chiller_ch1_kw > 5) & (d.chiller_ch3_kw > 5)
    sp_low = (OP.CHW_STD - d.chw_setpoint_c).clip(lower=0)
    at7 = ch / (1 + OP.SETPOINT_PCT_PER_C * sp_low)
    ideal = d.chiller_load_tr * curve(d.chiller_load_tr)
    sav_stage = pd.Series(np.where(single_ok & two, (at7 - ideal).clip(lower=0), 0.0))
    sav_sp_low = pd.Series(np.where(single_ok | two, ch - at7, 0.0))
    sav_reset = pd.Series(np.where(single_ok, np.where(two & single_ok, ideal, at7) * OP.SETPOINT_PCT_PER_C * (sp_plan - OP.CHW_STD), 0.0))

    win = pd.Series(False, index=d.index)
    for r in ev.itertuples():
        st, en = OP.parse_booking(dict(start=r.start_time, end=r.end_time))
        day = pd.Timestamp(r.date)
        win |= (d.timestamp >= day + pd.Timedelta(hours=st - 1)) & (d.timestamp < day + pd.Timedelta(hours=en + 1))
    sav_ahu = d.ahu_banquet_kw.where(~win & (d.ahu_banquet_kw > 10), 0.0)

    peak, off = hr.between(18, 21), (hr >= 23) | (hr < 5)
    boost = (d.water_heating_kw - d.groupby(d.timestamp.dt.normalize()).water_heating_kw.transform("min")).where(~off, 0.0)
    tod_laundry = d.laundry_kw.where(peak, 0.0) / PF * T["peak"]
    tod_water = boost / PF * (-T["offpeak"]) + boost.where(peak, 0.0) / PF * T["peak"]

    m15 = pd.read_parquet(LIVE / "meter_ggn_15min.parquet")
    kv = m15.groupby(m15.timestamp.dt.floor("h")).kva_demand.max().rename("kva").reset_index()
    d = d.merge(kv, on="timestamp", how="left")
    high = d.f_kva + OP.LAUNDRY_KW / PF > OP.DEMAND_WATCH_KVA
    removed = boost + d.laundry_kw.where(peak | high, 0.0) + d.ev_chargers_kw.where(d.f_kva > OP.DEMAND_WATCH_KVA, 0.0)
    d["kva_plan"] = d.kva - removed / PF
    mon = d.groupby(d.timestamp.dt.to_period("M")).agg(md=("kva", "max"), md_plan=("kva_plan", "max"))
    dbill = lambda md: min(max(md, FLOOR), CD) * DRATE + max(md - CD, 0) * PEN
    mon["saving"] = [(dbill(a) - dbill(b)) * TAX for a, b in zip(mon.md, mon.md_plan)]
    bills = pd.read_parquet(LIVE / "monthly_bills.parquet").query("site == 'GGN'")
    pen = bills.set_index(pd.PeriodIndex(bills.billing_month, freq="M")).excess_demand_penalty_inr
    mon["penalty_billed"] = pen.reindex(mon.index).fillna(0)

    levers = pd.DataFrame([
        ("Chiller sequencing to the forecast load", sav_stage.sum(), sav_stage.sum() * RKWH * TAX, "Energy", "staging alerts"),
        ("Chilled water back to 7.0 °C", sav_sp_low.sum(), sav_sp_low.sum() * RKWH * TAX, "Energy", "setpoint alerts"),
        ("Chilled water 8.0 °C on cool hours", sav_reset.sum(), sav_reset.sum() * RKWH * TAX, "Energy", "CHW reset measure"),
        ("Banquet AHUs on 1 h before / off 1 h after", sav_ahu.sum(), sav_ahu.sum() * RKWH * TAX, "Energy", "hand-mode AHU alerts"),
        ("Laundry out of the 18–22 peak", 0.0, tod_laundry.sum() * TAX, "ToD", "flexible-load shift"),
        ("Water heating moved to 23–05", 0.0, tod_water.sum() * TAX, "ToD", "flexible-load shift"),
        ("Lower monthly maximum demand", 0.0, mon.saving.sum(), "Demand", "breach measure (penalty months only)"),
    ], columns=["lever", "kwh", "inr", "category", "already_counted_as"])
    return levers, mon


def plan_increment(mon=None) -> float:
    """The part of the plan's saving not already counted in src/savings.py: demand saving in months with no excess-demand penalty billed."""
    if mon is None:
        _, mon = run()
    return float(mon.loc[mon.penalty_billed == 0, "saving"].sum())


if __name__ == "__main__":
    lv, mon = run()
    pd.set_option("display.width", 250)
    print(lv.round(0).to_string())
    print(mon.round(0).to_string())
    print(f"plan total ₹{lv.inr.sum():,.0f}; not already counted: ₹{plan_increment(mon):,.0f}")
    lv.to_csv(LIVE / "plan_savings_live.csv", index=False)
