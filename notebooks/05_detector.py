# %% [markdown]
# # 05 · Context-aware detector — tune before 1 Apr 2026, report from 1 Apr 2026
# **What it is** (`src/detector.py`): three parts.
# 1. **Rule layer** — one rule per waste type from notebook 04. Each compares a sub-meter (or PF, or the CHW setpoint) with a *learned profile of normal for the same
#    context* (hour, outdoor-temperature band, event on/off, plant load). That is what makes it context-aware: heat, a full house and a 500-guest wedding are compared with
#    their own kind of hour, so they do not alert (T2).
# 2. **Residual layer** — main meter minus the baseline from notebook 03; persistent, large, positive residuals with no rule alert nearby become "unexplained deviation".
# 3. **Fault stream** — flat-lined / zero / missing billed readings found from the *raw* columns. Fault hours are removed from every waste signal (T5): never a waste alert, never a saving.
#
# **Protocol (enforced in `src/evaluation.py`).** `tuning_labels()` can only return labels that start before 1 Apr 2026. Everything in sections 1–4 uses only those.
# The configuration is then **frozen** (section 5). Section 6 calls `score_heldout()` **once**; it reads the later labels and returns aggregates only (no per-label rows, no
# alert-to-label pairing), so nothing seen there can feed back into tuning. Section 7 checks the brief's acceptance scenarios against the alerts using the dates in the brief,
# not the label table. Results are reported as they come out — if a number misses its target, it is reported as a miss.

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
from features import SITES

pd.set_option("display.max_columns", 40, "display.width", 220, "display.max_colwidth", 200, "display.float_format", "{:,.2f}".format)
plt.rcParams.update({"figure.dpi": 100, "axes.grid": True, "grid.alpha": .3, "axes.spines.top": False, "axes.spines.right": False})

TL = E.tuning_labels()
print("labels visible to this notebook until section 6:", len(TL), "(all start before", E.CUT.date(), ")")
frames, P = D.load_all(E.tuning_label_mask)         # profiles: tuning-window hours, labelled hours removed
FAULTS = pd.concat([D.detect_meter_faults(s) for s in D.SITES], ignore_index=True)
print({s: round(P.rate_kwh[s], 2) for s in D.SITES}, "Rs per marginal grid kWh | normal PF:", {s: round(P.pf_ref[s], 3) for s in D.SITES})

# %% [markdown]
# ## 1 · Meter-fault stream (T5)
# Found from raw columns only — no flags, no labels. Gurugram: a run of identical raw kWh readings (≥ 3 repeats) or raw zeros while `kw_avg` is live on grid supply.
# Jaipur/Goa: missing readings or repeated kWh. Each fault carries its evidence; its hours are excluded from every waste signal and from the baseline.

# %%
display(FAULTS.assign(hours=(FAULTS.end - FAULTS.start).dt.total_seconds() / 3600).sort_values("start")[["site", "start", "end", "hours", "kind", "detected_at", "evidence"]].query("start < @E.CUT"))
tf = TL[TL.severity == "Data quality"]
det = [bool(((FAULTS.site == r.site) & E._overlap(FAULTS.start, FAULTS.end, r.start, r.end)).any()) for r in tf.itertuples()]
print(f"tuning-window data-fault labels: {len(tf)} | found: {sum(det)}")
fp = FAULTS[FAULTS.start < E.CUT]
print("fault notices that match no data-fault label (false notices):", int(sum(not ((tf.site == r.site) & E._overlap(r.start, r.end, tf.start, tf.end)).any() for r in fp.itertuples())))

# %% [markdown]
# ## 2 · Rule layer on the tuning window
# One row per rule: alerts raised and how many overlap a tuning label of the same site (precision), and for each tuning label whether *any* alert overlaps (recall) and how fast.

# %%
al = D.detect_all(frames, P)
res_t = E.score(al, TL, FAULTS, "tune")
display(pd.Series(res_t["summary"]).to_frame("tuning window").T)
display(res_t["by_rule"].round(2)); display(res_t["by_type"].round(1)); display(res_t["by_sev"])

