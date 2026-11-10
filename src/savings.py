"""Savings: (1) a sized plan of safe measures split energy / ToD / demand, (2) IPMVP Option C verification statistics.

Why both: the brief targets 8–12 % of the bill as *identified* savings, and finance only accepts savings verified against an adjusted baseline.
(1) sizes each measure from the year's metered data with stated assumptions and a safety check; nothing is claimed as achieved.
(2) gives the M&V engine: the full-year baseline (weather, occupancy, events, day type) is the Option C adjustment model; this module reports its
    fit and the minimum savings it can verify (ASHRAE Guideline 14 fractional savings uncertainty). Verified savings = adjusted baseline − actual,
    computed with `verify()` once a measure has a go-live date and a reporting period. The data year contains no implemented measure, so no
    verified saving is reported - that would be invented.
Data faults are never savings (T5): fault hours are excluded everywhere via `valid`.
"""
import math

import numpy as np
import pandas as pd
from scipy import stats

from bills import TOD, _in_window, tariff
from features import CLEAN, SITES

APP = CLEAN.parent / "app"
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
                         category="Energy", inr=e.cost_inr.sum(), basis=f"{len(e)} alerts over the year; ₹ is the detector's (staging/CHW/AHU are lower bounds)",
                         safety="Each action carries its guardrail; kitchen exhaust interlock only, never auto-off", confidence="High"))
        pfa = c[c.rule == "POWER_FACTOR_DROP"]
        if len(pfa):
            rows.append(dict(site=s, measure="Keep PF ≥ 0.97: repair APFC steps within hours (PF alert)", category="Energy", inr=pfa.cost_inr.sum(),
                             basis=f"{len(pfa)} PF-drop episodes; excess kVAh × energy+FSA+duty", safety="No comfort impact", confidence="High"))
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
                         safety="Hot water must still reach ≥60 °C once a day (Legionella); laundry recommend-only", confidence="Medium"))
        # 3. Demand
        b = pd.read_parquet(CLEAN / "monthly_bills.parquet").query("site == @s")
        if b.excess_demand_penalty_inr.sum() > 0:
            rows.append(dict(site=s, measure="Avoid contract-demand breaches: day-ahead stacking watch + shift plan + EV throttle above 920 kVA",
                             category="Demand", inr=b.excess_demand_penalty_inr.sum(), basis="Excess-demand penalties actually billed this year",
                             safety="Never shed chillers, kitchen, lifts or life-safety", confidence="Medium"))
        max_md = b.recorded_md_kva.max()
        new_cd = math.ceil(max_md * 1.15 / 10) * 10
        if new_cd < t["cd"]:
            def demand_bill(cd):
                bd = np.maximum(b.recorded_md_kva, 0.75 * cd)
                return (np.minimum(bd, cd) * t["demand"] + np.maximum(b.recorded_md_kva - cd, 0) * t["penalty"]).sum() * (1 + t["muni"])
            rows.append(dict(site=s, measure=f"Right-size contract demand {t['cd']:,.0f} → {new_cd:,} kVA (max MD this year {max_md:,.0f} kVA, +15 % headroom)",
                             category="Demand", inr=demand_bill(t["cd"]) - demand_bill(new_cd),
                             basis=f"MD below the 75 % floor ({0.75 * t['cd']:,.0f} kVA) in {(b.recorded_md_kva < 0.75 * t['cd']).sum()} of 12 months - paying for unused demand",
                             safety="Paperwork with the utility; no equipment change. Check growth plans first", confidence="Medium"))
        # 4. CHW reset to 8 degC in cool, light-load hours (guide allows)
        if s == "GGN":
            ok = (d.temp_c < 24) & (d.chw_setpoint_c == 7.0) & d.chiller_load_tr.between(1, 280) & d.valid
            kwh = d.chillers_kw[ok].sum() * 0.035
            rows.append(dict(site=s, measure="CHW reset 7 → 8 °C when outdoor < 24 °C and plant load is light", category="Energy", inr=kwh * rkwh,
                             basis=f"{ok.sum():,} eligible hours, {d.chillers_kw[ok].sum():,.0f} chiller kWh × 3.5 %/°C (guide)",
                             safety="Within the guide's reset rule; never below 6.5 °C; watch humidity complaints", confidence="Medium"))
    p = pd.DataFrame(rows)
    bill = pd.read_parquet(CLEAN / "monthly_bills.parquet").groupby("site").total_energy_cost_inr.sum()
    p["pct_of_site_bill"] = p.inr / p.site.map(bill) * 100
    p["hotel"] = p.site.map(SITES)
    return p


NOT_SIZED = [
    "Unsold-room setback via PMS: guest-room FCU/plug load already scales with rooms sold (≈0.2 kW per sold room, ~0 for unsold), so little to gain.",
    "Night base load (GGN ~330 kW 01–05 h): 8–14 % of energy is unmetered 'other'; needs a walk-through audit, not sizable from data.",
    "Capital measures (chiller replacement, solar, heat recovery) are out of scope; short note only.",
]


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


if __name__ == "__main__":
    p = plan()
    pd.set_option("display.width", 220, "display.max_colwidth", 70)
    print(p[["site", "category", "measure", "inr", "pct_of_site_bill"]].round(1).to_string())
    tot = pd.read_parquet(CLEAN / "monthly_bills.parquet").total_energy_cost_inr.sum()
    print("total ₹", round(p.inr.sum()), f"{p.inr.sum() / tot * 100:.1f}% of ₹{tot / 1e7:.2f} cr")
    print(p.groupby("category").inr.sum())
    for s in ["GGN", "JAI", "GOA"]:
        st = model_stats(s); st.pop("monthly"); print(s, {k: round(v, 2) if isinstance(v, float) else v for k, v in st.items()})
