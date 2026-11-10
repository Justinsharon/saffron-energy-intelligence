"""Thin wrapper over src/forecast.py for the UI: one model fitted on the whole year, a day view and the T7 what-if.

The stored daily forecasts (forecast_ggn_daily.parquet) are out-of-sample and are what accuracy is quoted on; this full-year model is
only used for "what if tomorrow is 40 °C with a big conference" scenarios, where no actual exists.
"""
import pandas as pd

import forecast as F
from features import CLEAN

_STATE = {}


def state():
    if not _STATE:
        d = F.build_frame()
        S = pd.read_parquet(CLEAN / "forecast_ggn_daily.parquet").set_index("date")
        b = pd.read_parquet(CLEAN / "monthly_bills.parquet").query("site == 'GGN'")
        _STATE.update(d=d, model=F.Forecaster().fit(d), S=S, fac=F.upper_factor(S), pf=float(b.grid_kwh.sum() / b.grid_kvah.sum()),
                      hot=F.hot_reference(d))
    return _STATE


def assess(pred_hourly: pd.Series, hours: pd.Series) -> dict:
    s = state()
    pk = float(pred_hourly.max())
    ph = int(hours.iloc[int(pred_hourly.to_numpy().argmax())])
    allow, allow_tab = F.stack_allowance(s["hot"], ph, s["pf"])
    level, why = F.risk_level(pk, s["fac"], allow)
    plan = None
    if level != "OK":
        base = pk * s["fac"] if level in ("BREACH RISK", "WARNING") else pk + allow
        plan = F.shift_plan(s["hot"], ph, base, s["pf"], mode="bound" if level in ("BREACH RISK", "WARNING") else "stack")
    return dict(peak=pk, hour=ph, upper=pk * s["fac"], allowance=allow, level=level, why=why, plan=plan, allow_tab=allow_tab)


def day_view(date) -> tuple[pd.DataFrame, dict]:
    s = state()
    h = pd.read_parquet(CLEAN / "forecast_ggn_hourly.parquet")
    w = h[h.timestamp.dt.normalize() == pd.Timestamp(date)].copy()
    w["hour"] = w.timestamp.dt.hour
    return w, assess(w.pred_kva.reset_index(drop=True), w.hour.reset_index(drop=True))


def scenario(date, tmax: float, guests: int, start_h: int = 9, end_h: int = 18) -> tuple[pd.DataFrame, dict]:
    """Template day `date` with its temperature shifted so the max is `tmax`, plus a conference of `guests` (T7)."""
    s = state()
    t = s["d"].copy()
    m = t.date == pd.Timestamp(date)
    t.loc[m, "temp_c"] = t.loc[m, "temp_c"] + (tmax - t.loc[m, "temp_c"].max())
    t = F.thermal_features(t)
    if guests:
        t.loc[m & t.hour.between(start_h - 1, end_h), ["ev_guests", "ev_corp"]] = guests
        t.loc[m & t.hour.between(start_h, end_h - 1), "ev_core"] = guests
    w = t[m].copy()
    w["pred_kva"] = s["model"].predict(w)
    return w[["timestamp", "hour", "temp_c", "pred_kva"]], assess(w.pred_kva.reset_index(drop=True), w.hour.reset_index(drop=True))
