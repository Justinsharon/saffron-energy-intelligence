"""Bill reconciliation: rebuild every monthly bill from the tariff sheet and from the meter, component by component.

Why deterministic arithmetic and no ML: finance must be able to tick every line. Three checks per bill:
  1. tariff check  - the tariff applied to the bill's *own* quantities reproduces each ₹ line (proves we read the tariff right);
  2. meter check   - quantities rebuilt from the raw meter (what the utility read) match the bill's quantities;
  3. corrected     - the same bill priced on the *cleaned* meter (meter-fault intervals rebuilt from kW). The gap is a
                     billing-dispute candidate, never a saving, and the issued bill is never altered (CLAUDE.md).

Demand charge (resolves OPEN_QUESTIONS #2 - both documents agree once read together, and all 36 bills reproduce):
  billing demand = max(recorded MD, 75 % of CD); demand charge = min(billing demand, CD) x rate;
  excess-demand penalty = max(MD - CD, 0) x penalty rate, charged on top. Municipal tax = 2 % of (energy + demand charge).
"""
import numpy as np
import pandas as pd

from features import CLEAN, CONTRACT_KVA

# ToD windows per hotel, [start, end) hours; off-peak may wrap midnight. From the tariffs sheet.
TOD = {"GGN": dict(peak=(18, 22), off=(23, 5)), "JAI": dict(peak=(17, 23), off=(23, 5)), "GOA": dict(peak=(18, 22), off=(22, 6))}
FAULT_MONTHS_NOTE = "Billed on readings taken during a meter data fault; corrected figure rebuilt from live kW (bill left as issued)."
TOL_PCT = 1.0          # a bill line within ±1 % of the rebuild is reconciled (default; OPEN_QUESTIONS #4)


def tariff(site: str) -> dict:
    t = pd.read_parquet(CLEAN / "tariffs.parquet").query("site == @site").set_index("component").rate
    return dict(energy=t["Energy charge"], peak=t["Peak ToD surcharge"], off=t["Off-peak ToD rebate"], demand=t["Demand charge"],
                penalty=t["Excess demand penalty"], fsa=t["Fuel surcharge adjustment (FSA)"], duty=t["Electricity duty"],
                muni=t["Municipal tax"], cd=t["Contract demand"], dg=t["DG generation cost"])


def _in_window(hour: pd.Series, w: tuple) -> pd.Series:
    a, b = w
    return hour.between(a, b - 1) if a < b else (hour >= a) | (hour < b)


def price(site: str, kvah: float, peak_kvah: float, off_kvah: float, md_kva: float, dg_kwh: float = 0.0) -> dict:
    """Every ₹ line of the bill from the five billed quantities."""
    t = tariff(site)
    bd = max(md_kva, 0.75 * t["cd"])
    out = dict(energy_charge_inr=kvah * t["energy"], tod_net_inr=peak_kvah * t["peak"] + off_kvah * t["off"],
               billing_demand_kva=bd, demand_charge_inr=min(bd, t["cd"]) * t["demand"],
               excess_demand_penalty_inr=max(md_kva - t["cd"], 0.0) * t["penalty"],
               fsa_inr=kvah * t["fsa"], electricity_duty_inr=kvah * t["duty"])
    out["municipal_tax_inr"] = t["muni"] * (out["energy_charge_inr"] + out["demand_charge_inr"])
    out["total_grid_bill_inr"] = sum(out[k] for k in ["energy_charge_inr", "tod_net_inr", "demand_charge_inr", "excess_demand_penalty_inr",
                                                      "fsa_inr", "electricity_duty_inr", "municipal_tax_inr"])
    out["dg_cost_inr"] = dg_kwh * t["dg"]
    out["total_energy_cost_inr"] = out["total_grid_bill_inr"] + out["dg_cost_inr"]
    return out


