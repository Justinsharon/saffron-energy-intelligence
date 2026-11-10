"""Why did a bill change? (T9: "Why was Gurugram's May 2026 bill higher than April's?")

Method (all numbers from the baseline model and the bills; nothing from an LLM):
1. Fit the baseline ensemble (src/baseline.py: Ridge + shallow LightGBM, averaged) on every valid hour of the year.
2. Energy volume change = Δ(baseline) + Δ(actual − baseline).
   Δ(baseline) is split between driver groups with exact Shapley values: predict month B's hours with each group of drivers
   (weather / occupancy / events) taken from month A or B (same day-of-month and hour; extra days wrap). What is left once all
   three groups are at A's values is the calendar (day count, weekdays).
   Δ(actual − baseline) is "operations": kWh flagged by detector alerts in the month, plus an unexplained remainder (model noise).
3. ₹: volume kWh at month A's marginal grid rate ((energy + FSA + duty + 2 % municipal tax on energy) / PF); then separately the PF effect,
   the ToD net, the demand charge, the excess-demand penalty, and diesel at its own rate. A rounding line closes the sum to the
   difference between the two issued bills exactly.
"""
from itertools import permutations

import numpy as np
import pandas as pd

from baseline import GBM_FEATURES, build_features, make_gbm, make_ridge
from bills import tariff
from features import CLEAN

GROUPS = {
    "Weather": ["temp_c", "temp_3h", "cdh", "cdh_24h", "hdh", "rel_humidity_pct", "rain_mm"],
    "Occupancy": ["rooms_sold", "guests_in_house", "covers_served_fnb", "occupancy_pct"],
    "Events": ["ev_guests", "ev_core", "ev_social", "ev_corp", "ev_evening"],
}
_MODELS = {}


def production_baseline(site: str):
    """(frame with pred column, fitted models). Cached per process; fit on every valid hour of the year."""
    if site not in _MODELS:
        d = build_features(site)
        tr = d[d.valid]
        r = make_ridge().fit(tr, tr.total_kwh)
        g = make_gbm().fit(tr[GBM_FEATURES], tr.total_kwh)
        _MODELS[site] = (r, g)
    r, g = _MODELS[site]
    d = build_features(site)
    d["pred"] = predict(site, d)
    return d, (r, g)


def predict(site: str, d: pd.DataFrame) -> np.ndarray:
    r, g = _MODELS[site]
    return (r.predict(d) + g.predict(d[GBM_FEATURES])) / 2


def _counterfactual(dB: pd.DataFrame, dA: pd.DataFrame, take_from_a: set) -> pd.DataFrame:
    """Month B's hours with the listed driver groups replaced by month A's values (same day-of-month and hour, wrapping)."""
    x = dB.copy()
    nA = dA.timestamp.dt.day.max()
    key_b = ((dB.timestamp.dt.day - 1) % nA + 1) * 100 + dB.timestamp.dt.hour
    a = dA.assign(key=dA.timestamp.dt.day * 100 + dA.timestamp.dt.hour).drop_duplicates("key").set_index("key")
    for gname in take_from_a:
        for c in GROUPS[gname]:
            x[c] = a[c].reindex(key_b.to_numpy()).to_numpy()
    return x


def _alert_kwh(site: str, month: str) -> pd.DataFrame:
    """Detector-flagged excess kWh falling in the month (pro-rated by overlap) per waste type."""
    a = pd.read_parquet(CLEAN / "alerts.parquet").query("site == @site")
    p = pd.Period(month)
    m0, m1 = p.start_time, (p + 1).start_time
    rows = []
    for r in a.itertuples():
        ov = (min(r.end, m1) - max(r.start, m0)) / (r.end - r.start)
        if ov > 0 and r.excess_kwh > 0:
            rows.append(dict(rule=r.rule, kwh=r.excess_kwh * ov))
    return pd.DataFrame(rows, columns=["rule", "kwh"]).groupby("rule").kwh.sum()


