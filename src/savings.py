"""Savings: (1) a sized plan of safe measures split energy / ToD / demand, (2) IPMVP Option C verification statistics.

Why both: the brief targets 8–12 % of the bill as *identified* savings, and finance only accepts savings verified against an adjusted baseline.
(1) sizes each measure from the year's metered data with stated assumptions and a safety check; nothing is claimed as achieved.
(2) gives the M&V engine: the full-year baseline (weather, occupancy, events, day type) is the Option C adjustment model; this module reports its
    fit and the minimum savings it can verify (ASHRAE Guideline 14 fractional savings uncertainty). Verified savings = adjusted baseline − actual,
    computed with `verify()` once a measure has a go-live date and a reporting period. The data year contains no implemented measure, so no
    verified saving is reported - that would be invented.
Data faults are never savings (T5): fault hours are excluded everywhere via `valid`.
Two totals, always reported together: operations (every row except Capital) and with capital (+ the one capital item, pump VFDs).
On the live year (SAFFRON_DATA=data/live) one more row is added: the daily operating plan's demand saving in months without a penalty,
the only part of the plan not already counted by the alert and breach rows (tools/plan_savings_live.py).
Night base load (audit): channels whose 00-05 h draw stays above their own good nights, night after night (tools/night_baseload.py). The
claim always comes from the ORIGINAL year's audit (the live year is a check on synthetic data); public-lighting kWh only beyond the night-lighting
row, so nothing is counted twice. Rows appear only for channels with a clear repeatable excess.
"""
import json
import math
import os
import subprocess
import sys
from functools import lru_cache

import numpy as np
import pandas as pd
from scipy import stats

from bills import TOD, _in_window, tariff
from features import APP, CLEAN, DEFAULT_CLEAN, ROOT, SITES

PF_TARGET = 0.99
NIGHT_LIGHT_CUT = 0.30          # assumption: corridor / facade / landscape lighting dimmed or sensor-switched after midnight
VFD_SHARE = 0.30                # capital: typical saving converting constant-speed pumps to variable flow
CAPITAL = "Capital"
NIGHT = "Night base load (audit)"
LIVE_YEAR = CLEAN != DEFAULT_CLEAN


@lru_cache(maxsize=1)
def _chw_per_degc() -> float:
    """Lowest metered chiller penalty per degC (5.5 vs 7.0 degC, per load band; recalibration.py) - the conservative choice.
    Always fitted on the original year: the fit needs its tuning window (before 1 Apr 2026), which the live year does not have (on the live
    frame it came back empty and the row was NaN). Like every other model, the plant's measured penalty is frozen, never refitted."""
    import baseline
    import detector
    import evaluation
    import features
    import recalibration as RC
    mods = (features, baseline, detector, evaluation, RC)
    cur = [m.CLEAN for m in mods]
    for m in mods:
        m.CLEAN = DEFAULT_CLEAN
    try:
        pen = RC.fit(RC._frame())["chw_penalty"]
    finally:
        for m, c in zip(mods, cur):
            m.CLEAN = c
    return float(pen.min() / 1.5)


@lru_cache(maxsize=1)
def night_audit() -> dict:
    """The night base-load audit on the original year (the claim) and, if present, the live year (a check)."""
    sys.path.insert(0, str(ROOT / "tools"))
    import night_baseload as NB
    return dict(orig=NB.audit(NB.ORIG), live=NB.audit(NB.LIVE) if (NB.LIVE / "sub_ggn_hourly.parquet").exists() else None)


@lru_cache(maxsize=1)
def _plan_live():
    """Live year only: (lever table, monthly demand table, increment) of the simulated daily operating plan."""
    sys.path.insert(0, str(ROOT / "tools"))
    import plan_savings_live as PSL
    levers, mon = PSL.run()
    return levers, mon, PSL.plan_increment(mon)


SHIFT_SHARE = {"laundry_kw": 1.0, "water_heating_kw": 0.7, "ev_chargers_kw": 0.5}   # share of peak-window kWh assumed movable


def _frame(site):
    return pd.read_parquet(APP / f"frame_{site}.parquet")


def _rates(site):
    t = tariff(site)
    b = pd.read_parquet(CLEAN / "monthly_bills.parquet").query("site == @site")
    pf = b.grid_kwh.sum() / b.grid_kvah.sum()
    per_kvah = t["energy"] * (1 + t["muni"]) + t["fsa"] + t["duty"]
    return t, pf, per_kvah / pf


