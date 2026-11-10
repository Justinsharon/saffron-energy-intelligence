"""Context-aware waste detector: engineering-rule layer + main-meter residual layer + meter-fault stream.

Why this shape (details and evidence in notebooks/04_waste_types and 05_detector):
- Rule layer: each waste type has a physical signature on a sub-meter (or PF / BMS setpoint). Thresholds are *learned profiles* of normal
  behaviour for the same context (hour, outdoor-temperature band, event on/off, plant load) taken from the tuning window with labelled hours
  removed, so a heatwave, an occupied night or a wedding is compared against its own kind of hour and does not alert.
- Residual layer: persistent positive gap between the main meter and the baseline (src/baseline.py), for waste no rule describes.
  Only reported when no rule alert covers the same time ("unexplained deviation").
- Fault stream: flat-lined / zero / missing billed readings. Fault hours are removed from every waste signal (T5), never alerts or savings.

Leakage: nothing here reads anomaly_labels except `fit_params(..., label_mask=...)`, which only excludes tuning-window labelled hours from
the *normal-behaviour* profiles. Thresholds are frozen in PARAMS_* constants before the held-out window is scored.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from baseline import build_features
from features import CLEAN

CUT = pd.Timestamp("2026-04-01")                       # tune before, report from
SITES = ["GGN", "JAI", "GOA"]
PEAK = {"GGN": (18, 22), "JAI": (17, 23), "GOA": (18, 22)}      # [start, end) hour, per hotel tariff sheet
CHW_STD, CHW_FLOOR = 7.0, 6.5                          # engineering guide
CHW_PCT_PER_C = 0.035                                  # +3-4% chiller power per degC lower (guide)
GOOD_KW_PER_TR = 0.65                                  # guide: good efficiency ~0.6 kW/TR

# ---- frozen configuration (chosen on the tuning window, see notebook 05 section 3) -------------------------
# min_h = flagged hours needed before an alert is raised; gap_h = largest gap of unflagged hours merged into one alert.
RULES = {
    "AHU_HAND_MODE":                  dict(min_h=1, gap_h=3),
    "HEAT_COOL_FIGHT":                dict(min_h=1, gap_h=18),     # re-heat shows up in the daytime only: one alert per multi-day episode
    "KITCHEN_EXHAUST_OFF_HOURS":      dict(min_h=2, gap_h=18),
    "LIGHTING_LEFT_ON":               dict(min_h=2, gap_h=3),
    "LAUNDRY_IN_PEAK":                dict(min_h=1, gap_h=2),
    "POOL_PUMP_OFF_SCHEDULE":         dict(min_h=3, gap_h=12),
    "POWER_FACTOR_DROP":              dict(min_h=1, gap_h=6),
    "CHILLER_STAGING_LOW_LOAD":       dict(min_h=1, gap_h=3),
    "CHILLER_PART_LOAD_INEFFICIENCY": dict(min_h=2, gap_h=3),
    "CHW_SETPOINT_LOW":               dict(min_h=1, gap_h=3),
    "RESIDUAL_UNEXPLAINED":           dict(min_h=4, gap_h=2),
}
PF_ALERT = 0.95            # guide: alarm when PF stays below 0.95
PF_NORMAL_FLOOR = 0.97     # APFC target
KW_FLOOR = dict(AHU=10.0, HEATER=5.0, KITCHEN=5.0, LIGHTING=8.0, LAUNDRY=10.0, POOL=5.0)  # kW: below this a deviation is noise
KWTR_MARGIN = 0.12         # kW/TR above the learned curve (curve noise is ~0.02)
PROFILE_Q, PROFILE_PAD = 0.995, 1.05
RESID = dict(z=4.0, floor_frac=0.08)   # residual layer: z over hour-specific sigma and at least this share of expected load


@dataclass
class Params:
    rate_kwh: dict = field(default_factory=dict)       # marginal grid Rs per kWh (energy + FSA + duty) / PF
    rate_kvah: dict = field(default_factory=dict)
    peak_surcharge: dict = field(default_factory=dict)
    pf_ref: dict = field(default_factory=dict)
    prof: dict = field(default_factory=dict)           # (site, name) -> DataFrame of cell stats
    kwtr_curve: dict = field(default_factory=dict)     # site -> (TR centres, median kW/TR)
    sigma_hour: dict = field(default_factory=dict)     # site -> Series by hour (robust residual sigma)


def _tariff(site: str) -> dict:
    t = pd.read_parquet(CLEAN / "tariffs.parquet").query("site == @site").set_index("component").rate
    return dict(energy=t["Energy charge"], fsa=t["Fuel surcharge adjustment (FSA)"], duty=t["Electricity duty"],
                peak=t["Peak ToD surcharge"])


# ---------------------------------------------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------------------------------------------
def site_frame(site: str, with_resid: bool = True) -> pd.DataFrame:
    """Hourly frame: baseline drivers + harmonised sub-meter columns + meter-fault flag + out-of-fold baseline."""
    d = build_features(site)
    if site == "GGN":
        s = pd.read_parquet(CLEAN / "sub_ggn_hourly.parquet")
        s = pd.DataFrame({"timestamp": s.timestamp, "chillers_kw": s.chiller_ch1_kw + s.chiller_ch2_kw + s.chiller_ch3_kw,
                          "ahu_banquet_kw": s.ahu_banquet_kw, "ahu_heaters_kw": s.ahu_heaters_kw,
                          "kitchen_exhaust_kw": s.kitchen_exhaust_mua_kw, "laundry_kw": s.laundry_kw,
                          "lighting_kw": s.lighting_public_kw, "chiller_load_tr": s.chiller_load_tr,
                          "n_chillers": s.chillers_running, "chw_setpoint_c": s.chw_setpoint_c})
    else:
        s = pd.read_parquet(CLEAN / "sub_jai_goa_hourly.parquet").query("site == @site")
        s = pd.DataFrame({"timestamp": s.timestamp, "chillers_kw": s.chillers_kw, "laundry_kw": s.laundry_kw,
                          "lighting_kw": s.lighting_kw, "pool_pump_kw": s.pumps_pool_kw, "chiller_load_tr": s.chiller_load_tr})
    d = d.merge(s, on="timestamp", how="left")
    d["event_on"] = d.ev_guests > 0
    d["tband"] = (np.floor(d.temp_c / 3) * 3)
    d["peak_window"] = d.hour.between(PEAK[site][0], PEAK[site][1] - 1)
    f = detect_meter_faults(site)
    d["fault"] = False
    for r in f.itertuples():
        d.loc[(d.timestamp + pd.Timedelta(hours=1) > r.start) & (d.timestamp < r.end), "fault"] = True
    if with_resid:
        o = pd.read_parquet(CLEAN / "baseline_oof.parquet").query("site == @site")[["timestamp", "pred_ens"]]
        d = d.merge(o, on="timestamp", how="left")
        d["resid"] = d.total_kwh - d.pred_ens
    return d


def detect_meter_faults(site: str, flat_repeats: int = 3, zero_run: int = 2) -> pd.DataFrame:
    """Faults in the billed readings, found from the *raw* columns only (no flags, no labels).

    GGN 15-min: a run of identical raw kWh (>= flat_repeats repeats) or raw 0 while kw_avg is live on GRID supply.
    Hourly meters: missing raw readings (gap) or identical kWh repeated for >= flat_repeats hours.
    Returns start, end (end exclusive), kind, detected_at and the evidence.
    """
    out = []
    if site == "GGN":
        g = pd.read_parquet(CLEAN / "meter_ggn_15min.parquet")
        raw, kw, grid = g.grid_kwh_raw, g.kw_avg, g.supply_source.eq("GRID")
        same = raw.eq(raw.shift()) & grid
        zero = raw.eq(0) & kw.gt(50) & grid
        step = pd.Timedelta(minutes=15)
        for mask, kind, need in ((same, "flat line", flat_repeats), (zero, "zero reading", zero_run)):
            run = (mask != mask.shift()).cumsum()
            for _, idx in g[mask].groupby(run[mask]).groups.items():
                if len(idx) >= need:
                    t0, t1 = g.timestamp[idx[0]], g.timestamp[idx[-1]]
                    start = t0 - step if kind == "flat line" else t0          # the first frozen reading is itself a true one
                    seg = g[(g.timestamp >= t0) & (g.timestamp <= t1)]
                    out.append(dict(site=site, start=start, end=t1 + step, kind=kind,
                                    detected_at=g.timestamp[idx[need - 1]] + step,
                                    evidence=f"billed kWh {'frozen at ' + format(raw[idx[0]], '.2f') if kind == 'flat line' else 'reads 0'} for "
                                             f"{len(idx)} intervals while kW stays live (mean {seg.kw_avg.mean():.0f} kW)"))
    else:
        h = pd.read_parquet(CLEAN / f"meter_{site.lower()}_hourly.parquet")
        raw = h["grid_kwh_raw"] if "grid_kwh_raw" in h else h["grid_kwh"]
        grid = ~h.is_dg
        for mask, kind, need in ((raw.isna() & grid, "missing readings", 2), (raw.eq(raw.shift()) & grid & raw.notna(), "flat line", flat_repeats)):
            run = (mask != mask.shift()).cumsum()
            for _, idx in h[mask].groupby(run[mask]).groups.items():
                if len(idx) >= need:
                    t0, t1 = h.timestamp[idx[0]], h.timestamp[idx[-1]]
                    out.append(dict(site=site, start=t0, end=t1 + pd.Timedelta(hours=1), kind=kind,
                                    detected_at=h.timestamp[idx[need - 1]] + pd.Timedelta(hours=1),
                                    evidence=f"{len(idx)} h with {kind} on the billed meter"))
    f = pd.DataFrame(out, columns=["site", "start", "end", "kind", "detected_at", "evidence"])
    for c in ("start", "end", "detected_at"):
        f[c] = pd.to_datetime(f[c])                          # an empty frame (e.g. Goa has no faults) must keep datetime dtype
    return f


# ---------------------------------------------------------------------------------------------------------------
# Normal-behaviour profiles (fit on the tuning window, labelled hours removed)
# ---------------------------------------------------------------------------------------------------------------
def _profile(x: pd.Series, keys: pd.DataFrame, fit: pd.Series) -> pd.DataFrame:
    """Median and high quantile of x per context cell, plus a per-first-key fallback for cells never seen."""
    k = list(keys.columns)
    g = x[fit].groupby([keys.loc[fit, c] for c in k])
    cell = pd.DataFrame({"med": g.median(), "hi": g.quantile(PROFILE_Q), "n": g.size()})
    cell.index.names = k
    return cell


def _lookup(cell: pd.DataFrame, keys: pd.DataFrame, minn: int = 12) -> tuple[np.ndarray, np.ndarray]:
    k = list(keys.columns)
    ok = cell[cell.n >= minn]
    idx = pd.MultiIndex.from_frame(keys[k])
    med, hi = ok.med.reindex(idx).to_numpy().copy(), ok.hi.reindex(idx).to_numpy().copy()
    if len(k) > 1:                                       # fallback to the first key alone (e.g. hour)
        top = cell.reset_index().groupby(k[0]).agg(med=("med", "median"), hi=("hi", "max"))
        miss = np.isnan(med)
        med[miss] = top.med.reindex(keys[k[0]][miss]).to_numpy()
        hi[miss] = top.hi.reindex(keys[k[0]][miss]).to_numpy()
    return med, hi


def fit_params(frames: dict, label_mask: dict) -> Params:
    """Fit all normal-behaviour profiles on hours before CUT that are valid, fault-free and not inside a tuning label."""
    P = Params()
    for s, d in frames.items():
        tr = _tariff(s)
        fit = (d.timestamp < CUT) & d.valid & ~d.fault & ~label_mask[s]
        pf = (d.grid_kwh / d.grid_kvah)[fit & ~d.is_dg].median()
        P.pf_ref[s] = float(pf)
        P.rate_kvah[s] = tr["energy"] + tr["fsa"] + tr["duty"]
        P.rate_kwh[s] = P.rate_kvah[s] / pf
        P.peak_surcharge[s] = tr["peak"]
        if s == "GGN":
            P.prof[s, "heaters"] = _profile(d.ahu_heaters_kw, d[["hour", "tband"]], fit)
            P.prof[s, "kitchen"] = _profile(d.kitchen_exhaust_kw, d[["hour"]], fit)
        P.prof[s, "lighting"] = _profile(d.lighting_kw, d[["hour", "event_on"]], fit)
        if s != "GGN":
            P.prof[s, "pool"] = _profile(d.pool_pump_kw, d[["hour"]], fit)
            ok = fit & d.chiller_load_tr.gt(0)
            band = (d.chiller_load_tr[ok] // 20) * 20 + 10
            c = (d.chillers_kw / d.chiller_load_tr)[ok].groupby(band).agg(["median", "size"]).query("size >= 20")
            P.kwtr_curve[s] = (c.index.to_numpy(float), c["median"].to_numpy(float))
        if "resid" in d:
            r = d.resid[fit]
            P.sigma_hour[s] = r.groupby(d.hour[fit]).agg(lambda v: 1.4826 * np.median(np.abs(v - np.median(v))))
    return P


# ---------------------------------------------------------------------------------------------------------------
# Rule flags -> (flag, excess kW)  [kW over normal; Rs computed in _cost]
# ---------------------------------------------------------------------------------------------------------------
def _profile_flag(x, cell, keys, floor):
    med, hi = _lookup(cell, keys)
    thr = np.maximum(hi * PROFILE_PAD, med + floor)
    xv = x.to_numpy(float)
    flag = (xv > thr) & ~np.isnan(xv)
    return pd.Series(flag, index=x.index), pd.Series(np.where(flag, xv - med, 0.0), index=x.index)


def rule_signals(site: str, d: pd.DataFrame, P: Params) -> dict:
    sig = {}
    ok = ~d.fault                                                    # T5: nothing is judged inside a meter fault
    if site == "GGN":
        f = (d.ahu_banquet_kw > KW_FLOOR["AHU"]) & ~d.event_on
        sig["AHU_HAND_MODE"] = (f, d.ahu_banquet_kw.where(f, 0.0))
        f, ex = _profile_flag(d.ahu_heaters_kw, P.prof[site, "heaters"], d[["hour", "tband"]], KW_FLOOR["HEATER"])
        warm = (d.temp_c > 16) & (d.ahu_heaters_kw > KW_FLOOR["HEATER"])          # guide interlock: no re-heat above 16 degC
        sig["HEAT_COOL_FIGHT"] = (f | warm, ex.where(f, d.ahu_heaters_kw.where(warm, 0.0)))
        sig["KITCHEN_EXHAUST_OFF_HOURS"] = _profile_flag(d.kitchen_exhaust_kw, P.prof[site, "kitchen"], d[["hour"]], KW_FLOOR["KITCHEN"])
        f = (d.n_chillers >= 2) & (d.chiller_load_tr < 130)
        sig["CHILLER_STAGING_LOW_LOAD"] = (f, (d.chillers_kw - GOOD_KW_PER_TR * d.chiller_load_tr).clip(lower=0).where(f, 0.0))
        f = d.chw_setpoint_c < CHW_STD - 1e-9
        frac = CHW_PCT_PER_C * (CHW_STD - d.chw_setpoint_c)
        sig["CHW_SETPOINT_LOW"] = (f, (d.chillers_kw * frac / (1 + frac)).where(f, 0.0))
    else:
        sig["POOL_PUMP_OFF_SCHEDULE"] = _profile_flag(d.pool_pump_kw, P.prof[site, "pool"], d[["hour"]], KW_FLOOR["POOL"])
        x, y = P.kwtr_curve[site]
        exp = np.interp(d.chiller_load_tr.fillna(0), x, y)
        f = (d.chiller_load_tr > 0) & (d.chillers_kw / d.chiller_load_tr > exp + KWTR_MARGIN)
        sig["CHILLER_PART_LOAD_INEFFICIENCY"] = (f, (d.chillers_kw - exp * d.chiller_load_tr).clip(lower=0).where(f, 0.0))
    sig["LIGHTING_LEFT_ON"] = _profile_flag(d.lighting_kw, P.prof[site, "lighting"], d[["hour", "event_on"]], KW_FLOOR["LIGHTING"])
    f = d.peak_window & (d.laundry_kw > KW_FLOOR["LAUNDRY"])
    sig["LAUNDRY_IN_PEAK"] = (f, d.laundry_kw.where(f, 0.0))
    pf = (d.grid_kwh / d.grid_kvah).where((d.grid_kvah > 0) & ~d.is_dg)
    f = pf < PF_ALERT
    sig["POWER_FACTOR_DROP"] = (f, (d.grid_kwh * (1 / pf - 1 / P.pf_ref[site])).where(f, 0.0))   # excess kVAh stored in the kW slot
    return {k: (a.fillna(False) & ok, b.fillna(0.0)) for k, (a, b) in sig.items()}


# ---------------------------------------------------------------------------------------------------------------
# Episodes -> alerts
# ---------------------------------------------------------------------------------------------------------------
def _episodes(flag: np.ndarray, min_h: int, gap_h: int):
    """Runs of flagged hours merged across gaps <= gap_h. Yields (first, last, n_flagged, k-th flagged index)."""
    idx = np.flatnonzero(flag)
    if len(idx) == 0:
        return
    start = 0
    for i in range(1, len(idx) + 1):
        if i == len(idx) or idx[i] - idx[i - 1] - 1 > gap_h:
            run = idx[start:i]
            if len(run) >= min_h:
                yield run
            start = i


def _event_context(site: str, t0: pd.Timestamp, t1: pd.Timestamp) -> str:
    ev = pd.read_parquet(CLEAN / "events.parquet").query("site == @site")
    def span(r):
        s = pd.Timestamp(r.date) + pd.Timedelta(hours=int(r.start_time[:2]), minutes=int(r.start_time[3:]))
        e = (pd.Timestamp(r.date) + pd.Timedelta(days=1, hours=1)) if r.ends_after_midnight else \
            pd.Timestamp(r.date) + pd.Timedelta(hours=int(r.end_time[:2]), minutes=int(r.end_time[3:]))
        return s, e
    sp = [(span(r), r) for r in ev.itertuples()]
    prev = [(e, r) for (s, e), r in sp if e <= t0 + pd.Timedelta(hours=1)]
    nxt = [(s, r) for (s, e), r in sp if s >= t1]
    p = max(prev, key=lambda x: x[0]) if prev else None
    n = min(nxt, key=lambda x: x[0]) if nxt else None
    a = f"last event: {p[1].event_type} ({p[1].venue}, {p[1].guests} guests) ended {p[0]:%d %b %H:%M}" if p else "no earlier event in calendar"
    b = f"; next event {n[0]:%d %b %H:%M}" if n else "; no later event in calendar"
    return a + b


def _evidence(rule: str, site: str, d: pd.DataFrame, fl: np.ndarray, P: Params, t0, t1) -> str:
    seg = d.iloc[fl]
    n = len(seg)
    if rule == "AHU_HAND_MODE":
        return (f"Banquet AHU draw {seg.ahu_banquet_kw.mean():.0f} kW for {n} h with no event active; " + _event_context(site, t0, t1))
    if rule == "HEAT_COOL_FIGHT":
        return (f"AHU re-heat {seg.ahu_heaters_kw.mean():.0f} kW on average over {n} flagged h (daytime outdoor {seg.temp_c.mean():.0f} degC), "
                f"while chillers carried {seg.chiller_load_tr.mean():.0f} TR")
    if rule == "KITCHEN_EXHAUST_OFF_HOURS":
        return f"Exhaust + make-up air at {seg.kitchen_exhaust_kw.mean():.0f} kW for {n} h in hours when the learned profile is off (kitchen closed)"
    if rule == "LIGHTING_LEFT_ON":
        return (f"Lighting {seg.lighting_kw.mean():.0f} kW for {n} h vs {(seg.lighting_kw - seg.excess_kw).mean():.0f} kW normal for those hours; "
                + _event_context(site, t0, t1))
    if rule == "LAUNDRY_IN_PEAK":
        return f"Laundry {seg.laundry_kw.mean():.0f} kW for {n} h inside the {PEAK[site][0]}:00-{PEAK[site][1]}:00 peak window"
    if rule == "POOL_PUMP_OFF_SCHEDULE":
        return f"Pool pumps {seg.pool_pump_kw.mean():.0f} kW for {n} h outside the usual schedule (normal off-schedule level {(seg.pool_pump_kw - seg.excess_kw).mean():.0f} kW)"
    if rule == "POWER_FACTOR_DROP":
        pf = (seg.grid_kwh / seg.grid_kvah)
        return f"Hourly PF {pf.mean():.3f} (min {pf.min():.3f}) vs {P.pf_ref[site]:.3f} normal; kWh unchanged, kVAh up {(P.pf_ref[site] / pf.mean() - 1) * 100:.1f}%"
    if rule == "CHILLER_STAGING_LOW_LOAD":
        return (f"Two chillers on for {n} h at {seg.chiller_load_tr.mean():.0f} TR (CH-3 alone can carry 130 TR): {seg.chillers_kw.mean() / seg.chiller_load_tr.mean():.2f} kW/TR "
                f"vs ~{GOOD_KW_PER_TR} expected")
    if rule == "CHILLER_PART_LOAD_INEFFICIENCY":
        return f"Chiller plant at {seg.chillers_kw.mean() / seg.chiller_load_tr.mean():.2f} kW/TR for {n} h at {seg.chiller_load_tr.mean():.0f} TR vs {np.interp(seg.chiller_load_tr.mean(), *P.kwtr_curve[site]):.2f} normal"
    if rule == "CHW_SETPOINT_LOW":
        cmd = pd.read_parquet(CLEAN / "bms_command_log.parquet").query("site == @site and point == 'CHW supply setpoint'")
        c = cmd[cmd.timestamp <= t0 + pd.Timedelta(hours=1)].tail(1)
        who = f"; BMS log: {c.old_value.iloc[0]:g} -> {c.new_value.iloc[0]:g} degC at {c.timestamp.iloc[0]:%d %b %H:%M} by {c.changed_by.iloc[0]}" if len(c) else ""
        return f"CHW supply setpoint {seg.chw_setpoint_c.min():.1f} degC for {n} h (standard {CHW_STD} degC, limit {CHW_FLOOR}){who}"
    return ""


def _cost(rule: str, site: str, seg: pd.DataFrame, P: Params) -> tuple[float, float]:
    """(excess kWh, Rs). Laundry: Rs = peak surcharge only (energy is shifted, not saved). PF: excess kVAh x rates."""
    if rule == "LAUNDRY_IN_PEAK":
        return 0.0, float((seg.laundry_kw / P.pf_ref[site]).sum() * P.peak_surcharge[site])
    if rule == "POWER_FACTOR_DROP":
        return 0.0, float(seg.excess_kw.sum() * P.rate_kvah[site])
    return float(seg.excess_kw.sum()), float(seg.excess_kw.sum() * P.rate_kwh[site])


def detect_site(site: str, d: pd.DataFrame, P: Params, use_resid: bool = True) -> pd.DataFrame:
    rows = []
    for rule, (flag, ex) in rule_signals(site, d, P).items():
        cfg = RULES[rule]
        dd = d.assign(excess_kw=ex.to_numpy())
        for run in _episodes(flag.to_numpy(), cfg["min_h"], cfg["gap_h"]):
            seg_idx = run
            seg = dd.iloc[seg_idx]
            t0, t1 = dd.timestamp.iloc[run[0]], dd.timestamp.iloc[run[-1]] + pd.Timedelta(hours=1)
            kwh, inr = _cost(rule, site, seg, P)
            n = len(seg_idx)
            rows.append(dict(site=site, rule=rule, start=t0, end=t1, alert_time=dd.timestamp.iloc[run[cfg["min_h"] - 1]] + pd.Timedelta(hours=1),
                             flagged_h=n, excess_kwh=kwh, cost_inr=inr, inr_per_hour=inr / n, inr_per_day=inr / n * 24,
                             evidence=_evidence(rule, site, dd, seg_idx, P, t0, t1)))
    out = pd.DataFrame(rows)
    if use_resid:
        out = pd.concat([out, residual_alerts(site, d, P, out)], ignore_index=True)
    return out


def residual_alerts(site: str, d: pd.DataFrame, P: Params, rule_alerts: pd.DataFrame) -> pd.DataFrame:
    """Persistent positive main-meter residual (actual - out-of-fold baseline) not already covered by a rule alert."""
    cfg = RULES["RESIDUAL_UNEXPLAINED"]
    sig = d.hour.map(P.sigma_hour[site]).to_numpy()
    z = d.resid.to_numpy() / np.where(sig > 0, sig, np.nan)
    flag = (z > RESID["z"]) & (d.resid.to_numpy() > RESID["floor_frac"] * d.pred_ens.to_numpy()) & d.valid.to_numpy() & ~d.fault.to_numpy()
    rows = []
    for run in _episodes(flag, cfg["min_h"], cfg["gap_h"]):
        seg = d.iloc[run]
        t0, t1 = seg.timestamp.iloc[0], seg.timestamp.iloc[-1] + pd.Timedelta(hours=1)
        if len(rule_alerts) and ((rule_alerts.start < t1 + pd.Timedelta(hours=2)) & (rule_alerts.end > t0 - pd.Timedelta(hours=2))).any():
            continue                                             # already explained by a named waste type
        kwh = float(seg.resid.sum())
        rows.append(dict(site=site, rule="RESIDUAL_UNEXPLAINED", start=t0, end=t1, alert_time=seg.timestamp.iloc[cfg["min_h"] - 1] + pd.Timedelta(hours=1),
                         flagged_h=len(run), excess_kwh=kwh, cost_inr=kwh * P.rate_kwh[site], inr_per_hour=kwh * P.rate_kwh[site] / len(run),
                         inr_per_day=kwh * P.rate_kwh[site] / len(run) * 24,
                         evidence=f"Site load {seg.total_kwh.mean():.0f} kW vs {seg.pred_ens.mean():.0f} kW expected for the weather, occupancy and events "
                                  f"(+{seg.resid.mean():.0f} kW, {seg.resid.mean() / seg.pred_ens.mean() * 100:.0f}%) for {len(run)} h; no named waste type matches"))
    return pd.DataFrame(rows)


def load_all(label_mask_fn=None) -> tuple[dict, Params]:
    """Frames for the three hotels and fitted profiles. label_mask_fn(site, timestamps) -> bool Series of tuning-labelled hours."""
    frames = {s: site_frame(s) for s in SITES}
    masks = {s: (label_mask_fn(s, frames[s].timestamp) if label_mask_fn else pd.Series(False, index=frames[s].index)) for s in SITES}
    return frames, fit_params(frames, masks)


def detect_all(frames: dict, P: Params, use_resid: bool = True) -> pd.DataFrame:
    a = pd.concat([detect_site(s, frames[s], P, use_resid) for s in SITES], ignore_index=True)
    a = a.sort_values(["alert_time", "site"]).reset_index(drop=True)
    a.insert(0, "alert_id", [f"AL-{i + 1:04d}" for i in range(len(a))])
    return a


def alert_text(a, names: dict | None = None) -> str:
    """Duty-engineer wording (brief section 13): what, where, since when, Rs/day, evidence, action. Facts only from the alert row."""
    from waste_types import WASTE_TYPES
    names = names or {"GGN": "Gurugram", "JAI": "Jaipur", "GOA": "Goa"}
    w = WASTE_TYPES.get(a.rule)
    title = w["label"] if w else "Unexplained load above baseline"
    act = w["action"] if w else "Check the largest loads for the period; no named waste type matches the signature."
    cost = f"~Rs {a.inr_per_hour:,.0f}/h (Rs {a.inr_per_day:,.0f}/day)" if a.cost_inr > 0 else "cost not material"
    guard = " [Recommendation only - a person approves.]" if not w or w["guardrail"] != "never" else \
        " [Recommendation only - never switched off automatically.]"
    return (f"{names[a.site]} - {title}, since {a.start:%d %b %H:%M} ({a.flagged_h} h flagged). {a.evidence}. {cost}. "
            f"Action: {act}{guard}")