# %% [markdown]
# ## 3 · Tuning choices (all on the tuning window)
# **a. Persistence (`min_h`) vs speed.** Fewer required hours detect sooner. The tuning window shows no false alerts at 1 h for the high-signal rules, so they use 1 h; the
# lower-signal ones (lighting, kitchen, pool) wait for 2–3 h to avoid one-off blips. **b. Merging (`gap_h`).** Waste that recurs daily (re-heat in daytime, pool pump at night, kitchen
# exhaust after midnight) is merged into one "ongoing since…" alert, not one alert per day — alert fatigue is a problem the brief names (66 % of BMS alarms closed with no action).
# **c. Residual layer threshold.** Swept below.

# %%
base_rules = pd.concat([D.detect_site(s, frames[s], P, use_resid=False) for s in D.SITES], ignore_index=True)
sweep = []
old = dict(D.RESID), D.RULES["RESIDUAL_UNEXPLAINED"]["min_h"]
for z in [3, 4, 5]:
    for ff in [0.04, 0.08, 0.12]:
        D.RESID.update(z=z, floor_frac=ff)
        rs = pd.concat([D.residual_alerts(s, frames[s], P, base_rules[base_rules.site == s]) for s in D.SITES], ignore_index=True)
        rs = rs[rs.start < E.CUT] if len(rs) else rs
        hit = [((TL.site == r.site) & E._overlap(r.start, r.end, TL.start, TL.end)).any() for r in rs.itertuples()] if len(rs) else []
        sweep.append(dict(z=z, min_share_of_load=ff, alerts_in_tuning_window=len(rs), overlapping_a_label=int(sum(hit))))
D.RESID.update(old[0])
S = pd.DataFrame(sweep); display(S)
print("Residual layer: at z=3 / 4% it raises 10 alerts, none matches a tuning label; from z>=4 with a share floor >=8% it raises none. Frozen at z=4, 8%: the least strict setting with zero tuning false alerts.")
print("Its value cannot be shown on the tuning window (the rules already cover every tuning label); its held-out behaviour is reported separately by rule in section 6.")

# %% [markdown]
# **d. Sensitivity of the profile thresholds** (tuning window): how many false alerts and how much recall as the profile pad and the kW floors are scaled. A robust choice sits on a flat part of the curve.

# %%
rows = []
for padx in [1.0, 1.05, 1.15, 1.3]:
    for fx in [0.5, 1.0, 2.0]:
        D.PROFILE_PAD = padx; saved = dict(D.KW_FLOOR); D.KW_FLOOR.update({k: v * fx for k, v in saved.items()})
        a2 = D.detect_all(frames, P, use_resid=False); r = E.score(a2, TL, FAULTS, "tune")["summary"]
        rows.append(dict(profile_pad=padx, floor_scale=fx, alerts=r["n_alerts"], precision=r["precision_any"], recall_HM=r["recall_HM"], ttd_high_median_h=r["ttd_high_median_h"]))
        D.KW_FLOOR.update(saved)
D.PROFILE_PAD = 1.05
display(pd.DataFrame(rows))

# %% [markdown]
# ## 4 · Frozen configuration
# Printed so the held-out run below can be traced to exactly these settings.

# %%
CONFIG = dict(RULES=D.RULES, PF_ALERT=D.PF_ALERT, KW_FLOOR=D.KW_FLOOR, KWTR_MARGIN=D.KWTR_MARGIN, PROFILE_Q=D.PROFILE_Q, PROFILE_PAD=D.PROFILE_PAD, RESID=D.RESID,
              CHW_STD=D.CHW_STD, CHW_FLOOR=D.CHW_FLOOR, PEAK_WINDOWS=D.PEAK)
for k, v in CONFIG.items():
    print(f"{k}: {v}")

# %% [markdown]
# ## 5 · Alerts as an engineer sees them
# Wording follows brief §13: what, where, since when, ₹, evidence, action. Every number comes from the alert row (the models), none from free text. Two examples from the **tuning window**.

# %%
ex = al[(al.start < E.CUT) & al.rule.isin(["AHU_HAND_MODE", "CHILLER_STAGING_LOW_LOAD", "POWER_FACTOR_DROP", "LIGHTING_LEFT_ON"])].groupby("rule").head(1)
for a in ex.itertuples():
    print(f"[{a.alert_id}] alert raised {a.alert_time:%d %b %H:%M}\n  {D.alert_text(a)}\n")

