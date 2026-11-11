"""Day-ahead load and peak-kVA forecast for Gurugram, with a contract-demand risk warning and a flexible-load shift plan (T7).

Why a separate module: the UI, the assistant and the savings step all ask "what do we expect tomorrow?", and they must get the same answer.

What is known the day before (inputs): weather forecast, rooms sold (PMS forecast), the events calendar, day type, and yesterday's actual
kVA (lags). The weather in the historical data stands in for the forecast; notebooks/07_forecast.py measures how much a 1.5 degC forecast error costs.

Thresholds (7.0 / 920 / 1000 kVA) come from the engineering guide and the tariff - never from anomaly labels. Labels are not used here at all.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from baseline import CDH_BASE, GBM_FEATURES, build_features, make_gbm, make_ridge
from features import CLEAN, CONTRACT_KVA

SITE = "GGN"
CD = CONTRACT_KVA[SITE]                    # 1,000 kVA contract demand
EV_THROTTLE_KVA = 920                      # guide: EV chargers may be throttled above 920 kVA site demand
PENALTY_PER_KVA = 580.0                    # tariff: excess-demand penalty, Rs per kVA per month
LAGS = ["lag24", "lag168", "prev_day_max", "prev_day_mean"]
FLEX = {"laundry_kw": "Laundry", "ev_chargers_kw": "EV chargers", "water_heating_kw": "Water heating", "ahu_banquet_kw": "Banquet AHUs"}


def thermal_features(d: pd.DataFrame) -> pd.DataFrame:
    """Recompute the temperature-derived columns from temp_c (same formulas as baseline.build_features)."""
    d = d.copy()
    d["cdh"] = (d.temp_c - CDH_BASE[SITE]).clip(lower=0)
    d["temp_3h"] = d.temp_c.rolling(3, min_periods=1).mean()
    d["cdh_24h"] = d.cdh.rolling(24, min_periods=1).mean()
    d["hdh"] = (18.0 - d.temp_c).clip(lower=0)
    return d


def build_frame() -> pd.DataFrame:
    """Hourly Gurugram frame: baseline drivers + kVA target + day-ahead lags + flexible-load sub-meters."""
    d = build_features(SITE)
    d["date"] = d.timestamp.dt.normalize()
    d["y"] = d.kva_max_in_hour.where(d.valid)                   # hourly max 15-min kVA (what the utility bills as MD)
    d["lag24"] = d.y.shift(24)
    d["lag168"] = d.y.shift(168)
    d["prev_day_max"] = d.date.map(d.groupby("date").y.max().shift(1))
    d["prev_day_mean"] = d.date.map(d.groupby("date").y.mean().shift(1))
    s = pd.read_parquet(CLEAN / "sub_ggn_hourly.parquet")[["timestamp", *FLEX]]
    return d.merge(s, on="timestamp", how="left")


@dataclass
class Forecaster:
    ridge: object = None
    gbm: object = None

    def fit(self, d: pd.DataFrame) -> "Forecaster":
        tr = d[d.valid & d.y.notna()]
        self.ridge = make_ridge().fit(tr, tr.y)
        self.gbm = make_gbm().fit(tr[GBM_FEATURES + LAGS], tr.y)
        return self

    def predict(self, d: pd.DataFrame) -> np.ndarray:
        return (self.ridge.predict(d) + self.gbm.predict(d[GBM_FEATURES + LAGS])) / 2


def cv_hourly(d: pd.DataFrame, scheme: str = "lomo", start: int = 6, test_transform=None) -> pd.Series:
    """Out-of-sample hourly kVA predictions. 'lomo' = leave one month out; 'rolling' = train on months before, predict the next."""
    months = sorted(d.month.unique())
    p = pd.Series(np.nan, index=d.index)
    folds = [(m, [x for x in months if x != m]) for m in months] if scheme == "lomo" else [(months[i], months[:i]) for i in range(start, 12)]
    for m, train_months in folds:
        te = d.month == m
        test = d[te] if test_transform is None else test_transform(d)[te]       # e.g. add weather-forecast error to the test months only
        p[te] = Forecaster().fit(d[d.month.isin(train_months)]).predict(test)
    return p


# ---- daily summary, risk and plan -------------------------------------------------------------------------------
def daily_summary(d: pd.DataFrame, pred: pd.Series) -> pd.DataFrame:
    """Predicted vs actual daily peak and the hour it occurs; 'valid' days only have an actual."""
    t = d.assign(p=pred)
    g = t.groupby("date")
    out = pd.DataFrame({"pred_peak": g.p.max(), "pred_peak_hour": t.loc[g.p.idxmax(), ["date", "hour"]].set_index("date").hour,
                        "actual_peak": t[t.valid].groupby("date").y.max(), "tmax": g.temp_c.max(), "event_guests_max": g.ev_guests.max()})
    out["rel_err_pct"] = (out.pred_peak - out.actual_peak) / out.actual_peak * 100
    return out


def upper_factor(summary: pd.DataFrame, q: float = 0.90, min_pred: float = 750.0) -> float:
    """Multiplier on the predicted peak giving a q-upper bound, from out-of-sample ratios actual/pred on days with a high predicted peak."""
    s = summary[(summary.pred_peak >= min_pred) & summary.actual_peak.notna()]
    return float(np.quantile(s.actual_peak / s.pred_peak, q))


WATCH_FRAC = 0.90          # maximum-demand watch line: 90 % of contract demand (a convention, not fitted)
STACK_LOADS = {"laundry_kw": "LAUNDRY", "water_heating_kw": "HP-DHW", "ahu_banquet_kw": "AHU-BQ-A/B"}   # shiftable loads and their equipment_register ids


def hot_reference(d: pd.DataFrame, tmax: float = 38.0) -> pd.DataFrame:
    """Hours on hot weekdays - the context in which the afternoon peak happens. Used for 'typical' load at the peak hour."""
    day_tmax = d.groupby("date").temp_c.transform("max")
    return d[(day_tmax >= tmax) & (d.weekend == 0) & d.valid]


def stack_allowance(hot_ref: pd.DataFrame, peak_hour: int, pf: float) -> tuple[float, pd.DataFrame]:
    """kVA by which the peak could rise if the shiftable loads ran at their *connected* rating instead of their typical draw.

    headroom_kW = connected_kW (equipment register) - median kW at this hour on hot weekdays. Not fitted to any label.
    """
    reg = pd.read_parquet(CLEAN / "equipment_register.parquet").query("site == @SITE").set_index("equipment_id").connected_kw
    h = hot_ref[hot_ref.hour == peak_hour]
    rows = [dict(load=FLEX[c], connected_kw=float(reg[eq]), typical_kw=float(h[c].median()), headroom_kw=max(float(reg[eq]) - float(h[c].median()), 0.0))
            for c, eq in STACK_LOADS.items()]
    t = pd.DataFrame(rows)
    return float(t.headroom_kw.sum() / pf), t


def risk_level(pred_peak: float, factor: float, allowance_kva: float = 0.0) -> tuple[str, str]:
    """(level, reason). Statistical upper bound vs the guide's 1,000 / 920 kVA, then the stacking watch at 90 % of contract demand."""
    upper = pred_peak * factor
    if upper >= CD:
        return "BREACH RISK", f"90 % upper bound {upper:,.0f} kVA >= contract demand {CD:,}"
    if upper >= EV_THROTTLE_KVA:
        return "WARNING", f"90 % upper bound {upper:,.0f} kVA >= {EV_THROTTLE_KVA} kVA (EV-throttle level)"
    if pred_peak + allowance_kva >= WATCH_FRAC * CD:
        return "STACKING WATCH", f"forecast {pred_peak:,.0f} + shiftable-load headroom {allowance_kva:,.0f} = {pred_peak + allowance_kva:,.0f} kVA >= {WATCH_FRAC:.0%} of contract demand"
    return "OK", ""