def plan() -> pd.DataFrame:
    cards = pd.read_parquet(APP / "cards.parquet")
    rows = []
    for s in ["GGN", "JAI", "GOA"]:
        t, pf, rkwh = _rates(s)
        c = cards[cards.site == s]
        # 1. Fix detected waste (alerts) - energy, excluding laundry (ToD) and demand (below)
        e = c[~c.rule.isin(["LAUNDRY_IN_PEAK", "DEMAND_NEAR_CONTRACT", "POWER_FACTOR_DROP"])]
        rows.append(dict(site=s, measure="Act on detected waste alerts (staging, hand-mode AHUs, re-heat, lighting, pumps, setpoints, exhaust)",
                         category="Energy", inr=e.cost_inr.sum(), basis=f"{len(e)} alerts over the year; ₹ from the detector, staging and CHW recalibrated to metered kW/TR (hand-mode AHU is a lower bound)",
                         safety="Each fix is approved by a person; kitchen extract fans are linked to kitchen hours, never switched off automatically", confidence="High"))
        pfa = c[c.rule == "POWER_FACTOR_DROP"]
        if len(pfa):
            rows.append(dict(site=s, measure="Keep PF ≥ 0.97: repair APFC steps within hours (PF alert)", category="Energy", inr=pfa.cost_inr.sum(),
                             basis=f"{len(pfa)} PF-drop episodes; excess kVAh × energy+FSA+duty", safety="No effect on guests or comfort", confidence="High"))
        # 2. Flexible loads out of the peak window into off-peak
        d = _frame(s)
        h = d.timestamp.dt.hour
        pk = _in_window(h, TOD[s]["peak"])
        spread = t["peak"] - t["off"]              # surcharge avoided + rebate earned per kVAh moved
        cols = ["laundry_kw", "water_heating_kw", "ev_chargers_kw"] if s == "GGN" else ["laundry_kw"]
        moved = sum(d.loc[pk, col].sum() * SHIFT_SHARE[col] for col in cols if col in d)
        rows.append(dict(site=s, measure="Shift flexible loads (" + ", ".join(x.replace("_kw", "").replace("_", " ") for x in cols) + ") from peak to off-peak window",
                         category="ToD", inr=moved / pf * spread,
                         basis=f"{moved:,.0f} kWh/yr movable (shares {', '.join(f'{k[:-3]} {v:.0%}' for k, v in SHIFT_SHARE.items() if k in cols)}) × ₹{spread:.2f}/kVAh",
                         safety="Hot water still reaches 60 °C once a day for hygiene; laundry timing is the laundry manager's call", confidence="Medium"))
        # 3. Demand
        b = pd.read_parquet(CLEAN / "monthly_bills.parquet").query("site == @s")
        if b.excess_demand_penalty_inr.sum() > 0:
            rows.append(dict(site=s, measure="Avoid contract-demand breaches: day-ahead stacking watch + shift plan + EV throttle above 920 kVA",
                             category="Demand", inr=b.excess_demand_penalty_inr.sum(), basis="Excess-demand penalties actually billed this year",
                             safety="Chillers, kitchens, lifts and safety systems are never cut", confidence="Medium"))
        max_md = b.recorded_md_kva.max()
        new_cd = math.ceil(max_md * 1.15 / 10) * 10
        if new_cd < t["cd"]:
            def demand_bill(cd):
                bd = np.maximum(b.recorded_md_kva, 0.75 * cd)
                return (np.minimum(bd, cd) * t["demand"] + np.maximum(b.recorded_md_kva - cd, 0) * t["penalty"]).sum() * (1 + t["muni"])
            rows.append(dict(site=s, measure=f"Right-size contract demand {t['cd']:,.0f} → {new_cd:,} kVA (max MD this year {max_md:,.0f} kVA, +15 % headroom)",
                             category="Demand", inr=demand_bill(t["cd"]) - demand_bill(new_cd),
                             basis=f"MD below the 75 % floor ({0.75 * t['cd']:,.0f} kVA) in {(b.recorded_md_kva < 0.75 * t['cd']).sum()} of 12 months - paying for unused demand",
                             safety="An application to the utility, no equipment change; check expansion plans first", confidence="Medium"))
        # 4. CHW reset to 8 degC in cool, light-load hours (guide allows)
        if s == "GGN":
            ok = (d.temp_c < 24) & (d.chw_setpoint_c == 7.0) & d.chiller_load_tr.between(1, 280) & d.valid
            per_c = _chw_per_degc()
            kwh = d.chillers_kw[ok].sum() * per_c
            rows.append(dict(site=s, measure="CHW reset 7 → 8 °C when outdoor < 24 °C and plant load is light", category="Energy", inr=kwh * rkwh,
                             basis=f"{ok.sum():,} eligible hours, {d.chillers_kw[ok].sum():,.0f} chiller kWh × {per_c * 100:.1f} %/°C (lowest metered penalty per °C)",
                             safety="Only on cool, quiet days; never below 6.5 °C; watch for humidity complaints", confidence="Medium"))
        # 5. PF up to 0.99: energy, FSA and duty are billed per kVAh, so every 0.01 of PF is ~1 % of the energy line
        from bills import meter_quantities
        q = meter_quantities(s, raw=False).sum()                     # meter, not bills: the Goa July bill's kVAh is an estimate
        pf_now = q.grid_kwh / q.grid_kvah
        t_ = tariff(s)
        per_kvah = t_["energy"] * (1 + t_["muni"]) + t_["fsa"] + t_["duty"]
        cut = q.grid_kvah - q.grid_kwh / PF_TARGET
        already = c[c.rule == "POWER_FACTOR_DROP"].cost_inr.sum()   # repairing the drop episodes is counted above
        rows.append(dict(site=s, measure=f"Hold PF at {PF_TARGET}: add / retune APFC steps (average PF {pf_now:.3f} today)", category="Energy",
                         inr=max(cut * per_kvah - already, 0.0),
                         basis=f"{cut:,.0f} kVAh/yr less at the same kWh × ₹{per_kvah:.2f}/kVAh, minus ₹{already:,.0f} already counted for PF-drop repairs",
                         safety="No effect on guests or comfort; the panel supplier sizes the upgrade so it does not over-correct", confidence="High"))
        # 6. Night public lighting: 00-05 h draw is above daytime at every hotel
        lt = d[d.timestamp.dt.hour.between(0, 5)].lighting_kw.sum()
        rows.append(dict(site=s, measure=f"Dim / sensor-switch public lighting 00:00–06:00 by {NIGHT_LIGHT_CUT:.0%} (keep egress and security lighting)",
                         category="Energy", inr=lt * NIGHT_LIGHT_CUT * rkwh,
                         basis=f"{lt:,.0f} kWh/yr of lighting between 00:00 and 06:00 (night mean {d[d.timestamp.dt.hour.between(0, 5)].lighting_kw.mean():.0f} kW vs "
                               f"{d[d.timestamp.dt.hour.between(6, 17)].lighting_kw.mean():.0f} kW by day) × {NIGHT_LIGHT_CUT:.0%} assumed",
                         safety="Emergency and exit lighting untouched; security walks the areas before levels are set", confidence="Low (assumed share)"))
        # 7. Night base load (audit): clear, repeatable excess over the channel's own good nights (original-year audit)
        night_lt_kwh = lt * NIGHT_LIGHT_CUT * d[d.timestamp.dt.hour.between(0, 4)].lighting_kw.sum() / max(lt, 1e-9)   # the lighting row's 00-05 h kWh
        a = night_audit()["orig"][s]
        for r in a["table"][a["table"].kwh > 0].itertuples():
            kwh = r.kwh - (night_lt_kwh if r.channel in ("lighting_public_kw", "lighting_kw") else 0.0)
            if kwh <= 0:
                continue
            rows.append(dict(site=s, measure=f"Night base load: {r.label} 00:00–05:00 back to its good-night level ({r.good_kw:.1f} kW)", category=NIGHT,
                             inr=kwh * a["rate"],
                             basis=f"Median night {r.excess_kw:.2f} kW above the 10th–20th percentile of similar nights (occupancy, temperature), on "
                                   f"{r.share:.0%} of nights and persisting night to night (r = {r.ac1:.2f}); {kwh:,.0f} kWh/yr at the off-peak price",
                             safety="Recommend only; a night walk-round confirms the cause first. Guest rooms, lifts, safety systems and chilled water "
                                    "for occupied rooms are never touched", confidence="Medium (needs a night walk-round to confirm)"))
        if s == "GGN":
            sub = pd.read_parquet(CLEAN / "sub_ggn_hourly.parquet")
            pk = (sub.chw_pumps_kw + sub.cw_pumps_ct_kw).sum()
            rows.append(dict(site=s, measure="VFDs on chilled-water and condenser pumps (constant speed today)", category=CAPITAL,
                             inr=pk * VFD_SHARE * rkwh,
                             basis=f"{pk:,.0f} kWh/yr of pump energy, flat whatever the plant load; {VFD_SHARE:.0%} typical for variable-flow conversion",
                             safety="Set up by the chiller manufacturer to keep enough water flowing; an investment, so only in the with-capital total",
                             confidence="Low (capital, typical 30 %)", payback="needs a supplier quote"))
        if s == "GGN" and LIVE_YEAR:
            rows.append(dict(site=s, measure="Daily operating plan: lower maximum demand in months without a penalty", category="Demand",
                             inr=_plan_live()[2],
                             basis="Plan simulated on the live year with the frozen models; the plan's other levers are the same waste the alerts already "
                                   "count, so they are not added again",
                             safety="Recommend only: the plan moves laundry, water heating and EV charging; chillers, kitchens, lifts and safety systems "
                                    "are never cut", confidence="Medium"))
    p = pd.DataFrame(rows)
    bill = pd.read_parquet(CLEAN / "monthly_bills.parquet").groupby("site").total_energy_cost_inr.sum()
    p["pct_of_site_bill"] = p.inr / p.site.map(bill) * 100
    p["hotel"] = p.site.map(SITES)
    return p


