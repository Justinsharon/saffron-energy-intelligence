"""Contract-demand risk for tomorrow (T7), built on top of the day-ahead forecast (src/forecast.py, unchanged).

Why this layer (added 10 Nov, after notebook 07; no anomaly labels used):
1. Bias. The forecast's daily peak is the max of 24 smooth hourly predictions; the real peak is the max of 24 noisy hours, so it runs
   ~3-4 % higher on every kind of day. We correct with the median actual/predicted ratio of *earlier* days only (no look-ahead).
2. Probability. Instead of a single bound we report P(peak > 1,000 kVA) from the spread of earlier days' actual/predicted ratios.
3. Stacking. The year's three >1,000 kVA days (12 May, 18 Jun, 25 Jun - from the meter, not labels) were laundry, water heating and
   banquet AHUs running far above their usual draw at the 13-17 h peak. Weather and bookings cannot see that, so we add the stacking
   seen on earlier breach days to tomorrow's forecast as a "what if it happens again" scenario. Before the first breach in the data we fall
   back to the equipment register's connected ratings (forecast.stack_allowance).
"""
import numpy as np
import pandas as pd

import forecast as F

CD, WARN = F.CD, F.EV_THROTTLE_KVA
MIN_PRED = 700.0          # ratios from days with a high predicted peak: the regime that matters for the contract demand


def _hist(S: pd.DataFrame, before=None) -> pd.DataFrame:
    h = S[(S.pred_peak >= MIN_PRED) & S.actual_peak.notna()]
    if before is not None:
        h = h[h.index < pd.Timestamp(before)]
    return h


def bias_factor(S: pd.DataFrame, before=None) -> float:
    h = _hist(S, before)
    return float((h.actual_peak / h.pred_peak).median()) if len(h) >= 10 else 1.0


def exceed_prob(S: pd.DataFrame, corrected_peak: float, before=None, level: float = CD) -> float:
    """Share of earlier high-forecast days whose actual/corrected ratio would have taken tomorrow's corrected peak above `level`."""
    h = _hist(S, before)
    if len(h) < 10:
        return float("nan")
    r = h.actual_peak / (h.pred_peak * bias_factor(S, before))
    return float((r >= level / corrected_peak).mean())


def breach_days(d: pd.DataFrame, before=None) -> pd.DataFrame:
    """Days whose metered peak exceeded contract demand, with the peak hour."""
    v = d[d.valid]
    pk = v.loc[v.groupby("date").kva_max_in_hour.idxmax()][["date", "hour", "kva_max_in_hour"]]
    pk = pk[pk.kva_max_in_hour > CD]
    if before is not None:
        pk = pk[pk.date < pd.Timestamp(before)]
    return pk


def stacking_increment(d: pd.DataFrame, hot_ref: pd.DataFrame, pf: float, before=None) -> tuple[float, pd.DataFrame, str]:
    """(kVA, per-load table, basis) the shiftable loads added above their usual draw at the peak hour on earlier breach days."""
    bd = breach_days(d, before)
    if bd.empty:
        allow, tab = F.stack_allowance(hot_ref, 14, pf)
        return allow, tab.rename(columns={"headroom_kw": "extra_kw"}), "connected rating (no earlier breach day)"
    rows = []
    for r in bd.itertuples():
        row = d[(d.date == r.date) & (d.hour == r.hour)].iloc[0]
        typ = hot_ref[hot_ref.hour == r.hour]
        for c in F.STACK_LOADS:
            rows.append(dict(date=r.date, load=F.FLEX[c], actual_kw=float(row[c]), typical_kw=float(typ[c].median())))
    t = pd.DataFrame(rows)
    t["extra_kw"] = (t.actual_kw - t.typical_kw).clip(lower=0)
    per_load = t.groupby("load")[["actual_kw", "typical_kw", "extra_kw"]].mean().reset_index()
    days = ", ".join(f"{x:%d %b}" for x in bd.date)
    return float(per_load.extra_kw.sum() / pf), per_load, f"average of earlier breach days ({days})"


def assess(pred_peak: float, peak_hour: int, S: pd.DataFrame, d: pd.DataFrame, hot_ref: pd.DataFrame, pf: float, before=None) -> dict:
    b = bias_factor(S, before)
    corr = pred_peak * b
    h = _hist(S, before)
    fac = float(np.quantile(h.actual_peak / (h.pred_peak * b), 0.90)) if len(h) >= 10 else 1.125   # 1.125 ≈ full-year 1.164 / 1.035 bias
    upper = corr * fac
    p = exceed_prob(S, corr, before)
    inc, tab, basis = stacking_increment(d, hot_ref, pf, before)
    stack = corr + inc
    if upper >= CD:
        level, why = "BREACH RISK", f"90 % upper bound {upper:,.0f} kVA ≥ contract demand {CD:,} kVA"
    elif stack >= CD:
        level, why = "BREACH RISK", (f"if laundry, water heating and banquet AHUs stack as on {basis.split('(')[-1].rstrip(')')}, "
                                     f"demand reaches {stack:,.0f} kVA ≥ {CD:,} kVA")
    elif upper >= WARN:
        level, why = "WARNING", f"90 % upper bound {upper:,.0f} kVA ≥ {WARN} kVA (EV-throttle level)"
    elif stack >= F.WATCH_FRAC * CD:
        level, why = "STACKING WATCH", f"stacking scenario {stack:,.0f} kVA ≥ {F.WATCH_FRAC:.0%} of contract demand"
    else:
        level, why = "OK", ""
    return dict(raw_peak=pred_peak, bias=b, peak=corr, hour=peak_hour, upper=upper, p_exceed=p, stack_increment=inc, stack_peak=stack,
                stack_table=tab, stack_basis=basis, level=level, why=why)