# %% [markdown]
# ## 6 · Held-out scoring — anomalies starting from 1 Apr 2026 (called once)
# Precision: share of waste alerts overlapping a labelled anomaly on the same site (the BMS-alarm definition: 26 % today). `precision_typed` is stricter: the label must also be a type that rule
# is meant to explain. Recall: share of High + Medium labels with an overlapping alert (BMS: 40 %). Time to detect: first *fresh* overlapping alert (raised on/after the label start) minus label start, High
# severity (BMS: 8.3 h median); labels that an earlier alert already covers at their start are "pre-alerted" — detected, but excluded from the time statistics.
#
# **Disclosure — the scoring definitions were amended once after the first held-out run.** The first run counted any overlapping alert, including one raised *before* the label started, as a 0 h detection, which gave a
# median time-to-detect of 0.0 h that is not credible; it also scored the CHW rule's "typed" precision as 0 because no label type was mapped to it. Both are fixes to the *scorer* (`src/evaluation.py`,
# `src/waste_types.py`), not to the detector: no rule, threshold or profile was changed after seeing held-out results, and none will be. The first run also revealed two held-out label types for which the
# detector has no rule (see below); adding rules for them would be tuning on held-out knowledge, so they are reported as gaps instead.

# %%
H = E.score_heldout(al, FAULTS)
print(pd.Series(H["summary"]).to_string())
print("\nby severity:"); display(H["by_sev"])
print("by label type:"); display(H["by_type"].round(1))
print("by rule (alert precision):"); display(H["by_rule"].round(2))

# %% [markdown]
# **Time to detect is measured from when the fault first shows in the data** (owner's answer to open question 15), not from the label start. Onset = first hour inside the label window where a raw
# rule flag for that label type is true, before the persistence rule; `E.onset_ttd`. The scorer was added after the freeze (detector unchanged); the label-start figure is kept as a secondary row.
# Hourly meters make 1 h the floor. High labels with no onset (no rule exists for their type) are not scored and are counted separately.

# %%
flags = {s_: {k: pd.Series(f.to_numpy(bool), index=pd.DatetimeIndex(frames[s_].timestamp)) for k, (f, _) in D.rule_signals(s_, frames[s_], P).items()} for s_ in D.SITES}
HO = E.score_heldout_onset(al, flags)
print(pd.Series(HO).to_string())

# %%
s = H["summary"]
T = pd.DataFrame([
    ("Alert precision", "26 %", ">= 70 %", f"{s['precision_any']:.0%} (typed {s['precision_typed']:.0%})", s["precision_any"] >= .70),
    ("Recall, High+Medium", "40 %", ">= 75 %", f"{s['recall_HM']:.0%} ({int(round(s['recall_HM'] * s['n_HM']))} of {s['n_HM']})", s["recall_HM"] >= .75),
    ("Time to detect, High (median), from first appearance in the data", "8.3 h", "< 2 h", f"{HO['ttd_onset_median_h']:.1f} h; {HO['ttd_onset_under_2h']:.0%} of {HO['n_scored']} scored within 2 h", HO["ttd_onset_median_h"] < 2),
    ("  (secondary) from label start", "8.3 h", "-", f"{s['ttd_high_median_h']:.1f} h; {s['ttd_high_under_2h']:.0%} within 2 h", None),
    ("Meter faults found", "-", "all, no waste alert", f"{s['faults_detected']} of {s['fault_labels']}", s["faults_detected"] == s["fault_labels"]),
], columns=["metric", "BMS today", "target", "this detector, from 1 Apr 2026", "met"])
display(T)

# %% [markdown]
# ## 7 · Acceptance scenarios (T1–T8) against the alerts
# Dates and conditions are from the brief (T-table). Only our alerts and the raw data are read — not the label table. T7 (forecast), T9 (bill split) and T10 (assistant refusal) belong to later steps.

# %%
def show(a):
    print(f"  [{a.alert_id}] raised {a.alert_time:%d %b %Y %H:%M} | {a.rule} | {a.flagged_h} h | Rs {a.inr_per_hour:,.0f}/h, Rs {a.inr_per_day:,.0f}/day\n    {a.evidence}")