NOT_SIZED = [
    "Unsold-room setback via PMS: guest-room FCU/plug load already scales with rooms sold (≈0.2 kW per sold room, ~0 for unsold), so little to gain.",
    "Night base load (00–05 h): audited per sub-meter channel against each channel's own good nights (data/night_baseload.md); only a persistent "
    "excess is counted. Cutting below the best nights the meters have seen (switching areas off) needs the night walk-round, not data.",
    "Other capital measures (chiller replacement, solar, heat recovery) are out of scope; pump VFDs are the one capital item, counted only in the with-capital total.",
]


def totals(p: pd.DataFrame | None = None) -> dict:
    """The two headline totals: operations (all rows except Capital) and with capital (operations + Capital), as ₹ and % of the group bill."""
    p = plan() if p is None else p
    bill = float(pd.read_parquet(CLEAN / "monthly_bills.parquet").total_energy_cost_inr.sum())
    ops = float(p.loc[p.category != CAPITAL, "inr"].sum())
    cap = float(p.loc[p.category == CAPITAL, "inr"].sum())
    o, w = ops / bill * 100, (ops + cap) / bill * 100
    return dict(group_bill=bill, operations_inr=ops, capital_inr=cap, with_capital_inr=ops + cap, operations_pct=round(o, 1),
                with_capital_pct=round(w, 1), text=f"{o:.1f}% from operations · {w:.1f}% with one capital item (pump VFDs)")


