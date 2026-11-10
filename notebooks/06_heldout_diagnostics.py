# %% [markdown]
# # 06 · Held-out diagnostics — why the detector scores what it scores (diagnostic only)
# The project owner allowed labels from 1 Apr 2026 to be used to **check** accuracy and precision, **not** to build the model. So this notebook only *measures*:
# nothing here changes a rule, threshold, profile or model; `src/detector.py` is imported unmodified and the alerts are the ones frozen in notebook 05
# (`data/clean/alerts.parquet`). Where a finding suggests a change, it is written up as a **proposal** for a later "v2" and labelled post-hoc — a v2 tuned with this
# knowledge can no longer claim a clean held-out score.
#
# Questions: (1) is the 98 % precision / 96 % recall real once matching is made strict? (2) why is time-to-detect 3.0 h for High? (3) what are the two label types
# with no rule, and what would catching them take? (4) are the ₹ estimates right? (5) is the baseline accurate in the same months? (6) which T2 event-window alerts were real?

# %%
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

ROOT = Path.cwd() if (Path.cwd() / "data").exists() else Path.cwd().parent
sys.path.insert(0, str(ROOT / "src"))
import detector as D, evaluation as E
from waste_types import WASTE_TYPES
from baseline import cv_rmse, nmbe

pd.set_option("display.max_columns", 40, "display.width", 220, "display.max_colwidth", 90, "display.float_format", "{:,.2f}".format)
plt.rcParams.update({"figure.dpi": 100, "axes.grid": True, "grid.alpha": .3, "axes.spines.top": False, "axes.spines.right": False})

AL = pd.read_parquet(ROOT / "data/clean/alerts.parquet")
HL = E.heldout_labels_for_diagnostics()
W = HL[HL.severity != "Data quality"].copy()
AH = AL[AL.start >= E.CUT].copy()                       # alerts that belong to the held-out window
FRAMES = {s: D.site_frame(s) for s in D.SITES}
TMAP = {k: set(v["maps_to_labels"]) for k, v in WASTE_TYPES.items()}
print(f"{len(W)} held-out waste labels | {len(AH)} alerts starting on/after {E.CUT.date()} | detector config untouched: {len(D.RULES)} rules, RESID={D.RESID}")

# %% [markdown]
# ## 1 · Strict matching: does each label get an alert *of the right type*?
# Notebook 05 counted a label as detected if **any** alert on that site overlapped it. Here a label counts only if an alert from a rule meant for that label type overlaps it,
# and an alert counts as precise only if it overlaps a label **of a type its rule explains**.

# %%
def typed_overlap(a, lab):
    return bool(((lab.site == a.site) & lab.anomaly_type.isin(TMAP.get(a.rule, set())) & E._overlap(a.start, a.end, lab.start, lab.end)).any())

AH["precise_any"] = [bool(((W.site == a.site) & E._overlap(a.start, a.end, W.start, W.end)).any()) for a in AH.itertuples()]
AH["precise_typed"] = [typed_overlap(a, W) for a in AH.itertuples()]
rows = []
for r in W.itertuples():
    ok_rules = [k for k, v in TMAP.items() if r.anomaly_type in v]
    m = AL[(AL.site == r.site) & AL.rule.isin(ok_rules) & E._overlap(AL.start, AL.end, r.start, r.end)]
    fresh = m[m.alert_time >= r.start - E.SLACK]
    rows.append(dict(id=r.anomaly_id, typ=r.anomaly_type, site=r.site, sev=r.severity, start=r.start, end=r.end, has_rule=bool(ok_rules), detected_typed=len(m) > 0,
                     pre_alerted=len(m) > 0 and len(fresh) == 0, ttd_label_h=(fresh.alert_time.min() - r.start).total_seconds() / 3600 if len(fresh) else np.nan, cost=r.excess_cost_inr))
LT = pd.DataFrame(rows)
hm = LT[LT.sev.isin(["High", "Medium"])]
print(f"alert precision: any-label {AH.precise_any.mean():.1%}  | type-matched {AH.precise_typed.mean():.1%}  ({int((~AH.precise_typed).sum())} of {len(AH)} alerts not type-matched)")
print(f"recall High+Medium: any-alert 96 % (notebook 05) | type-matched {hm.detected_typed.mean():.1%}  ({int(hm.detected_typed.sum())} of {len(hm)})")
display(LT.groupby("typ").agg(n=("id", "size"), has_rule=("has_rule", "max"), detected_typed=("detected_typed", "sum"), pre_alerted=("pre_alerted", "sum"), median_ttd_from_label_start_h=("ttd_label_h", "median")).reset_index())