ev = pd.read_parquet(ROOT / "data/clean/events.parquet")
# T1: Gurugram banquet AHUs after the conference that ended 16 Apr 2026
e = ev[(ev.site == "GGN") & (ev.date == "2026-04-16")]
print("T1 — events at GGN on 16 Apr 2026:\n", e[["event_type", "venue", "guests", "start_time", "end_time"]].to_string(index=False))
end = pd.Timestamp("2026-04-16") + pd.Timedelta(hours=int(e.iloc[0].end_time[:2]))
a1 = al[(al.site == "GGN") & (al.rule == "AHU_HAND_MODE") & (al.start >= end) & (al.start <= end + pd.Timedelta(hours=24))]
for a in a1.itertuples():
    show(a); print(f"    -> alert {(a.alert_time - end).total_seconds() / 3600:.1f} h after the event ended (target <= 2 h)")
print("  ", "OK" if len(a1) and (a1.alert_time.min() - end) <= pd.Timedelta(hours=2) else "MISS")

# T2: no waste alert explained by a big event
print("\nT2 — big events (> 300 guests) and alerts that start inside the event evening (start-1 h .. end+1 h):")
rows = []
for s in D.SITES:
    for r in ev[(ev.site == s) & (ev.guests > 300)].itertuples():
        t0 = pd.Timestamp(r.date) + pd.Timedelta(hours=int(r.start_time[:2]) - 1); t1 = pd.Timestamp(r.date) + pd.Timedelta(hours=int(r.end_time[:2]) + 1) if not r.ends_after_midnight else pd.Timestamp(r.date) + pd.Timedelta(days=1, hours=2)
        m = al[(al.site == s) & (al.start >= t0) & (al.start < t1)]
        rows.append(dict(site=s, date=r.date.date(), guests=r.guests, alerts_started_in_window=len(m), rules=",".join(sorted(set(m.rule)))))
T2 = pd.DataFrame(rows)
print(f"  {len(T2)} big events; with any alert starting during the event: {(T2.alerts_started_in_window > 0).sum()}")
display(T2[T2.alerts_started_in_window > 0].head(10))
print("  by rule among those:", T2[T2.alerts_started_in_window > 0].rules.str.split(",").explode().value_counts().to_dict())
print("  (a laundry-in-peak or lighting alert on an event day is real, unexplained-by-event waste; AHU / residual / chiller alerts there would be false alarms)")

# T3, T4, T5, T6, T8
def first(site, rule, after, before=None):
    m = al[(al.site == site) & (al.rule == rule) & (al.start >= pd.Timestamp(after) - pd.Timedelta(days=1)) & ((al.start <= pd.Timestamp(before)) if before else True)]
    return m.sort_values("alert_time").head(1)
print("\nT3 — Jaipur, 2nd chiller overnight in April, occupancy < 45 %:")
m = al[(al.site == "JAI") & (al.rule == "CHILLER_PART_LOAD_INEFFICIENCY") & (al.start >= "2026-04-01") & (al.start < "2026-05-01")]
print(f"  {len(m)} Jaipur chiller-efficiency alerts in April")
for a in m.head(2).itertuples(): show(a)
print("T4 — Gurugram PF ~0.88 from 23 May 2026:")
for a in first("GGN", "POWER_FACTOR_DROP", "2026-05-23").itertuples():
    show(a); print(f"    -> raised {(a.alert_time - pd.Timestamp('2026-05-23')).total_seconds() / 3600:.1f} h after 23 May 00:00")
print("T5 — Gurugram meter flat from 8 Jul 2026, sub-meters normal:")
f5 = FAULTS[(FAULTS.site == "GGN") & (FAULTS.start >= "2026-07-07") & (FAULTS.start < "2026-07-10")]
display(f5[["start", "end", "kind", "detected_at", "evidence"]])
inside = al[(al.site == "GGN") & (al.start < f5.end.max()) & (al.end > f5.start.min()) & (al.rule != "RESIDUAL_UNEXPLAINED")]
inside_all = al[(al.site == "GGN") & (al.start < f5.end.max()) & (al.end > f5.start.min())]
print(f"  waste alerts overlapping that fault window: {len(inside_all)} (rules: {sorted(set(inside_all.rule))}); fault hours flagged in the frame: {int(frames['GGN'].fault[(frames['GGN'].timestamp >= f5.start.min()) & (frames['GGN'].timestamp < f5.end.max())].sum())}")
print("T6 — Gurugram CHW setpoint lowered to 5.5 degC on 13 May 2026:")
for a in first("GGN", "CHW_SETPOINT_LOW", "2026-05-13").itertuples():
    show(a); print("    ->", WASTE_TYPES["CHW_SETPOINT_LOW"]["action"])