def write_live_md(live_t: dict, orig_t: dict) -> None:
    """data/live/savings_live.md: both totals for both years and the plan lever table."""
    levers, mon, inc = _plan_live()
    L = ["# Savings: original year and live year", "",
         "The live year (Oct 2026 – Sep 2027) is **synthetic** (tools/make_live_year.py); its figures are a robustness check, not a measured result.", "",
         "| Year | Operations | With one capital item (pump VFDs) | Headline |", "|---|---:|---:|---|"]
    for name, t in (("Original (Oct 2025 – Sep 2026)", orig_t), ("Live (Oct 2026 – Sep 2027, synthetic)", live_t)):
        L.append(f"| {name} | ₹{t['operations_inr']:,.0f} ({t['operations_pct']:.1f}%) | ₹{t['with_capital_inr']:,.0f} ({t['with_capital_pct']:.1f}%) | {t['text']} |")
    L += ["", "## Daily operating plan, simulated on the live year (Gurugram)", "",
          "| Lever | kWh | ₹ | Category | Already counted as |", "|---|---:|---:|---|---|"]
    L += [f"| {r.lever} | {r.kwh:,.0f} | ₹{r.inr:,.0f} | {r.category} | {r.already_counted_as} |" for r in levers.itertuples()]
    L += [f"| **Plan total** | | **₹{levers.inr.sum():,.0f}** | | |", "",
          f"Only ₹{inc:,.0f} is added to the live-year savings (the lower-demand saving in months with no excess-demand penalty billed); the rest is the "
          "same waste the alert and breach rows already count. Verified plan ₹ from approved steps (Plan vs actual) stays on the plan pages and the "
          "monthly report and is never added to this headline."]
    (CLEAN / "savings_live.md").write_text("\n".join(L) + "\n", encoding="utf-8")


