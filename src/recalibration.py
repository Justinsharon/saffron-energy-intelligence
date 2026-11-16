"""Post-hoc fixes for the two chiller costs that came out low against the answer key (written 10 Nov, after the freeze; src/detector.py untouched).

1. STAGING_KWTR (new Gurugram rule). In ~900 hours the plant draws 0.9-1.1 kW/TR at 130-280 TR while the BMS shows one chiller running -
   about 1.6x what one chiller normally needs at that load (0.6-0.7). We first read this as a second chiller at part load that the BMS
   run-status point missed. The per-chiller sub-meters (sub_ggn_hourly) disprove that: in every flagged hour chiller_ch3_kw = 0 and CH-1 alone
   carries the load. Normal CH-1-alone hours at the same outdoor temperature run at ~1.0x, so weather explains little. The rule now flags
   "CH-1 inefficient, cause unknown" (likely condenser side: cooling tower, fouling, water flow). Its ₹ is shown on the alert but NOT counted
   as waste or savings until the cause is confirmed (src/savings.py NOT_SIZED).
   Defined on the tuning window only: the "normal one-chiller" kW/TR curve and the flag threshold are fitted on hours before 1 Apr 2026
   with the tuning labels removed. The same pattern exists in March (13-31 Mar), inside the tuning window, so the rule is not fitted to
   post-April labels - but the gap was found in held-out diagnostics, so results on it are POST-HOC, not clean held-out.
2. CHW_SETPOINT_LOW cost. The detector used the guide's ~3.5 % per degC. The meters show 5.5 degC costs 6.5-10 % more kW/TR than 7.0 degC at the
   same load (single-chiller hours, staging signature removed) - about 4.3-6.8 % per degC. We re-cost the setpoint alerts with that measured
   penalty per load band. Physics measured from meters, no labels; still a post-freeze change, so labelled.
"""
import numpy as np
import pandas as pd

from detector import CHW_STD, site_frame
from evaluation import tuning_label_mask
from features import CLEAN

TUNE_END = pd.Timestamp("2026-04-01")
BANDS = [20, 80, 130, 200, 280]
ONE_CHILLER_MAX_TR = 280          # guide: CH-1 alone up to 280 TR


def _frame() -> pd.DataFrame:
    d = site_frame("GGN", with_resid=False)
    sub = pd.read_parquet(CLEAN / "sub_ggn_hourly.parquet")[["timestamp", "chiller_ch1_kw", "chiller_ch3_kw"]]
    d = d.drop(columns=[c for c in ("chiller_ch1_kw", "chiller_ch3_kw") if c in d]).merge(sub, on="timestamp", how="left")
    d["kwtr"] = d.chillers_kw / d.chiller_load_tr.where(d.chiller_load_tr > 20)
    d["band"] = pd.cut(d.chiller_load_tr, BANDS)
    return d


def fit(d: pd.DataFrame) -> dict:
    """Normal one-chiller kW/TR per load band at 7.0 degC, and the flag ratio, from tuning-window hours with tuning labels removed."""
    lab = tuning_label_mask("GGN", d.timestamp).to_numpy()
    t = d[(d.timestamp < TUNE_END) & ~lab & (d.n_chillers == 1) & (d.chw_setpoint_c == CHW_STD) & d.kwtr.notna() & ~d.fault]
    curve = t.groupby("band", observed=True).kwtr.median()
    ratio = t.kwtr / t.band.map(curve).astype(float)
    # The tuning-window ratio is bimodal: ~4,100 h at 0.9-1.15x normal, then nothing until 1.5x (the two-chiller signature). The threshold
    # sits in the middle of that empty range, found without labels (all tuning hours, labelled or not, are in this histogram).
    h, edges = np.histogram(ratio.to_numpy(), bins=np.arange(1.0, 2.0, 0.05))
    lo = edges[:-1][h == 0]                                           # first empty bin above the normal mode
    hi_mass = edges[:-1][(h > 0) & (edges[:-1] > (lo[0] if len(lo) else 1.2))]   # first occupied bin after the gap
    thr = float(round((lo[0] + hi_mass[0]) / 2, 2)) if len(lo) and len(hi_mass) else 1.3
    # setpoint penalty per band: single-chiller hours below the staging threshold, 5.5 vs 7.0 degC (whole year, meters only)
    s = d[(d.n_chillers == 1) & d.kwtr.notna() & ~d.fault]
    s = s[s.kwtr / s.band.map(curve).astype(float) < thr]
    m = s.groupby(["band", "chw_setpoint_c"], observed=True).kwtr.median().unstack()
    pen = (m[5.5] / m[CHW_STD] - 1) if 5.5 in m else pd.Series(0.0, index=m.index)
    return dict(curve=curve, thr=thr, n_tune=len(t), chw_penalty=pen)


def _runs(flag: np.ndarray, gap: int, min_len: int, breaks: np.ndarray | None = None):
    """Runs of flagged hours, merging gaps up to `gap` hours - but never across a `breaks` hour (meter faults: T5)."""
    idx = np.flatnonzero(flag)
    if not len(idx):
        return
    cb = np.concatenate([[0], np.cumsum(breaks)]) if breaks is not None else None
    start = 0
    for i in range(1, len(idx) + 1):
        crosses = cb is not None and i < len(idx) and cb[idx[i]] - cb[idx[i - 1] + 1] > 0
        if i == len(idx) or idx[i] - idx[i - 1] - 1 > gap or crosses:
            if i - start >= min_len:
                yield idx[start:i]
            start = i