LINES = ["energy_charge_inr", "tod_net_inr", "demand_charge_inr", "excess_demand_penalty_inr", "fsa_inr", "electricity_duty_inr",
         "municipal_tax_inr", "total_grid_bill_inr", "dg_cost_inr", "total_energy_cost_inr"]
QTY = ["grid_kwh", "grid_kvah", "peak_window_kvah", "offpeak_window_kvah", "recorded_md_kva", "dg_kwh"]


def meter_quantities(site: str, raw: bool) -> pd.DataFrame:
    """Monthly billed quantities from the meter. raw=True uses the readings as the utility took them (fault values kept)."""
    if site == "GGN":
        m = pd.read_parquet(CLEAN / "meter_ggn_15min.parquet")
        kwh, kvah, kva = (("grid_kwh_raw", "grid_kvah_raw", "kva_demand_raw") if raw else ("grid_kwh", "grid_kvah", "kva_demand"))
    else:
        m = pd.read_parquet(CLEAN / f"meter_{site.lower()}_hourly.parquet")
        has_raw = raw and "grid_kwh_raw" in m
        kwh, kvah, kva = (("grid_kwh_raw", "grid_kvah_raw", "kva_max_in_hour_raw") if has_raw else ("grid_kwh", "grid_kvah", "kva_max_in_hour"))
    h = m.timestamp.dt.hour
    w = TOD[site]
    g = pd.DataFrame({"month": m.timestamp.dt.to_period("M").astype(str), "grid_kwh": m[kwh], "grid_kvah": m[kvah],
                      "peak_window_kvah": m[kvah].where(_in_window(h, w["peak"]), 0.0),
                      "offpeak_window_kvah": m[kvah].where(_in_window(h, w["off"]), 0.0), "recorded_md_kva": m[kva], "dg_kwh": m.dg_kwh})
    q = g.groupby("month").agg(grid_kwh=("grid_kwh", "sum"), grid_kvah=("grid_kvah", "sum"), peak_window_kvah=("peak_window_kvah", "sum"),
                               offpeak_window_kvah=("offpeak_window_kvah", "sum"), recorded_md_kva=("recorded_md_kva", "max"), dg_kwh=("dg_kwh", "sum"))
    return q


def fault_months(site: str) -> set:
    f = pd.read_parquet(CLEAN / "meter_faults.parquet").query("site == @site")
    return set(f.start.dt.to_period("M").astype(str)) if site == "GGN" else set()   # Jaipur's gap was blank, not billed on bad values