# ---- IPMVP Option C ------------------------------------------------------------------------------------------
def model_stats(site: str) -> dict:
    """Fit statistics of the adjustment model and the minimum verifiable savings (ASHRAE G14 FSU, 90 % confidence)."""
    d = _frame(site)
    v = d[d.valid]
    y, p = v.total_kwh.to_numpy(), v.pred_ens.to_numpy()          # out-of-fold: honest error
    n = len(y)
    cv = math.sqrt(((y - p) ** 2).sum() / (n - 1)) / y.mean()
    nmbe = (y - p).sum() / ((n - 1) * y.mean())
    r = pd.Series(y - p)
    rho = float(r.autocorr(1))
    n_eff = n * (1 - rho) / (1 + rho)
    t = stats.t.ppf(0.95, n_eff - 1)
    m = 8760                                                       # one reporting year, hourly
    def fsu(F):
        return 1.26 * t * cv * math.sqrt((n / n_eff) * (1 + 2 / n) * (1 / m)) / F
    mv = d.groupby("month").agg(actual=("total_kwh", "sum"), baseline=("pred_ens", "sum"))
    cv_m = math.sqrt(((mv.actual - mv.baseline) ** 2).sum() / (len(mv) - 1)) / mv.actual.mean()
    min_F = next((F / 100 for F in np.arange(0.5, 30, 0.5) if fsu(F / 100) <= 0.5), None)
    return dict(cv_rmse_hourly=cv * 100, nmbe=nmbe * 100, cv_rmse_monthly=cv_m * 100, autocorr=rho, n=n, n_eff=n_eff,
                fsu_at_5pct=fsu(0.05) * 100, fsu_at_8pct=fsu(0.08) * 100, min_verifiable_pct=None if min_F is None else min_F * 100, monthly=mv)


def verify(site: str, go_live: str, actual: pd.Series | None = None) -> pd.DataFrame:
    """Option C: monthly adjusted baseline (model fitted on hours before go_live, driven by actual conditions after) minus actual."""
    from baseline import GBM_FEATURES, build_features, make_gbm, make_ridge
    d = build_features(site)
    pre, post = d[(d.timestamp < go_live) & d.valid], d[(d.timestamp >= go_live) & d.valid]
    r = make_ridge().fit(pre, pre.total_kwh)
    g = make_gbm().fit(pre[GBM_FEATURES], pre.total_kwh)
    post = post.assign(adjusted_baseline=(r.predict(post) + g.predict(post[GBM_FEATURES])) / 2)
    if actual is not None:
        post["total_kwh"] = actual.reindex(post.index)
    m = post.groupby("month").agg(adjusted_baseline=("adjusted_baseline", "sum"), actual=("total_kwh", "sum"))
    m["savings_kwh"] = m.adjusted_baseline - m.actual
    return m


def original_totals() -> dict:
    """Original-year totals from a separate process (modules bind their data folder at import)."""
    env = {k: v for k, v in os.environ.items() if k != "SAFFRON_DATA"} | {"PYTHONIOENCODING": "utf-8"}
    out = subprocess.run([sys.executable, __file__, "--totals"], capture_output=True, encoding="utf-8", env=env, cwd=ROOT, check=True).stdout
    return json.loads(out.strip().splitlines()[-1])


if __name__ == "__main__":
    p = plan()
    if "--totals" in sys.argv:
        print(json.dumps(totals(p)))
        sys.exit(0)
    pd.set_option("display.width", 220, "display.max_colwidth", 70)
    print(p[["site", "category", "measure", "inr", "pct_of_site_bill"]].round(1).to_string())
    t = totals(p)
    print(f"{'live' if LIVE_YEAR else 'original'} year: operations ₹{t['operations_inr']:,.0f}, with capital ₹{t['with_capital_inr']:,.0f} "
          f"of ₹{t['group_bill'] / 1e7:.2f} cr -> {t['text']}")
    print(p.groupby("category").inr.sum())
    if LIVE_YEAR:
        o = original_totals()
        write_live_md(t, o)
        print("original year:", o["text"], "| wrote", CLEAN / "savings_live.md")
    for s in ["GGN", "JAI", "GOA"]:
        st = model_stats(s); st.pop("monthly"); print(s, {k: round(v, 2) if isinstance(v, float) else v for k, v in st.items()})