def _rate() -> float:
    a = pd.read_parquet(CLEAN / "alerts.parquet").query("site == 'GGN' and rule == 'CHILLER_STAGING_LOW_LOAD' and excess_kwh > 0")
    return float((a.cost_inr / a.excess_kwh).median())                # same marginal ₹/kWh the detector used


def flagged(d: pd.DataFrame, F: dict) -> tuple:
    """(flag mask, expected one-chiller kW/TR now, expected at 7.0 °C) for the STAGING_KWTR rule."""
    exp = d.band.map(F["curve"]).astype(float)
    pen = d.band.map(F["chw_penalty"]).astype(float).fillna(0)
    exp_now = exp * np.where(d.chw_setpoint_c < CHW_STD, 1 + pen, 1.0)    # don't count the setpoint's own penalty twice
    flag = ((d.n_chillers == 1) & d.chiller_load_tr.between(BANDS[0], ONE_CHILLER_MAX_TR) & (d.kwtr > F["thr"] * exp_now) & ~d.fault).to_numpy()
    return flag, exp_now, exp


def ch1_summary(d: pd.DataFrame, F: dict) -> dict:
    """The CH-1 inefficiency in numbers, for the card's cause text and the savings NOT_SIZED line (all from the meters)."""
    flag, _, exp = flagged(d, F)
    x = d[flag]
    return dict(kwtr=float(x.kwtr.median()) if len(x) else float("nan"), normal_lo=float(F["curve"].min()), normal_hi=float(F["curve"].max()),
                hours=int(flag.sum()), ch3_on_h=int((x.chiller_ch3_kw > 5).sum()))


def staging_kwtr_alerts(d: pd.DataFrame, F: dict) -> pd.DataFrame:
    flag, exp_now, exp = flagged(d, F)
    excess = (d.chillers_kw - exp_now * d.chiller_load_tr).clip(lower=0)
    rate = _rate()
    rows = []
    for run in _runs(flag, gap=6, min_len=2, breaks=d.fault.to_numpy().astype(int)):
        seg = d.iloc[run]
        kwh = float(excess.iloc[run].sum())
        t0, t1 = seg.timestamp.iloc[0], seg.timestamp.iloc[-1] + pd.Timedelta(hours=1)
        ch3 = float(seg.chiller_ch3_kw.max())
        rows.append(dict(site="GGN", rule="STAGING_KWTR", start=t0, end=t1, alert_time=seg.timestamp.iloc[1] + pd.Timedelta(hours=1),
                         flagged_h=len(run), excess_kwh=kwh, cost_inr=kwh * rate,
                         evidence=(f"CH-1 at {seg.kwtr.mean():.2f} kW/TR for {len(run)} h at {seg.chiller_load_tr.mean():.0f} TR; it normally needs "
                                   f"{exp.iloc[run].mean():.2f} at this load. "
                                   + ("CH-3's sub-meter reads 0 kW throughout, so CH-1 is running alone (not a second chiller)" if ch3 <= 5
                                      else f"CH-3's sub-meter reads up to {ch3:.0f} kW in these hours"))))
    return pd.DataFrame(rows)


def chw_recost(cards: pd.DataFrame, d: pd.DataFrame, F: dict) -> pd.DataFrame:
    """Re-cost CHW_SETPOINT_LOW alerts with the measured penalty instead of 3.5 %/degC. Returns cards with old cost kept."""
    c = cards.copy()
    rate = _rate()
    pen = d.band.map(F["chw_penalty"]).astype(float)
    for i in c.index[c.rule == "CHW_SETPOINT_LOW"]:
        r = c.loc[i]
        seg = (d.timestamp >= r.start) & (d.timestamp < r.end) & (d.chw_setpoint_c < CHW_STD) & ~d.fault
        p = pen[seg].fillna(F["chw_penalty"].mean())
        kwh = float((d.chillers_kw[seg] * p / (1 + p)).sum())
        c.loc[i, ["cost_inr_guide", "excess_kwh", "cost_inr"]] = [r.cost_inr, kwh, kwh * rate]
        c.loc[i, "inr_per_hour"] = kwh * rate / max(r.flagged_h, 1)
        c.loc[i, "inr_per_day"] = c.loc[i, "inr_per_hour"] * 24
    return c


if __name__ == "__main__":
    from evaluation import tuning_labels, heldout_labels_for_diagnostics
    d = _frame()
    F = fit(d)
    print("curve", F["curve"].round(3).to_dict(), "thr", F["thr"], "tuning hours", F["n_tune"])
    print("CHW penalty per band (5.5 vs 7.0)", (F["chw_penalty"] * 100).round(1).to_dict())
    a = staging_kwtr_alerts(d, F)
    print(len(a), "alerts,", round(a.excess_kwh.sum()), "kWh, ₹", round(a.cost_inr.sum()))
    for name, L in (("tuning", tuning_labels()), ("held-out (diagnostic only)", heldout_labels_for_diagnostics())):
        L = L[L.site == "GGN"]
        sub = a[a.start < TUNE_END] if name == "tuning" else a[a.start >= TUNE_END]
        hit = [((L.start < r.end) & (L.end > r.start)).any() for r in sub.itertuples()]
        typ = [L[(L.start < r.end) & (L.end > r.start)].anomaly_type.tolist() for r in sub.itertuples()]
        print(name, len(sub), "alerts; overlapping a label:", sum(hit), "| types:", pd.Series([t for x in typ for t in x]).value_counts().to_dict())