def reconcile(site: str) -> pd.DataFrame:
    """One row per month: issued bill, tariff-check rebuild, meter-raw and corrected rebuilds, variances and a status."""
    b = pd.read_parquet(CLEAN / "monthly_bills.parquet").query("site == @site").set_index("billing_month")
    raw, cor = meter_quantities(site, raw=True), meter_quantities(site, raw=False)
    fm = fault_months(site)
    rows = []
    for mo, r in b.iterrows():
        chk = price(site, r.grid_kvah, r.peak_window_kvah, r.offpeak_window_kvah, r.recorded_md_kva, r.dg_kwh)
        q_raw, q_cor = raw.loc[mo], cor.loc[mo]
        mr = price(site, q_raw.grid_kvah, q_raw.peak_window_kvah, q_raw.offpeak_window_kvah, q_raw.recorded_md_kva, q_raw.dg_kwh)
        mc = price(site, q_cor.grid_kvah, q_cor.peak_window_kvah, q_cor.offpeak_window_kvah, q_cor.recorded_md_kva, q_cor.dg_kwh)
        tariff_gap = max(abs(chk[k] - r[k]) for k in LINES if k in r)
        meter_gap_pct = (r.grid_kvah - q_raw.grid_kvah) / q_raw.grid_kvah * 100
        corr_gap = r.total_energy_cost_inr - mc["total_energy_cost_inr"]
        if r.is_provisional:
            status, note = "Provisional", (f"Estimated reading: billed kVAh {meter_gap_pct:+.1f}% vs meter. Ask the utility for an actual-reading "
                                           f"revision; meter-based bill ₹{mc['total_energy_cost_inr']:,.0f} (₹{corr_gap:,.0f} over).")
        elif mo in fm:
            status, note = "Meter fault", FAULT_MONTHS_NOTE + f" Billed − corrected = ₹{corr_gap:,.0f} ({'billed high' if corr_gap > 0 else 'billed low'})."
        elif abs(meter_gap_pct) <= TOL_PCT and tariff_gap <= 200:          # ₹200: MD is billed in whole kVA, lines are rounded
            status, note = "Reconciled", f"Tariff rebuild within ₹{tariff_gap:,.0f}; billed kVAh {meter_gap_pct:+.2f}% vs meter."
        elif abs((r.grid_kvah - q_cor.grid_kvah) / q_cor.grid_kvah * 100) <= TOL_PCT and tariff_gap <= 200:
            g2 = (r.grid_kvah - q_cor.grid_kvah) / q_cor.grid_kvah * 100
            status, note = "Reconciled", (f"Meter had blank hours this month; billed kVAh {meter_gap_pct:+.2f}% vs the readings that exist, "
                                          f"{g2:+.2f}% vs the gap-filled meter.")
        else:
            status, note = "Check", f"Billed kVAh {meter_gap_pct:+.2f}% vs meter; largest tariff-line gap ₹{tariff_gap:,.0f}."
        rows.append(dict(site=site, month=mo, status=status, note=note, billed_total=r.total_energy_cost_inr, tariff_check_total=chk["total_energy_cost_inr"],
                         tariff_check_max_gap=tariff_gap, meter_kvah=q_raw.grid_kvah, billed_kvah=r.grid_kvah, meter_gap_pct=meter_gap_pct,
                         corrected_total=mc["total_energy_cost_inr"], billed_minus_corrected=corr_gap, md_kva=r.recorded_md_kva,
                         billing_demand_kva=r.billing_demand_kva, pf=r.grid_kwh / r.grid_kvah,
                         **{f"bill_{k}": r[k] for k in LINES}))
    return pd.DataFrame(rows)


def reconcile_all() -> pd.DataFrame:
    return pd.concat([reconcile(s) for s in ["GGN", "JAI", "GOA"]], ignore_index=True)


def components(site: str) -> pd.DataFrame:
    """Issued bill by ₹ component per month (long format, for charts)."""
    b = pd.read_parquet(CLEAN / "monthly_bills.parquet").query("site == @site")
    names = {"energy_charge_inr": "Energy (kVAh)", "tod_net_inr": "ToD net", "demand_charge_inr": "Demand charge",
             "excess_demand_penalty_inr": "Excess-demand penalty", "fsa_inr": "Fuel surcharge", "electricity_duty_inr": "Electricity duty",
             "municipal_tax_inr": "Municipal tax", "dg_cost_inr": "Diesel (DG)"}
    return b.melt(id_vars="billing_month", value_vars=list(names), var_name="component", value_name="inr").replace({"component": names})


def unused_demand(site: str) -> dict:
    """Months where the 75 %-of-CD floor billed more demand than was used, and the ₹ that floor cost."""
    t = tariff(site)
    b = pd.read_parquet(CLEAN / "monthly_bills.parquet").query("site == @site")
    floor = 0.75 * t["cd"]
    paid_unused = ((floor - b.recorded_md_kva).clip(lower=0) * t["demand"]).sum()
    return dict(cd=t["cd"], floor=floor, max_md=float(b.recorded_md_kva.max()), months_on_floor=int((b.recorded_md_kva < floor).sum()),
                paid_for_unused_inr=float(paid_unused))


if __name__ == "__main__":
    r = reconcile_all()
    pd.set_option("display.width", 250)
    print(r[["site", "month", "status", "billed_total", "tariff_check_max_gap", "meter_gap_pct", "billed_minus_corrected"]].to_string())
    for s in ["GGN", "JAI", "GOA"]:
        print(s, unused_demand(s))