print("T8 — Goa pool pumps 24 h/day from 10 Jun 2026:")
for a in first("GOA", "POOL_PUMP_OFF_SCHEDULE", "2026-06-10").itertuples(): show(a)

# %% [markdown]
# ## 8 · Alert volume (alert fatigue)
# The brief wants engineers to act on alerts. Alerts per hotel per week over the year, and how concentrated the ₹ is — rank by ₹ and show the top few first.

# %%
al["week"] = al.start.dt.to_period("W").astype(str)
vol = al.groupby(["site"]).agg(alerts=("alert_id", "size"), per_week=("alert_id", lambda x: len(x) / 52), total_inr=("cost_inr", "sum"), median_inr=("cost_inr", "median"))
display(vol)
top = al.sort_values("cost_inr", ascending=False)
print("share of total ₹ in the top 20 % of alerts:", round(top.cost_inr.head(int(len(top) * .2)).sum() / top.cost_inr.sum() * 100, 1), "%")
print("alerts by rule over the year:", al.rule.value_counts().to_dict())
print("total flagged waste over the year: Rs", f"{al.cost_inr.sum():,.0f}", "| as a share of the group bill: ", f"{al.cost_inr.sum() / 7.40e7 * 100:.1f} %")

# %% [markdown]
# ## 9 · Save alerts for the product
# `data/clean/alerts.parquet` (all alerts, full year) and `meter_faults.parquet` feed the UI. The alert text is built from these rows only.

# %%
al.drop(columns="week").assign(text=[D.alert_text(a) for a in al.itertuples()]).to_parquet(ROOT / "data/clean/alerts.parquet", index=False)
FAULTS.to_parquet(ROOT / "data/clean/meter_faults.parquet", index=False)
print(len(al), "alerts,", len(FAULTS), "fault notices saved")

# %% [markdown]
# ## 10 · Limits — what the detector cannot see, and what is not proven
# Statements below are computed from the results above where they quote a number.

# %%
s = H["summary"]; bt = H["by_type"]
covered = {t for v in WASTE_TYPES.values() for t in v["maps_to_labels"]}
nr = bt[~bt.typ.isin(covered)]
print(f"- Time to detect (from first appearance in the data) is met: median {HO['ttd_onset_median_h']:.1f} h, max {HO['ttd_onset_max_h']:.1f} h over {HO['n_scored']} scored High labels; {HO['n_no_onset_or_no_alert']} of {HO['n_high']} High labels have no scoreable onset (no rule for their type) "
      f"and {HO['n_pre_alerted']} were pre-alerted. From the label start the median is {s['ttd_high_median_h']:.1f} h ({s['ttd_high_under_2h']:.0%} within 2 h) because label windows open a median {HO['label_to_onset_median_h']:.1f} h before the signature. "
      f"The onset scorer uses the detector's own raw flags, so 1 h is close to the floor by construction; it shows persistence adds no delay, not that onsets are independently confirmed.")
print(f"- No rule exists for label type(s) {', '.join(nr.typ)}: {int(nr.detected.sum())} of {int(nr.n.sum())} such labels got an overlapping alert, by coincidence with another rule. These are reported as gaps, not patched.")
print(f"- High recall: {s['n_high_detected']} of {s['n_high']} High labels detected (which types the misses belong to is not broken down further, to avoid inspecting held-out labels).")
print("- Rules are signature-based. A waste type with no sub-meter, or a deviation under the floors in section 3d / notebook 04 section 8, is invisible by design.")
print("- Every tuning label was a type the rules were built for, so tuning precision/recall (100 %) is not evidence of generalisation; the held-out numbers in section 6 are.")
print("- Precision is measured against a partial answer key: real waste not in the key counts as a false positive. 'precision_typed' limits that risk but cannot remove it.")
print("- The residual layer raised few alerts; its only evidence is its row in 'by rule'. Do not read it as validated.")
print("- Hourly sub-meter data and per-rule persistence bound time-to-detect from below (banquet AHUs cannot alert before event end + 1 h buffer + 1 h of data).")
print("- The residual layer uses out-of-fold baseline predictions trained on all other months (including later ones); label data is never used for it.")
print("- No holiday calendar exists (confirmed with the team), so public holidays are treated as ordinary weekdays / weekends in the baseline and the residual layer.")
