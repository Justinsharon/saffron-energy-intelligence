"""Scoring against the answer key, with the tune / report split enforced in code.

Why: CLAUDE.md forbids using labels from 1 Apr 2026 onward to inform the detector. `tuning_labels()` can only ever return rows that start before
the cut. `score_heldout()` is the only function that touches later rows and it returns aggregates only - no per-row listing - so tuning code
physically cannot browse them. Call it once, after the configuration is frozen.
"""
import numpy as np
import pandas as pd

from features import CLEAN

CUT = pd.Timestamp("2026-04-01")
SLACK = pd.Timedelta(hours=1)           # label times are hour-aligned; alerts are hourly


def _labels() -> pd.DataFrame:
    return pd.read_parquet(CLEAN / "anomaly_labels.parquet")


def tuning_labels() -> pd.DataFrame:
    """Labels that start before 1 Apr 2026 - the only ones the detector may be tuned on."""
    a = _labels()
    return a[a.start < CUT].reset_index(drop=True)


def tuning_label_mask(site: str, ts: pd.Series) -> pd.Series:
    m = pd.Series(False, index=ts.index)
    for r in tuning_labels().query("site == @site").itertuples():
        m |= (ts >= r.start) & (ts < r.end)
    return m


# rule -> label types it is expected to explain (from waste_types.WASTE_TYPES[...]["maps_to_labels"])
def _type_map():
    from waste_types import WASTE_TYPES
    return {k: set(v["maps_to_labels"]) for k, v in WASTE_TYPES.items()}


def _overlap(a_start, a_end, b_start, b_end):
    return (a_start < b_end + SLACK) & (a_end > b_start - SLACK)


def score(alerts: pd.DataFrame, labels: pd.DataFrame, faults: pd.DataFrame, window: str) -> dict:
    """Precision / recall / time-to-detect for one window ('tune' or 'report'); returns aggregates only.

    Alerts are assigned to a window by their start time (a label that starts before the cut belongs to tuning even if it runs past it).
    Precision = share of waste alerts overlapping a labelled non-fault anomaly on the same site (the BMS-alarm definition).
    Recall   = share of High+Medium waste labels with at least one overlapping alert.
    Time to detect = first *fresh* overlapping alert (raised on/after the label start, less the 1 h slack) minus label start, High severity.
    A label that an earlier alert already covers when it starts (one long alert spanning overlapping labels, or a recurring episode merged
    into one alert) is "pre-alerted": it counts as detected but is excluded from the time-to-detect statistics and reported separately.
    """
    in_win = (lambda t: t < CUT) if window == "tune" else (lambda t: t >= CUT)
    lab = labels[labels.start.map(in_win)]
    waste = lab[lab.severity != "Data quality"]
    al = alerts[alerts.start.map(in_win) & (alerts.rule != "METER_DATA_FAULT")]
    tmap = _type_map()

    def hit_any(a):
        w = waste[waste.site == a.site]
        return bool(_overlap(a.start, a.end, w.start, w.end).any())

    def hit_typed(a):
        w = waste[(waste.site == a.site) & waste.anomaly_type.isin(tmap.get(a.rule, set()))]
        return bool(_overlap(a.start, a.end, w.start, w.end).any())

    al = al.assign(match_any=[hit_any(a) for a in al.itertuples()], match_typed=[hit_typed(a) for a in al.itertuples()])
    rows = []
    for r in waste.itertuples():
        m = alerts[(alerts.site == r.site) & _overlap(alerts.start, alerts.end, r.start, r.end) & (alerts.rule != "METER_DATA_FAULT")]
        fresh = m[m.alert_time >= r.start - SLACK]
        ttd = (fresh.alert_time.min() - r.start).total_seconds() / 3600 if len(fresh) else np.nan
        rows.append(dict(sev=r.severity, typ=r.anomaly_type, site=r.site, detected=len(m) > 0, pre_alerted=len(m) > 0 and len(fresh) == 0,
                         ttd_h=max(ttd, 0) if len(fresh) else np.nan, cost=r.excess_cost_inr))
    L = pd.DataFrame(rows)
    hm = L[L.sev.isin(["High", "Medium"])]
    hi = L[(L.sev == "High") & L.detected & ~L.pre_alerted]
    fl = lab[lab.severity == "Data quality"]
    f_det = [bool(((faults.site == r.site) & _overlap(faults.start, faults.end, r.start, r.end)).any()) for r in fl.itertuples()]
    res = dict(window=window, n_labels=len(waste), n_alerts=len(al), n_alert_units=int(al.shape[0]),
               precision_any=al.match_any.mean() if len(al) else np.nan,
               precision_typed=al.match_typed.mean() if len(al) else np.nan,
               recall_HM=hm.detected.mean() if len(hm) else np.nan, n_HM=len(hm),
               recall_all=L.detected.mean() if len(L) else np.nan,
               ttd_high_median_h=hi.ttd_h.median() if len(hi) else np.nan,
               ttd_high_under_2h=(hi.ttd_h < 2).mean() if len(hi) else np.nan, n_high=int((L.sev == "High").sum()),
               n_high_detected=int(((L.sev == "High") & L.detected).sum()), n_high_pre_alerted=int(((L.sev == "High") & L.pre_alerted).sum()),
               n_high_fresh=len(hi), n_pre_alerted_all=int(L.pre_alerted.sum()),
               cost_found_share=(L[L.detected].cost.sum() / L.cost.sum()) if L.cost.sum() else np.nan,
               fault_labels=len(fl), faults_detected=int(sum(f_det)))
    by_type = L.groupby("typ").agg(n=("detected", "size"), detected=("detected", "sum"), pre_alerted=("pre_alerted", "sum"), median_ttd_h=("ttd_h", "median")).reset_index()
    by_sev = L.groupby("sev").agg(n=("detected", "size"), detected=("detected", "sum")).reset_index()
    by_rule = al.groupby("rule").agg(alerts=("alert_id", "size"), precise=("match_any", "mean"), typed=("match_typed", "mean")).reset_index()
    return dict(summary=res, by_type=by_type, by_sev=by_sev, by_rule=by_rule, alerts_scored=al)


