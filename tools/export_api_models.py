"""Save what the plan API (api/main.py) needs at run time to models/, so the container reads no data/ folder and never refits:

  plan_models.joblib  frozen kW, cooling-TR and peak-kVA models, fitted on Oct 2025 - Sep 2026 only (src/plan_models.py)
  context.parquet     Gurugram hourly context for the live year (synthetic weather, rooms sold, covers; last year's events cleared)
                      with the kVA model's "yesterday" lags taken from 52 weeks earlier, plus one warm-up day either side
  refs.json           per date: last year's behaviour on matched days (the plan's ₹ baseline), as tools/export_plan_inputs.py
  meta.json           tariff, PF, one-chiller kW/TR curve, AHU run-on, peak-risk calibration, cooling-model accuracy, and the input
                      ranges seen in training (the API notes inputs outside them instead of failing)

Run after any change to the models or the live year:   uv run python tools/export_api_models.py
"""
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
import export_plan_inputs as EP  # noqa: E402
import forecast  # noqa: E402
import recalibration  # noqa: E402
from baseline import GBM_FEATURES, build_features  # noqa: E402
from plan_models import EV_COLS, Ens, predict  # noqa: E402

OUT = ROOT / "models"
KEEP = sorted(set(GBM_FEATURES + forecast.LAGS + EV_COLS + ["timestamp", "hour", "dow", "weekend", "month", "temp_c", "rel_humidity_pct", "rain_mm",
                                                              "rooms_sold", "occupancy_pct", "guests_in_house", "covers_served_fnb", "cdh", "temp_3h",
                                                              "cdh_24h", "hdh"]))


def main():
    OUT.mkdir(exist_ok=True)
    with EP.data(EP.CLEAN):
        orig = EP.tr_frame()
        kw = Ens().fit(orig[orig.valid], orig.total_kwh[orig.valid])
        tr = Ens().fit(orig[orig.tr_ok], orig.chiller_load_tr[orig.tr_ok])
        fo = forecast.build_frame()
        kva = forecast.Forecaster().fit(fo)
        F = recalibration.fit(recalibration._frame())
        acc = EP.tr_accuracy(orig)
        cal = EP.risk_calibration()
    models = dict(kw=kw, tr=tr, kva=kva)
    joblib.dump(models, OUT / "plan_models.joblib", compress=3)

    with EP.data(EP.LIVE):
        live = build_features(EP.SITE)
    lag = fo.set_index("timestamp")[forecast.LAGS]
    live[forecast.LAGS] = lag.reindex(live.timestamp - pd.Timedelta(days=364)).to_numpy()
    ctx = EP.with_events(live, [])                                  # last year's events cleared: the API adds the bookings it is given
    ctx[KEEP].to_parquet(OUT / "context.parquet", index=False)

    base = predict(models, ctx)
    days = sorted(ctx.timestamp.dt.normalize().unique())
    sub_o = pd.read_parquet(EP.CLEAN / "sub_ggn_hourly.parquet")
    refs = {}
    for d in days[1:-1]:                                            # first and last day are warm-up only
        m = (ctx.timestamp.dt.normalize() == d).to_numpy()
        refs[pd.Timestamp(d).strftime("%Y-%m-%d")] = EP.matched_refs(orig, sub_o, pd.Timestamp(d), float(np.mean(base["tr"][m])))
    (OUT / "refs.json").write_text(json.dumps(refs, separators=(",", ":")), encoding="utf-8")

    ev = pd.read_parquet(EP.CLEAN / "events.parquet").query("site == @EP.SITE")
    bills = pd.read_parquet(EP.CLEAN / "monthly_bills.parquet").query("site == @EP.SITE")
    t = pd.read_parquet(EP.LIVE / "tariffs.parquet").query("site == @EP.SITE").set_index("component").rate
    occ = pd.read_parquet(EP.CLEAN / "occupancy_daily.parquet").query("site == @EP.SITE")
    meta = dict(
        site=EP.SITE, trained_on="Oct 2025 – Sep 2026 (original year only; never refitted)",
        dates=[min(refs), max(refs)], context="live year Oct 2026 – Sep 2027 (synthetic, simulated meters); last year's events cleared",
        pf=round(float(bills.grid_kwh.sum() / bills.grid_kvah.sum()), 4),
        tariff=dict(energy=float(t["Energy charge"]), fsa=float(t["Fuel surcharge adjustment (FSA)"]), duty=float(t["Electricity duty"]),
                    peak=float(t["Peak ToD surcharge"]), offpeak=float(t["Off-peak ToD rebate"]), penalty=float(t["Excess demand penalty"])),
        curve=dict(edges=[20, 80, 130, 200, 280], values=[round(float(v), 4) for v in F["curve"].to_numpy()]),
        chw_pct_per_c=[round(float(v) / 1.5, 4) for v in F["chw_penalty"].reindex(F["curve"].index).fillna(F["chw_penalty"].mean()).to_numpy()],
        ahu_overrun_kwh=EP.ahu_overrun(sub_o, ev), risk=cal, cooling_model=acc,
        ranges=dict(rooms=[0, 220], guests_in_house=[int(occ.guests_in_house.min()), int(occ.guests_in_house.max())],
                    covers=[int(occ.covers_served_fnb.min()), int(occ.covers_served_fnb.max())],
                    event_guests={"corporate": int(ev[ev.event_type.str.startswith("Corporate")].guests.max()),
                                  "social": int(ev[ev.event_type.str.startswith("Wedding")].guests.max())},
                    event_start_hours=[int(ev.start_time.str[:2].astype(int).min()), int(ev.start_time.str[:2].astype(int).max())]))
    (OUT / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    size = sum(f.stat().st_size for f in OUT.iterdir()) / 2 ** 20
    print(f"models/: {', '.join(f.name for f in sorted(OUT.iterdir()))} ({size:.1f} MB); {len(refs)} dates; cooling model {acc['hourly_cv_rmse_pct']} % CV(RMSE)")


if __name__ == "__main__":
    main()