# %% [markdown]
# ## 2 · The alerts that do not match (precision check)
# Each unmatched alert, with its evidence. If the evidence shows real waste that the key does not list, that is a labelling gap and not a false alarm; if it shows normal operation, it is a real false positive.

# %%
um = AH[~AH.precise_typed].copy()
um["matches_a_label_of_other_type"] = um.precise_any
display(um[["alert_id", "site", "rule", "start", "end", "flagged_h", "cost_inr", "matches_a_label_of_other_type", "evidence"]])
print("unmatched by rule:", um.rule.value_counts().to_dict())

# %% [markdown]
# ## 3 · Why time-to-detect is 3.0 h: the label window starts before the signature does
# For Gurugram's chiller-staging labels (High), measure when the second chiller actually appears at low load (the physical signature: ≥ 2 chillers running and plant load < 130 TR — the
# guide's staging rule, not a tuned value) and compare: label start → signature onset → our alert. If most of the lag sits between label start and onset, the detector is not slow; the label window is wide.

# %%
g = FRAMES["GGN"]
rows = []
for r in LT[(LT.typ == "CHILLER_ON_LOW_LOAD") & (LT.site == "GGN")].itertuples():
    w = g[(g.timestamp >= r.start) & (g.timestamp < r.end)]
    sig = w[(w.n_chillers >= 2) & (w.chiller_load_tr < 130)]
    onset = sig.timestamp.min() if len(sig) else pd.NaT
    m = AL[(AL.site == "GGN") & (AL.rule == "CHILLER_STAGING_LOW_LOAD") & (AL.start <= onset) & (AL.end > onset)] if pd.notna(onset) else AL.iloc[0:0]
    at = m.alert_time.min() if len(m) else pd.NaT
    rows.append(dict(id=r.id, sev=r.sev, label_start=r.start, signature_onset=onset, alert=at, label_to_onset_h=(onset - r.start).total_seconds() / 3600 if pd.notna(onset) else np.nan,
                     onset_to_alert_h=(at - onset).total_seconds() / 3600 if pd.notna(at) else np.nan, label_to_alert_h=(at - r.start).total_seconds() / 3600 if pd.notna(at) else np.nan,
                     low_load_two_chiller_h=len(sig)))
ST = pd.DataFrame(rows); display(ST)
print(f"median label start -> signature onset: {ST.label_to_onset_h.median():.1f} h | signature onset -> our alert: {ST.onset_to_alert_h.median():.1f} h | label start -> alert: {ST.label_to_alert_h.median():.1f} h")
print(f"share within 2 h of the *signature* (onset -> alert): {(ST.onset_to_alert_h <= 2).mean():.0%}; within 2 h of the *label start*: {(ST.label_to_alert_h <= 2).mean():.0%}")

# %% [markdown]
# The same split for power factor (first hour PF < 0.95) and the CHW setpoint (first hour below 7.0 °C):

# %%
rows = []
for r in LT[LT.typ.isin(["POWER_FACTOR_DROP", "CHW_SETPOINT_LOWERED"])].itertuples():
    f = FRAMES[r.site]; w = f[(f.timestamp >= r.start) & (f.timestamp < r.end)]
    if r.typ == "POWER_FACTOR_DROP":
        pf = (w.grid_kwh / w.grid_kvah).where(w.grid_kvah > 0); onset = w.timestamp[pf < D.PF_ALERT].min(); rule = "POWER_FACTOR_DROP"
    else:
        onset = w.timestamp[w.chw_setpoint_c < D.CHW_STD - 1e-9].min(); rule = "CHW_SETPOINT_LOW"
    m = AL[(AL.site == r.site) & (AL.rule == rule) & (AL.start <= onset) & (AL.end > onset)] if pd.notna(onset) else AL.iloc[0:0]
    at = m.alert_time.min() if len(m) else pd.NaT
    rows.append(dict(id=r.id, typ=r.typ, label_start=r.start, onset=onset, alert=at, label_to_onset_h=(onset - r.start).total_seconds() / 3600 if pd.notna(onset) else np.nan,
                     onset_to_alert_h=(at - onset).total_seconds() / 3600 if pd.notna(at) else np.nan))