def onset_ttd(alerts: pd.DataFrame, labels: pd.DataFrame, flags: dict, window: str) -> dict:
    """Time to detect measured from when the fault first shows in the data (the owner's definition), High severity.

    Onset = first hour inside the label window where a raw rule flag for that label type is true (before the persistence / min_h rule).
    TTD = first alert of those rules covering the onset, minus onset. Hourly meters give a floor of 1 h. Persistence beyond one hour shows
    up here; the gap between label start and onset (label windows open early) is reported separately as `label_to_onset_h`.
    `flags`: {site: {rule: boolean Series indexed by timestamp}}, built from detector.rule_signals. Aggregates only - no per-label rows -
    so that it is safe to call on the held-out window.
    """
    in_win = (lambda t: t < CUT) if window == "tune" else (lambda t: t >= CUT)
    hi = labels[labels.start.map(in_win) & (labels.severity == "High")]
    tmap = _type_map()
    rows = []
    for r in hi.itertuples():
        rules = [k for k, v in tmap.items() if r.anomaly_type in v and k in flags.get(r.site, {})]
        onset = pd.NaT
        for k in rules:
            f = flags[r.site][k]
            hit = f.index[f.to_numpy(bool) & (f.index >= r.start) & (f.index < r.end)]
            if len(hit):
                onset = hit.min() if pd.isna(onset) else min(onset, hit.min())
        if pd.isna(onset):
            rows.append(dict(onset_found=False, pre_alerted=False, ttd_h=np.nan, label_to_onset_h=np.nan))
            continue
        m = alerts[(alerts.site == r.site) & alerts.rule.isin(rules) & (alerts.start <= onset) & (alerts.end > onset)]
        at = m.alert_time.min() if len(m) else pd.NaT
        pre = bool(pd.notna(at) and at < onset)
        rows.append(dict(onset_found=True, pre_alerted=pre, ttd_h=(at - onset).total_seconds() / 3600 if pd.notna(at) and not pre else np.nan,
                         label_to_onset_h=(onset - r.start).total_seconds() / 3600))
    L = pd.DataFrame(rows, columns=["onset_found", "pre_alerted", "ttd_h", "label_to_onset_h"])
    return dict(window=window, n_high=len(L), n_onset_found=int(L.onset_found.sum()), n_pre_alerted=int(L.pre_alerted.sum()),
                n_scored=int(L.ttd_h.notna().sum()), n_no_onset_or_no_alert=int((L.onset_found & ~L.pre_alerted & L.ttd_h.isna()).sum() + (~L.onset_found).sum()),
                ttd_onset_median_h=L.ttd_h.median(), ttd_onset_max_h=L.ttd_h.max(), ttd_onset_under_2h=(L.ttd_h.dropna() <= 2).mean() if L.ttd_h.notna().any() else np.nan,
                label_to_onset_median_h=L.label_to_onset_h.median())


def heldout_labels_for_diagnostics() -> pd.DataFrame:
    """Labels from 1 Apr 2026, for *diagnostic checks only* (owner-permitted: accuracy / precision checks, never model fitting).

    Nothing returned here may be used to set a rule, threshold, profile or model parameter. notebooks/06_heldout_diagnostics is the only caller.
    """
    a = _labels()
    return a[a.start >= CUT].reset_index(drop=True)


def score_heldout(alerts: pd.DataFrame, faults: pd.DataFrame) -> dict:
    """The one place later labels are read. Returns aggregates only (no label rows, no alert-vs-label pairing)."""
    out = score(alerts, _labels(), faults, "report")
    out.pop("alerts_scored")                              # per-alert match flags would reveal which labels were hit
    return out


def score_heldout_onset(alerts: pd.DataFrame, flags: dict) -> dict:
    """Onset-based time to detect on the held-out window (aggregates only). Scoring-side addition made after the freeze; detector untouched."""
    return onset_ttd(alerts, _labels(), flags, "report")
