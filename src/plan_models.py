"""Frozen plan models (Gurugram; Jaipur and Goa from tools/train_api_models.py) and the booking -> feature step, shared by tools/export_plan_inputs.py, tools/export_api_models.py and the
API (api/main.py). Lives in src/ so the models saved with joblib (models/plan_models.joblib) refer to an importable class.

All models are fitted on the original year only (Oct 2025 - Sep 2026) and never refitted at run time:
  kw  - src/baseline.py ensemble (ridge + LightGBM) on total_kwh;
  tr  - the same method on sub_ggn_hourly.chiller_load_tr (cooling load);
  kva - src/forecast.py day-ahead peak-kVA model.
"""
import numpy as np
import pandas as pd

from baseline import GBM_FEATURES, make_gbm, make_ridge
from forecast import thermal_features

EV_COLS = ["ev_guests", "ev_core", "ev_social", "ev_corp", "ev_evening"]
HALL_EVENT = {"A": ("Corporate conference", "Banquet Hall A"), "B": ("Corporate conference", "Banquet Hall B"),
              "A+B": ("Wedding / social event", "Banquet Hall A + B")}


class Ens:
    """Ridge + LightGBM averaged, as src/baseline.py."""
    def fit(self, d, y):
        self.r, self.g = make_ridge().fit(d, y), make_gbm().fit(d[GBM_FEATURES], y)
        return self

    def predict(self, d):
        return (self.r.predict(d) + self.g.predict(d[GBM_FEATURES])) / 2


def booking_hours(start: str, end: str) -> tuple[int, int]:
    """(start_h, end_h) relative to the booking's day; an end of 23:59 means past midnight, taken as 01:00 next day (the baseline's
    assumption); an end at or before the start runs into the next day. Same rule as operating_plan.parse_booking."""
    sh = int(start[:2])
    eh, em = int(end[:2]), int(end[3:5])
    e = 25 if end == "23:59" else eh + (1 if em > 0 else 0)
    if e <= sh:
        e += 24
    return sh, e


def add_bookings(frame: pd.DataFrame, day: pd.Timestamp, bookings: list, venues: dict | None = None) -> pd.DataFrame:
    """Event features for the bookings, built the way baseline._event_hours builds them from the calendar (AHUs from 1 h before the
    start to 1 h after the end; 'core' while guests are in the hall), but from integer hours so any start time works, including
    events that cross midnight. Bookings: dicts with hall (A / B / A+B; for Jaipur and Goa the venue name), start, end (HH:MM) and guests.
    venues: Jaipur / Goa venue -> {"event_type": ...} (from the events calendar, tools/train_api_models.py); None = Gurugram's halls."""
    x = frame.copy()
    x[EV_COLS] = 0.0
    ts = x.timestamp
    for b in bookings:
        typ = HALL_EVENT[b["hall"]][0] if venues is None else venues[b["hall"]]["event_type"]
        s, e = booking_hours(b["start"], b["end"])
        g = float(b["guests"])
        social = "edding" in typ or "MICE" in typ
        for h in range(s - 1, e + 1):
            m = (ts == day + pd.Timedelta(hours=h)).to_numpy()
            x.loc[m, "ev_guests"] += g
            x.loc[m, "ev_social" if social else "ev_corp"] += g
            if s <= h < e:
                x.loc[m, "ev_core"] += g
    x["ev_evening"] = x.ev_guests * x.hour.between(17, 23)
    return x


def predict(models: dict, frame: pd.DataFrame, site: str = "GGN") -> dict:
    """kW, cooling TR (never below 0) and peak kVA for every row; temperature-derived features are recomputed first (site's CDH base)."""
    d = thermal_features(frame, site)
    return dict(kw=models["kw"].predict(d), tr=np.clip(models["tr"].predict(d), 0, None), kva=models["kva"].predict(d))