display(pd.DataFrame(rows))

# %% [markdown]
# **Reading.** Where a physical onset exists, the detector reacts about 1 h after the signature appears (one hour of data is the floor with hourly meters). The owner has confirmed (open question 15) that time to detect runs
# from when the fault first shows in the data, so the onset-based figure (`E.onset_ttd`, notebook 05 section 6) is the headline; label start → first alert is kept as a secondary figure.

# %% [markdown]
# ## 4 · The two label types with no rule
# ### 4a · Contract-demand breach (High labels on hot afternoons)
# What does the main meter show, and how would the guide's own threshold (920 kVA: the EV-throttling level) behave? Hourly max kVA, whole year.

# %%
cd = W[W.anomaly_type == "CONTRACT_DEMAND_BREACH"]
rows = []
for r in cd.itertuples():
    w = g[(g.timestamp >= r.start) & (g.timestamp < r.end)]
    rows.append(dict(id=r.anomaly_id, window=f"{r.start:%d %b %H:%M}-{r.end:%H:%M}", max_kva=w.kva_max_in_hour.max(), hours_over_920=int((w.kva_max_in_hour > 920).sum()), hours_over_1000=int((w.kva_max_in_hour > 1000).sum()),
                     temp_max=w.temp_c.max(), laundry_kw_max=w.laundry_kw.max(), banquet_ahu_kw_max=w.ahu_banquet_kw.max()))
display(pd.DataFrame(rows))
yr = g[g.kva_max_in_hour > 920]
inlab = pd.Series(False, index=yr.index)
for r in cd.itertuples():
    inlab |= (yr.timestamp >= r.start) & (yr.timestamp < r.end)
print(f"whole year: {len(yr)} GGN hours with max kVA > 920 on {yr.date.nunique()} days; {int(inlab.sum())} of those hours lie inside the labelled windows")
print("days with an hour > 920 kVA:", sorted(yr.date.dt.strftime("%d %b").unique()))

# %% [markdown]
# A kVA threshold needs no labels: the guide fixes 920 kVA (EV throttle) and 1,000 kVA (contract demand). It is a **peak-forecast / demand-risk** feature (T7, should-have) rather than a waste signature, and should be built from the brief's thresholds in that step.
#
# ### 4b · EV charger stuck on (Low labels)
# Signature to check: EV sub-meter draw that stays near 6 kW through the night, when the normal profile (tuning window) is near zero.

# %%
sg = pd.read_parquet(ROOT / "data/clean/sub_ggn_hourly.parquet")[["timestamp", "ev_chargers_kw"]]
ev_ = g[["timestamp", "hour"]].merge(sg, on="timestamp")
rows = []
for r in W[W.anomaly_type == "EV_CHARGER_FAULT"].itertuples():
    w = ev_[(ev_.timestamp >= r.start) & (ev_.timestamp < r.end)]
    n = ev_[ev_.timestamp < E.CUT]
    rows.append(dict(id=r.anomaly_id, days=(r.end - r.start).days, window_night_mean_kw=w[w.hour.between(1, 5)].ev_chargers_kw.mean(), window_night_min_kw=w[w.hour.between(1, 5)].ev_chargers_kw.min(),
                     normal_night_mean_kw=n[n.hour.between(1, 5)].ev_chargers_kw.mean(), normal_night_p99_kw=n[n.hour.between(1, 5)].ev_chargers_kw.quantile(.99)))
display(pd.DataFrame(rows))

# %% [markdown]
# If the night minimum in the window sits above the normal 99th percentile, a profile rule on the EV sub-meter would catch it; at ~6 kW on a ~430 kW site the whole-site residual can never see it (its floor is 8 % of load ≈ 34 kW).

# %% [markdown]
# ## 5 · Are the ₹ estimates right? (held-out)
# Our ₹ for the alerts that overlap a label of the right type vs the key's excess cost for those labels.

# %%
rows = []
for typ in sorted(set(W.anomaly_type) & {t for v in TMAP.values() for t in v}):
    L = W[W.anomaly_type == typ]; rules = [k for k, v in TMAP.items() if typ in v]
    A = AH[AH.rule.isin(rules)]
    hit = [a for a in A.itertuples() if ((L.site == a.site) & E._overlap(a.start, a.end, L.start, L.end)).any()]
    rows.append(dict(type=typ, key_inr=L.excess_cost_inr.sum(), our_inr=sum(a.cost_inr for a in hit), key_kwh=L.excess_kwh.sum(), our_kwh=sum(a.excess_kwh for a in hit)))
