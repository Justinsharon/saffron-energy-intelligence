"""Two Gurugram rules added after the detector freeze (POST-HOC, additive; src/detector.py is untouched).

Why they exist: notebook 06 showed held-out label types with no rule (contract-demand breach, EV charger stuck on). Both need no label to define:
- DEMAND_NEAR_CONTRACT: 15-min kVA demand above the guide's thresholds (920 kVA EV-throttle level, 1,000 kVA contract demand). Thresholds are the guide's.
- EV_CHARGER_NIGHT_ON: EV sub-meter above 1 kW between 01:00 and 05:00. The tuning window (before 1 Apr 2026) shows exactly 0 kW in those hours on every night,
  so any draw is outside the learned profile; no label was used (there is no EV label before April).
Because the held-out gaps were seen before these were written, results on them are NOT clean held-out; they are reported as post-hoc.
Alert rows use the same columns as detector alerts, so the UI can merge them.
"""
import numpy as np
import pandas as pd

from features import CLEAN, CONTRACT_KVA

EV_THROTTLE_KVA, CD = 920, CONTRACT_KVA["GGN"]
EV_NIGHT_HOURS, EV_NIGHT_KW = (1, 5), 1.0
PENALTY_PER_KVA = 580.0


def _runs(flag: np.ndarray, gap: int):
    idx = np.flatnonzero(flag)
    if len(idx) == 0:
        return
    start = 0
    for i in range(1, len(idx) + 1):
        if i == len(idx) or idx[i] - idx[i - 1] - 1 > gap:
            yield idx[start:i]
            start = i


def demand_alerts() -> pd.DataFrame:
    m = pd.read_parquet(CLEAN / "meter_ggn_15min.parquet")
    m = m[~m.exclude_from_model & ~m.is_dg].reset_index(drop=True)
    rows = []
    for run in _runs((m.kva_demand > EV_THROTTLE_KVA).to_numpy(), gap=4):         # merge within an hour
        seg = m.iloc[run]
        peak = float(seg.kva_demand.max())
        level = "BREACH" if peak > CD else "NEAR-LIMIT"
        t0, t1 = seg.timestamp.iloc[0], seg.timestamp.iloc[-1] + pd.Timedelta(minutes=15)
        rows.append(dict(site="GGN", rule="DEMAND_NEAR_CONTRACT", start=t0, end=t1, alert_time=t0 + pd.Timedelta(minutes=15), flagged_h=len(run) / 4,
                         cost_inr=max(0.0, peak - CD) * PENALTY_PER_KVA,
                         evidence=f"Site demand {peak:,.0f} kVA at {seg.timestamp.iloc[seg.kva_demand.argmax()]:%H:%M} ({level}); EV-throttle level {EV_THROTTLE_KVA}, contract demand {CD:,} kVA. "
                                  f"Penalty if this stands as the month's MD: Rs {max(0.0, peak - CD) * PENALTY_PER_KVA:,.0f} (excess-demand charge, tariff sheet)"))
    return pd.DataFrame(rows)


def ev_alerts() -> pd.DataFrame:
    g = pd.read_parquet(CLEAN / "sub_ggn_hourly.parquet")[["timestamp", "ev_chargers_kw"]].reset_index(drop=True)
    hr = g.timestamp.dt.hour
    flag = ((hr >= EV_NIGHT_HOURS[0]) & (hr <= EV_NIGHT_HOURS[1]) & (g.ev_chargers_kw > EV_NIGHT_KW)).to_numpy()
    rows = []
    for run in _runs(flag, gap=30):                                              # nights of one episode merge (daytime is normal use)
        seg = g.iloc[run]
        rows.append(dict(site="GGN", rule="EV_CHARGER_NIGHT_ON", start=seg.timestamp.iloc[0], end=seg.timestamp.iloc[-1] + pd.Timedelta(hours=1),
                         alert_time=seg.timestamp.iloc[0] + pd.Timedelta(hours=1), flagged_h=len(run), cost_inr=np.nan,
                         evidence=f"EV chargers draw {seg.ev_chargers_kw.mean():.1f} kW between 01:00 and 05:00 on {seg.timestamp.dt.date.nunique()} night(s); normal for those hours is 0 kW. "
                                  f"Likely a stuck charger; check at the charger panel. Low value, but it also adds to afternoon demand"))
    return pd.DataFrame(rows)


def all_additions() -> pd.DataFrame:
    return pd.concat([demand_alerts(), ev_alerts()], ignore_index=True).sort_values("alert_time").reset_index(drop=True)
