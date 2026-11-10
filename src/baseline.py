"""Hourly baseline ("what should this hotel use right now?") shared by the notebook and, later, the detector,
forecast and IPMVP savings.

Why one module: the detector, the savings view and the peak forecast must all use the *same* feature definitions
and the same model, otherwise "expected" means different things in different places.

Design choices (see notebooks/03_baseline.py for the evidence):
- Target is `total_kwh` (grid + DG) per hour = mean kW. Hours with DG, meter faults or imputed values are not used to
  fit or score (`exclude_from_model | is_dg | has_meter_fault`).
- Drivers are only things known independently of the meter: weather, rooms sold / covers, the events calendar,
  hour and day type. No month / day-of-year feature: with a single year it would just memorise the season.
- Events: 23:59 end times mean "ran past midnight, true end unknown" (OPEN_QUESTIONS #3). We assume they end at
  `late_end_hour` the next day and expose that as a parameter so sensitivity can be checked.
- Anomaly labels are not used anywhere in this module.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from features import CLEAN, ROOMS, unified_hourly

# CDH base temperatures from the EDA (best daily-kWh fit per hotel).
CDH_BASE = {"GGN": 26.0, "JAI": 16.0, "GOA": 14.0}


def _event_hours(ev: pd.DataFrame, late_end_hour: int, buffer_h: int = 1) -> pd.DataFrame:
    """Expand events to the hourly grid. Banquet AHUs run from 1 h before start to 1 h after end (engineering guide)."""
    rows = []
    for r in ev.itertuples():
        start = pd.Timestamp(r.date) + pd.Timedelta(hours=int(r.start_time[:2]), minutes=int(r.start_time[3:]))
        if r.ends_after_midnight:
            end = pd.Timestamp(r.date) + pd.Timedelta(days=1, hours=late_end_hour)
        else:
            end = pd.Timestamp(r.date) + pd.Timedelta(hours=int(r.end_time[:2]), minutes=int(r.end_time[3:]))
        wed = "edding" in r.event_type or "MICE" in r.event_type
        for h in pd.date_range(start.floor("h") - pd.Timedelta(hours=buffer_h), end.ceil("h") + pd.Timedelta(hours=buffer_h - 1), freq="h"):
            core = start <= h + pd.Timedelta(minutes=30) < end
            rows.append((h, r.guests, r.guests if core else 0, r.guests if wed else 0, r.guests if not wed else 0))
    out = pd.DataFrame(rows, columns=["timestamp", "ev_guests", "ev_core", "ev_social", "ev_corp"])
    return out.groupby("timestamp").sum().reset_index()


def build_features(site: str, late_end_hour: int = 1) -> pd.DataFrame:
    """One row per hour for `site`, with target, validity mask and drivers."""
    m = unified_hourly().query("site == @site").drop(columns="site").reset_index(drop=True)
    w = pd.read_parquet(CLEAN / "weather_hourly.parquet").query("site == @site").drop(columns="site")
    occ = pd.read_parquet(CLEAN / "occupancy_daily.parquet").query("site == @site").drop(columns="site")
    ev = pd.read_parquet(CLEAN / "events.parquet").query("site == @site")

    d = m.merge(w, on="timestamp", how="left")
    d["date"] = d.timestamp.dt.normalize()
    d = d.merge(occ[["date", "rooms_sold", "occupancy_pct", "guests_in_house", "covers_served_fnb"]], on="date", how="left")
    d = d.merge(_event_hours(ev, late_end_hour), on="timestamp", how="left")
    for c in ["ev_guests", "ev_core", "ev_social", "ev_corp"]:
        d[c] = d[c].fillna(0.0)

    d["hour"] = d.timestamp.dt.hour
    d["dow"] = d.timestamp.dt.day_of_week
    d["weekend"] = (d.dow >= 5).astype(int)
    d["month"] = d.timestamp.dt.to_period("M").astype(str)

    base = CDH_BASE[site]
    d["cdh"] = (d.temp_c - base).clip(lower=0)
    d["temp_3h"] = d.temp_c.rolling(3, min_periods=1).mean()       # building thermal lag
    d["cdh_24h"] = d.cdh.rolling(24, min_periods=1).mean()
    d["hdh"] = (18.0 - d.temp_c).clip(lower=0)                     # winter re-heat / pool heating
    d["ev_evening"] = d.ev_guests * d.hour.between(17, 23)
    d["valid"] = ~(d.exclude_from_model | d.is_dg | d.has_meter_fault) & d.total_kwh.notna()
    return d


NUMERIC = ["temp_c", "temp_3h", "cdh", "cdh_24h", "hdh", "rel_humidity_pct", "rain_mm", "rooms_sold", "guests_in_house",
           "covers_served_fnb", "ev_guests", "ev_core", "ev_social", "ev_corp"]
GBM_FEATURES = NUMERIC + ["hour", "dow", "weekend"]


def make_ridge(alpha: float = 3.0):
    """Regularised linear model: hour x day-type profile, and weather / events allowed to act differently by hour block."""
    from sklearn.compose import ColumnTransformer
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import FunctionTransformer, StandardScaler

    def expand(df: pd.DataFrame) -> np.ndarray:
        X = {}
        prof = df.hour.astype(str) + "_" + df.weekend.astype(str)
        for k in sorted(set(f"{h}_{w}" for h in range(24) for w in (0, 1))):
            X[f"prof_{k}"] = (prof == k).astype(float)
        block = pd.cut(df.hour, [-1, 5, 11, 17, 23], labels=False)
        for v in ["cdh", "cdh_24h", "hdh", "rel_humidity_pct", "ev_guests", "ev_social", "ev_corp", "rooms_sold"]:
            for b in range(4):
                X[f"{v}_b{b}"] = df[v] * (block == b)
        for v in ["temp_c", "temp_3h", "rain_mm", "guests_in_house", "covers_served_fnb", "ev_core"]:
            X[v] = df[v]
        X["cdh_x_hum"] = df.cdh * df.rel_humidity_pct / 100
        return pd.DataFrame(X).to_numpy(float)

    return Pipeline([("x", FunctionTransformer(expand)), ("s", StandardScaler()), ("m", Ridge(alpha=alpha))])


def make_gbm(**kw):
    """Shallow boosted trees; huber loss so a few waste hours in the training year do not drag the baseline up."""
    import lightgbm as lgb

    p = dict(n_estimators=600, learning_rate=0.05, num_leaves=8, min_child_samples=40, subsample=0.8, subsample_freq=1,
             colsample_bytree=0.8, reg_lambda=5.0, objective="huber", alpha=40.0, random_state=0, verbose=-1)
    p.update(kw)
    return lgb.LGBMRegressor(**p)


# ---- ASHRAE Guideline 14 metrics -------------------------------------------------------------------------------
def cv_rmse(y, p, n_params: int = 1) -> float:
    y, p = np.asarray(y, float), np.asarray(p, float)
    return float(np.sqrt(((y - p) ** 2).sum() / max(len(y) - n_params, 1)) / y.mean() * 100)


def nmbe(y, p, n_params: int = 1) -> float:
    y, p = np.asarray(y, float), np.asarray(p, float)
    return float((y - p).sum() / (max(len(y) - n_params, 1) * y.mean()) * 100)


def fit_predict(kind: str, train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """Fit on `train` valid hours and predict every row of `test`."""
    tr = train[train.valid]
    if kind == "ridge":
        mdl = make_ridge()
        mdl.fit(tr, tr.total_kwh)
        return mdl.predict(test)
    mdl = make_gbm()
    mdl.fit(tr[GBM_FEATURES], tr.total_kwh)
    return mdl.predict(test[GBM_FEATURES])