C = pd.DataFrame(rows); C["ratio_inr"] = C.our_inr / C.key_inr.replace(0, np.nan); display(C)
print("Alerts spanning several labels / labels spanning several alerts make ratios indicative, not exact.")

# %% [markdown]
# ## 6 · Is the baseline accurate in the held-out months?
# Out-of-fold ensemble predictions (notebook 03), April–September 2026 only, valid hours.

# %%
oof = pd.read_parquet(ROOT / "data/clean/baseline_oof.parquet")
oof = oof[(oof.timestamp >= E.CUT) & oof.valid]
rows = []
for s, d in oof.groupby("site"):
    m = d.groupby(d.timestamp.dt.to_period("M")).agg(a=("total_kwh", "mean"), p=("pred_ens", "mean"))
    rows.append(dict(site=s, hourly_CVRMSE=cv_rmse(d.total_kwh, d.pred_ens), hourly_NMBE=nmbe(d.total_kwh, d.pred_ens), monthly_CVRMSE=cv_rmse(m.a, m.p), monthly_NMBE=nmbe(m.a, m.p)))
display(pd.DataFrame(rows))

# %% [markdown]
# ## 7 · T2 follow-up: which event-window alerts were real?
# Notebook 05 found 14 of 132 big events with an alert starting in the event window. With the labels, classify each as a confirmed anomaly or not.

# %%
ev = pd.read_parquet(ROOT / "data/clean/events.parquet")
ALL = pd.concat([E.tuning_labels(), HL])
rows = []
for s in D.SITES:
    for r in ev[(ev.site == s) & (ev.guests > 300)].itertuples():
        t0 = pd.Timestamp(r.date) + pd.Timedelta(hours=int(r.start_time[:2]) - 1)
        t1 = pd.Timestamp(r.date) + (pd.Timedelta(days=1, hours=2) if r.ends_after_midnight else pd.Timedelta(hours=int(r.end_time[:2]) + 1))
        for a in AL[(AL.site == s) & (AL.start >= t0) & (AL.start < t1)].itertuples():
            lab = ALL[(ALL.site == s) & E._overlap(a.start, a.end, ALL.start, ALL.end)]
            rows.append(dict(site=s, event_date=r.date.date(), guests=r.guests, rule=a.rule, alert_start=a.start, label_overlap=",".join(sorted(set(lab.anomaly_type))) or "NONE"))
T2 = pd.DataFrame(rows); display(T2)
print(f"event-window alerts: {len(T2)} | overlapping a labelled anomaly: {(T2.label_overlap != 'NONE').sum()} | not matching any label: {(T2.label_overlap == 'NONE').sum()}")

# %% [markdown]
# ## 8 · What this says, and a v2 proposal (not applied)
# Computed summary, then proposals. Nothing below has been implemented in the detector.

# %%
print(f"1. Strict precision: any-label {AH.precise_any.mean():.0%}, type-matched {AH.precise_typed.mean():.0%}. Strict recall (High+Medium, type-matched): {hm.detected_typed.mean():.0%}.")
print(f"2. Time to detect: official (label start -> alert) is a miss; from the physical signature onset the staging alerts come {ST.onset_to_alert_h.median():.1f} h after onset, "
      f"because label windows open ~{ST.label_to_onset_h.median():.1f} h before the second chiller appears at low load.")
print("3. Two label types have no rule: demand breach (a kVA threshold from the brief: belongs in the peak / demand forecast step) and EV charger stuck-on (see section 4b for whether a sub-meter profile rule could see it).")
print("\nProposals for a v2 (all post-hoc; v2 scores must be reported as tuned with held-out exposure):")
print(" a. Add a demand-risk alert at 920 / 1,000 kVA from the guide's thresholds, in the peak-forecast step.")
print(" b. Add an EV-charger idle-draw profile rule only if section 4b shows the window clears the tuning-window normal.")
print(" c. Leave the staging rule as is if section 3 confirms its lag is a label-window effect.")
print(" d. Ask the problem owner how the evaluator defines the label window / time to detect.")