def explain_change(site: str, month_a: str, month_b: str) -> dict:
    d, _ = production_baseline(site)
    b = pd.read_parquet(CLEAN / "monthly_bills.parquet").query("site == @site").set_index("billing_month")
    A, B = d[d.month == month_a], d[d.month == month_b]
    bA, bB = b.loc[month_a], b.loc[month_b]
    t = tariff(site)

    # --- kWh: baseline driver split (Shapley over 3 groups) ---------------------------------------------------
    names = list(GROUPS)
    cache = {}
    def f(keep_b: frozenset) -> float:              # groups at B's values; the rest at A's
        if keep_b not in cache:
            cache[keep_b] = float(predict(site, _counterfactual(B, A, set(names) - keep_b)).sum())
        return cache[keep_b]
    shap = {g: 0.0 for g in names}
    perms = list(permutations(names))
    for order in perms:
        s = frozenset()
        for g in order:
            shap[g] += (f(s | {g}) - f(s)) / len(perms)
            s = s | {g}
    base_A, base_B = float(A.pred.sum()), float(B.pred.sum())
    calendar = f(frozenset()) - base_A                      # B's calendar with all of A's drivers, minus A
    act_A, act_B = float(A.total_kwh.sum()), float(B.total_kwh.sum())
    ops = (act_B - base_B) - (act_A - base_A)
    ak = _alert_kwh(site, month_b).sum() - _alert_kwh(site, month_a).sum()
    kwh = {"Weather": shap["Weather"], "Occupancy": shap["Occupancy"], "Events": shap["Events"],
           "Calendar (days, weekdays)": calendar, "Detected waste (alerts)": ak, "Unexplained / model noise": ops - ak}

    # --- ₹ ------------------------------------------------------------------------------------------------------
    pfA = bA.grid_kwh / bA.grid_kvah
    per_kvah = t["energy"] * (1 + t["muni"]) + t["fsa"] + t["duty"]
    rate_kwh = per_kvah / pfA
    dg_delta = bB.dg_kwh - bA.dg_kwh
    lines = {k: v * rate_kwh for k, v in kwh.items()}
    # Volume above was priced as if all kWh came from the grid; move the DG share to the diesel rate.
    lines["Diesel (DG hours, priced at ₹27.56/kWh)"] = dg_delta * (t["dg"] - rate_kwh)
    lines["Power factor change (kVAh per kWh)"] = bB.grid_kwh * (1 / (bB.grid_kwh / bB.grid_kvah) - 1 / pfA) * per_kvah
    lines["ToD net (peak surcharge − off-peak rebate)"] = bB.tod_net_inr - bA.tod_net_inr
    lines["Demand charge (incl. 2% municipal tax)"] = (bB.demand_charge_inr - bA.demand_charge_inr) * (1 + t["muni"])
    lines["Excess-demand penalty"] = bB.excess_demand_penalty_inr - bA.excess_demand_penalty_inr
    total = bB.total_energy_cost_inr - bA.total_energy_cost_inr
    lines["Meter vs model rounding"] = total - sum(lines.values())

    group = {"Weather": "Weather", "Occupancy": "Occupancy", "Events": "Events", "Calendar (days, weekdays)": "Calendar",
             "Detected waste (alerts)": "Anomalies", "Power factor change (kVAh per kWh)": "Anomalies",
             "Unexplained / model noise": "Unexplained", "Excess-demand penalty": "Demand", "Demand charge (incl. 2% municipal tax)": "Demand",
             "ToD net (peak surcharge − off-peak rebate)": "Tariff mix", "Diesel (DG hours, priced at ₹27.56/kWh)": "Diesel", "Meter vs model rounding": "Unexplained"}
    tab = pd.DataFrame([dict(driver=k, group=group[k], kwh=kwh.get(k, np.nan), inr=v) for k, v in lines.items()])
    ctx = dict(cdh_A=float(A.cdh.sum()), cdh_B=float(B.cdh.sum()), tmax_A=float(A.temp_c.max()), tmax_B=float(B.temp_c.max()),
               rooms_A=float(A.groupby("date").rooms_sold.first().sum()), rooms_B=float(B.groupby("date").rooms_sold.first().sum()),
               event_guests_A=int(pd.read_parquet(CLEAN / "events.parquet").query("site == @site").pipe(lambda e: e[e.date.astype(str).str[:7] == month_a]).guests.sum()),
               event_guests_B=int(pd.read_parquet(CLEAN / "events.parquet").query("site == @site").pipe(lambda e: e[e.date.astype(str).str[:7] == month_b]).guests.sum()),
               md_A=float(bA.recorded_md_kva), md_B=float(bB.recorded_md_kva), pf_A=float(pfA), pf_B=float(bB.grid_kwh / bB.grid_kvah))
    return dict(site=site, month_a=month_a, month_b=month_b, bill_a=float(bA.total_energy_cost_inr), bill_b=float(bB.total_energy_cost_inr),
                delta=float(total), table=tab, context=ctx,
                alert_rules_b=_alert_kwh(site, month_b).sort_values(ascending=False).round(0).to_dict())


if __name__ == "__main__":
    r = explain_change("GGN", "2026-04", "2026-05")
    pd.set_option("display.width", 200)
    print(f"{r['bill_a']:,.0f} -> {r['bill_b']:,.0f}  delta {r['delta']:,.0f}")
    print(r["table"].round(0).to_string())
    print(r["table"].groupby("group").inr.sum().round(0))
    print(r["context"], r["alert_rules_b"])