def shift_plan(hot_ref: pd.DataFrame, peak_hour: int, base_kva: float, pf: float, mode: str = "bound", target: float = EV_THROTTLE_KVA) -> pd.DataFrame:
    """Which flexible loads to move off the peak hour, and the relief each gives (recommend only).

    mode 'bound' (start from the 90 % upper bound): relief = the *median* draw of the load at the peak hour on hot weekdays - what normally runs and could be moved.
    mode 'stack' (start from forecast + stacking allowance): relief = the connected rating of the three shiftable loads (equipment register), because the watch guards
    against them all running at full rating; keeping them out of the peak removes that.
    Banquet AHUs count at half in both modes (the guide requires pre-cooling 1 h before an event). EV chargers use the 95th-percentile draw (throttle is allowed above 920 kVA).
    Chillers, kitchen, lifts, guest-room thermostats and life-safety are never listed (brief section 9).
    """
    h = hot_ref[hot_ref.hour == peak_hour]
    reg = pd.read_parquet(CLEAN / "equipment_register.parquet").query("site == @SITE").set_index("equipment_id").connected_kw
    spec = [
        ("laundry_kw", "Hold laundry batches out of the afternoon peak (finish before 12:00 or start after 18:00)", "recommend only: flexible load", 1.0),
        ("ev_chargers_kw", f"Throttle EV charging while site demand is above {EV_THROTTLE_KVA} kVA; notify guests", "allowed by the guide above 920 kVA", 1.0),
        ("water_heating_kw", "Defer heat-pump water heating to off-peak; the daily ≥ 60 °C cycle must still complete", "recommend only: Legionella cycle", 1.0),
        ("ahu_banquet_kw", "Stagger banquet-hall AHU pre-cooling: start 1 h before the event, not earlier; stop 1 h after", "within the guide's AHU schedule rule", 0.5),
    ]
    rows = []
    for c, a, b, w in spec:
        if c == "ev_chargers_kw":
            kw = float(h[c].quantile(.95))
        elif mode == "stack":
            kw = float(reg[STACK_LOADS[c]])
        else:
            kw = float(h[c].median())
        rows.append(dict(load=FLEX[c], action=a, basis=b, kw_moved=kw * w, relief_kva=kw * w / pf))
    p = pd.DataFrame(rows).sort_values("relief_kva", ascending=False).reset_index(drop=True)
    p["cumulative_relief_kva"] = p.relief_kva.cumsum()
    p["demand_after_kva"] = base_kva - p.cumulative_relief_kva
    p["reaches_target"] = p.demand_after_kva <= target
    return p


def penalty_at_risk(upper_kva: float, md_so_far: float) -> float:
    """Extra excess-demand penalty if the month's recorded MD rises to upper_kva: (new MD - max(CD, MD so far)) x 580."""
    return max(0.0, upper_kva - max(CD, md_so_far)) * PENALTY_PER_KVA
