"""Night base-load audit: energy used 00:00-05:00 that the hotels don't need, per hotel and sub-meter channel. RECOMMEND ONLY.

Why a separate audit: the night base load (GGN ~330 kW, JAI ~190, GOA ~180 at 01-05 h) was listed as "not sizable from data". This sizes the
part that is, without inventing targets: each channel is compared with its own *good nights* - the 10th-20th percentile of nights with similar
occupancy and outdoor temperature (the 30 nearest nights on both) - so whatever the reference allows is already "achievable here".

  excess per night = actual night kW - good-night kW (the part occupancy and weather don't explain)
  claimed only if it repeats: (a) more than half of the nights sit above the reference by more than the sub-meters' ±1 % accuracy
  (CONTEXT.md §17), and (b) it persists from one night to the next (lag-1 correlation of the nightly excess above 2/sqrt(n), the 95 % line
  for random scatter). (b) matters: with pure night-to-night noise the median night always sits about one standard deviation above the
  15th percentile, so (a) alone would "find" savings in any noisy channel; real waste (an AHU left on day speed, a board left on) carries
  over between nights. The claim is the MEDIAN nightly excess (so most nights reach it) × the night hours checked - no scaling up.
  The report also shows what (a) alone would claim, so the effect of (b) is visible.
  ₹ at each hotel's off-peak price (00-05 h is inside every hotel's off-peak window, so the rebate applies).

Not counted (no double counting, nothing that must run):
  * hours a detector alert already counts as waste on that channel (data/<year>/alerts.parquet; RESIDUAL / PF alerts: every channel),
    DG hours and meter-fault / imputed hours;
  * the daily plan's levers: chillers and chilled water (staging, setpoint), laundry, water heating, EV chargers, banquet AHUs (Gurugram),
    event lighting on nights after an event (Jaipur / Goa);
  * what must run at night: guest rooms, lifts, chilled water and its pumps for occupied rooms (pumps: the VFD capital row), the water
    heating's daily cycle, pool heating / filtration minimums (Gurugram pool), kitchen exhaust in hours the kitchen is cooking.
Night public lighting already has a savings row (an assumed dimming share, src/savings.py); savings.py adds only the audit's lighting kWh
beyond that row, so nothing is counted twice.

Anomaly labels are not used. Run: uv run python tools/night_baseload.py   (writes data/night_baseload.md: original year = the claim,
live year = a check on synthetic data)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from features import SITES, gurugram_hourly  # noqa: E402

ORIG, LIVE = ROOT / "data" / "clean", ROOT / "data" / "live"
NIGHT = range(0, 5)                     # 00:00-05:00 (start-of-interval hours 0..4)
K = 30                                  # nearest nights on occupancy and temperature
REF_Q = (10, 20)                        # good night: the 10th-20th percentile of those nights
METER_TOL = 0.01                        # sub-meters ±1 % (CONTEXT.md §17)
MIN_HOURS = 4                           # a night counts with at least 4 of its 5 hours valid

GGN_CH = ["chiller_ch1_kw", "chiller_ch2_kw", "chiller_ch3_kw", "chw_pumps_kw", "cw_pumps_ct_kw", "ahu_public_kw", "ahu_banquet_kw", "ahu_heaters_kw",
          "kitchen_kw", "kitchen_exhaust_mua_kw", "laundry_kw", "lighting_public_kw", "rooms_fcu_plug_kw", "lifts_kw", "ev_chargers_kw", "water_heating_kw",
          "pool_kw", "other_kw"]
JG_CH = ["chillers_kw", "ahu_kw", "kitchen_kw", "laundry_kw", "lighting_kw", "pumps_pool_kw", "rooms_kw", "other_kw"]

# channels never claimed, and why (must run at night, or a plan lever / another savings row already covers them)
EXCLUDED = {
    "chiller_ch1_kw": "chilled water for occupied rooms; staging waste counted by alerts and the daily plan",
    "chiller_ch2_kw": "out of service; chilled water for occupied rooms", "chiller_ch3_kw": "chilled water for occupied rooms; staging counted by alerts and the plan",
    "chw_pumps_kw": "serve occupied rooms; constant-speed pumping is the pump-VFD capital row", "cw_pumps_ct_kw": "serve occupied rooms; pump-VFD capital row",
    "ahu_banquet_kw": "daily plan lever (banquet AHUs) and hand-mode alerts", "laundry_kw": "daily plan lever (laundry timing)",
    "rooms_fcu_plug_kw": "guest rooms (never controlled)", "lifts_kw": "lifts (life-safety, never controlled)", "ev_chargers_kw": "daily plan lever (EV) and EV night rule",
    "water_heating_kw": "daily ≥ 60 °C cycle (Legionella) and a daily plan lever", "pool_kw": "pool heating in winter is genuine; filtration minimum",
    "chillers_kw": "chilled water for occupied rooms; staging counted by alerts and the daily plan", "rooms_kw": "guest rooms (never controlled)",
}
LABEL = {"ahu_public_kw": "Public-area AHUs", "ahu_heaters_kw": "AHU re-heat", "kitchen_kw": "Kitchen", "kitchen_exhaust_mua_kw": "Kitchen exhaust / make-up air",
         "lighting_public_kw": "Public lighting", "other_kw": "Unmetered 'other'", "ahu_kw": "AHUs", "lighting_kw": "Lighting",
         "pumps_pool_kw": "Pumps and pool", "chiller_ch1_kw": "Chiller CH-1", "chiller_ch2_kw": "Chiller CH-2", "chiller_ch3_kw": "Chiller CH-3",
         "chw_pumps_kw": "CHW pumps", "cw_pumps_ct_kw": "Condenser pumps / towers", "ahu_banquet_kw": "Banquet AHUs", "laundry_kw": "Laundry",
         "rooms_fcu_plug_kw": "Guest rooms (FCU / plugs)", "lifts_kw": "Lifts", "ev_chargers_kw": "EV chargers", "water_heating_kw": "Water heating",
         "pool_kw": "Pool", "chillers_kw": "Chillers", "rooms_kw": "Guest rooms"}
CAUSE = {"ahu_public_kw": ("Lobby / corridor AHUs left on day speed or schedule overnight",
                           "Check each public AHU's speed and BMS time schedule at 02:00; are back-of-house and closed outlets still served?"),
         "ahu_heaters_kw": ("Re-heat coils on overnight while cooling runs",
                            "Check re-heat valve positions and AHU discharge setpoints at 02:00; is re-heat on with chilled water flowing?"),
         "kitchen_kw": ("Hot-holding, ovens or extraction left on after the kitchen closes; cold rooms with doors ajar",
                        "Walk the kitchens after closing: hot-holding, ovens, salamanders, cold-room doors and defrost cycles"),
         "kitchen_exhaust_mua_kw": ("Extract / make-up air left running with no cooking", "Confirm no cooking, then check the exhaust and MUA fan status and the hood interlock"),
         "lighting_public_kw": ("Areas lit at full level with nobody there", "Walk the back-of-house, car park, façade and landscape at 02:00; note any area at full level"),
         "lighting_kw": ("Areas lit at full level with nobody there", "Walk the back-of-house, car park, façade and lawns at 02:00; note any area at full level"),
         "other_kw": ("Unmetered loads: IT / server rooms, signage, ventilation fans, small equipment left on",
                      "Read the unmetered distribution boards at 02:00 vs 15:00; list what draws power with nobody using it"),
         "ahu_kw": ("AHUs left on day speed or schedule overnight", "Check each AHU's speed and BMS time schedule at 02:00"),
         "pumps_pool_kw": ("Pumps running outside their schedule", "Check which pumps run at 02:00 against the filtration and transfer schedules (filtration ≥ 8 h a day stays)")}


# ---- inputs ------------------------------------------------------------------------------------------------------------------
def _flags(folder: Path, site: str) -> pd.DataFrame:
    """Hourly site flags: DG and meter-fault / imputed hours are never counted."""
    if site == "GGN":
        h = gurugram_hourly(pd.read_parquet(folder / "meter_ggn_15min.parquet"))
        return h[["timestamp", "is_dg", "has_meter_fault"]]
    m = pd.read_parquet(folder / f"meter_{site.lower()}_hourly.parquet")
    fault = m["is_imputed"] if "is_imputed" in m else False
    return m.assign(has_meter_fault=fault)[["timestamp", "is_dg", "has_meter_fault"]]


RULE_CH = {"AHU_HAND_MODE": ["ahu_banquet_kw"], "CHILLER_STAGING_LOW_LOAD": ["chiller_ch1_kw", "chiller_ch3_kw", "chillers_kw"],
           "CHW_SETPOINT_LOW": ["chiller_ch1_kw", "chiller_ch3_kw"], "HEAT_COOL_FIGHT": ["ahu_heaters_kw", "ahu_public_kw"],
           "KITCHEN_EXHAUST_OFF_HOURS": ["kitchen_exhaust_mua_kw"], "LAUNDRY_IN_PEAK": ["laundry_kw"], "POOL_PUMP_OFF_SCHEDULE": ["pumps_pool_kw"],
           "LIGHTING_LEFT_ON": ["lighting_kw"], "CHILLER_PART_LOAD_INEFFICIENCY": ["chillers_kw"], "EV_CHARGER_NIGHT_ON": ["ev_chargers_kw"],
           "DEMAND_NEAR_CONTRACT": [], "CONTRACT_DEMAND_BREACH": []}


def _alert_hours(folder: Path, site: str, channels: list) -> dict:
    """Per channel: the hours a detector alert already counts as waste (an unknown rule - residual, PF - blocks every channel)."""
    out = {c: set() for c in channels}
    for f in ("alerts.parquet", "alerts_demand_ev.parquet"):
        p = folder / f
        if not p.exists():
            continue
        a = pd.read_parquet(p).query("site == @site")
        for r in a.itertuples():
            hrs = pd.date_range(pd.Timestamp(r.start).floor("h"), pd.Timestamp(r.end).ceil("h"), freq="h", inclusive="left")
            for c in RULE_CH.get(r.rule, channels):
                if c in out:
                    out[c].update(hrs)
    return out


def _rate(folder: Path, site: str) -> float:
    """₹ per kWh at night: energy (+ municipal tax) + FSA + duty + the off-peak rebate, per kVAh, divided by the hotel's PF."""
    t = pd.read_parquet(folder / "tariffs.parquet").query("site == @site").set_index("component").rate
    b = pd.read_parquet(folder / "monthly_bills.parquet").query("site == @site")
    pf = b.grid_kwh.sum() / b.grid_kvah.sum()
    kvah = t["Energy charge"] * (1 + t["Municipal tax"]) + t["Fuel surcharge adjustment (FSA)"] + t["Electricity duty"] + t["Off-peak ToD rebate"]
    return float(kvah / pf)


def _frame(folder: Path, site: str) -> tuple[pd.DataFrame, list]:
    if site == "GGN":
        sub = pd.read_parquet(folder / "sub_ggn_hourly.parquet")[["timestamp", *GGN_CH]]
        ch = GGN_CH
    else:
        sub = pd.read_parquet(folder / "sub_jai_goa_hourly.parquet").query("site == @site")[["timestamp", *JG_CH]]
        ch = JG_CH
    d = sub.merge(_flags(folder, site), on="timestamp", how="left")
    w = pd.read_parquet(folder / "weather_hourly.parquet").query("site == @site")[["timestamp", "temp_c"]]
    d = d.merge(w, on="timestamp", how="left")
    d["hour"] = d.timestamp.dt.hour
    d = d[d.hour.isin(NIGHT)].copy()
    d["night"] = d.timestamp.dt.normalize()
    occ = pd.read_parquet(folder / "occupancy_daily.parquet").query("site == @site")[["date", "occupancy_pct"]]
    occ = occ.assign(night=pd.to_datetime(occ.date) + pd.Timedelta(days=1))[["night", "occupancy_pct"]]   # 00-05 h guests checked in the day before
    d = d.merge(occ, on="night", how="left")
    d["ok"] = ~(d.is_dg.fillna(False).astype(bool) | d.has_meter_fault.fillna(False).astype(bool))
    return d, ch


def _event_nights(folder: Path, site: str) -> set:
    """Jaipur / Goa: nights after an event (event lighting is a daily-plan lever there)."""
    ev = pd.read_parquet(folder / "events.parquet").query("site == @site")
    return set(pd.to_datetime(ev.date) + pd.Timedelta(days=1))


# ---- the audit ---------------------------------------------------------------------------------------------------------------
def good_night(x: pd.DataFrame, value: str) -> pd.Series:
    """Per night: the good-night reference = mean of the 10th-20th percentile band of the K nearest other nights (occupancy, temperature)."""
    z = x[["occupancy_pct", "temp"]].to_numpy(dtype=float)
    z = (z - np.nanmean(z, axis=0)) / np.nanstd(z, axis=0)
    v = x[value].to_numpy(dtype=float)
    out = np.empty(len(x))
    for i in range(len(x)):
        dist = np.hypot(*(z - z[i]).T)
        dist[i] = np.inf
        nb = v[np.argsort(dist)[:K]]
        lo, hi = np.percentile(nb, REF_Q)
        band = nb[(nb >= lo) & (nb <= hi)]
        out[i] = band.mean() if len(band) else lo
    return pd.Series(out, index=x.index)


def audit_site(folder: Path, site: str) -> dict:
    d, ch = _frame(folder, site)
    alert_h = _alert_hours(folder, site, ch)
    rate = _rate(folder, site)
    ev_n = _event_nights(folder, site) if site != "GGN" else set()
    rows, monthly = [], []
    for c in ch:
        x = d[d.ok & ~d.timestamp.isin(alert_h[c])].copy()
        if c == "lighting_kw":
            x = x[~x.night.isin(ev_n)]
        if c == "kitchen_exhaust_mua_kw":                              # exhaust must run while the kitchen cooks
            k = d.kitchen_kw
            cooking = d.kitchen_kw > k.median() + 5 * (k - k.median()).abs().median() + 1.0
            x = x[~x.timestamp.isin(d.timestamp[cooking])]
        n = x.groupby("night").agg(kw=(c, "mean"), hours=(c, "size"), temp=("temp_c", "mean"), occupancy_pct=("occupancy_pct", "first"))
        n = n[(n.hours >= MIN_HOURS) & n.occupancy_pct.notna() & n.temp.notna()]
        r = dict(site=site, channel=c, label=LABEL.get(c, c), typical_kw=float(n.kw.median()) if len(n) else 0.0, nights=int(len(n)))
        if len(n) < K + 1:
            rows.append(dict(r, good_kw=r["typical_kw"], excess_kw=0.0, share=0.0, r2=np.nan, ac1=np.nan, loose_inr=0.0, kwh=0.0, inr=0.0, status="too few nights"))
            continue
        # how much occupancy and outdoor temperature explain (linear fit across nights)
        A = np.c_[np.ones(len(n)), n.occupancy_pct, n.temp]
        coef, *_ = np.linalg.lstsq(A, n.kw, rcond=None)
        res = n.kw - A @ coef
        r2 = 1 - res.var() / n.kw.var() if n.kw.var() > 0 else 0.0
        n["ref"] = good_night(n, "kw")
        n["excess"] = n.kw - n.ref
        share = float((n.excess > METER_TOL * n.ref.abs().clip(lower=1.0)).mean())
        med = float(n.excess.median())
        ex = n.excess.reindex(pd.date_range(n.index.min(), n.index.max()))
        ac1 = float(ex.autocorr(1)) if ex.notna().sum() > 2 else 0.0
        ac1 = 0.0 if np.isnan(ac1) else ac1
        persist = ac1 > 2 / np.sqrt(len(n))
        above = share > 0.5 and med > 0
        repeat = above and persist
        kwh = med * float(n.hours.sum()) if repeat else 0.0
        status = (("excluded: " + EXCLUDED[c]) if c in EXCLUDED else "clear repeatable excess" if repeat
                  else "random night-to-night scatter, not a persistent excess" if above else "no repeatable excess")
        claim = repeat and c not in EXCLUDED
        rows.append(dict(r, good_kw=float(n.ref.median()), excess_kw=med if repeat else 0.0, share=share, r2=float(r2), ac1=ac1,
                         loose_inr=med * float(n.hours.sum()) * rate if (above and c not in EXCLUDED) else 0.0,
                         kwh=kwh if claim else 0.0, inr=kwh * rate if claim else 0.0, kwh_if_counted=kwh, status=status,
                         cause=CAUSE.get(c, ("", ""))[0], walk=CAUSE.get(c, ("", ""))[1]))
        m = n.assign(month=n.index.to_period("M").astype(str)).groupby("month").agg(kw=("kw", "mean"), occ=("occupancy_pct", "mean"), temp=("temp", "mean"),
                                                                                      fitted=("kw", lambda s: float((A @ coef)[n.index.get_indexer(s.index)].mean())))
        monthly.append(m.assign(channel=c))
    t = pd.DataFrame(rows)
    mon = pd.concat(monthly).reset_index() if monthly else pd.DataFrame()
    bills = pd.read_parquet(folder / "monthly_bills.parquet").query("site == @site")
    return dict(site=site, rate=rate, table=t, monthly=mon, bill=float(bills.total_energy_cost_inr.sum()))


def audit(folder: Path = ORIG) -> dict:
    return {s: audit_site(folder, s) for s in SITES}


# ---- report ------------------------------------------------------------------------------------------------------------------
def _site_md(a: dict, live: bool) -> list:
    t = a["table"]
    claimed = t[t.inr > 0]
    L = [f"### {SITES[a['site']]} — ₹{claimed.inr.sum():,.0f}/yr ({claimed.inr.sum() / a['bill'] * 100:.2f} % of the year's bill ₹{a['bill'] / 1e5:,.1f} lakh)", "",
         f"Night price ₹{a['rate']:.2f}/kWh (off-peak, rebate applied).", "",
         "| Channel | Typical night kW | Good-night kW | Excess kW (median) | Nights above ref | Night-to-night r | Occ./temp. R² | Excess kWh/yr | ₹/yr | Status |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for r in t.sort_values(["inr", "loose_inr"], ascending=False).itertuples():
        f2 = lambda v: "" if pd.isna(v) else f"{v:.2f}"
        L.append(f"| {r.label} | {r.typical_kw:.1f} | {r.good_kw:.1f} | {r.excess_kw:.2f} | {r.share:.0%} | {f2(r.ac1)} | {f2(r.r2)} | "
                 f"{r.kwh:,.0f} | ₹{r.inr:,.0f} | {r.status} |")
    loose = t.loose_inr.sum()
    if loose > claimed.inr.sum():
        L += ["", f"Without the persistence test (b) the method would have claimed ₹{loose:,.0f}/yr here; that difference is random night-to-night "
                  "scatter around the good-night level, not waste, so it is not counted."]
    if not live and len(claimed):
        L += ["", "| Channel | Likely cause | What to check on a night walk-round (02:00) |", "|---|---|---|"]
        L += [f"| {r.label} | {r.cause} | {r.walk} |" for r in claimed.itertuples()]
    return L + [""]


def write_md(orig: dict, live: dict | None) -> Path:
    L = ["# Night base-load audit (00:00–05:00)", "",
         "Each sub-meter channel's night draw against its own **good nights**: the 10th–20th percentile of the 30 nights with the most similar "
         "occupancy and outdoor temperature. The excess is claimed only where it **repeats** (more than half of the nights above the reference by "
         "more than the sub-meters' ±1 % accuracy), at its **median** nightly size × the night hours checked, priced at each hotel's off-peak rate. "
         "Hours already counted as alert waste, DG and meter-fault hours, the daily plan's levers and everything that must run at night are excluded "
         "(see `tools/night_baseload.py`). Recommend only: confirm each item on a night walk-round before acting.", "",
         "R² is how much of the night-to-night variation occupancy and outdoor temperature explain (linear fit); the excess is what they don't.", "",
         "## Original year (Oct 2025 – Sep 2026): the savings claim", ""]
    tot = sum(a["table"].inr.sum() for a in orig.values())
    bill = sum(a["bill"] for a in orig.values())
    for a in orig.values():
        L += _site_md(a, False)
    loose = sum(a["table"].loose_inr.sum() for a in orig.values())
    L += [f"**Group: ₹{tot:,.0f}/yr, {tot / bill * 100:.2f} % of the group bill (₹{bill / 1e7:.2f} cr)** (without the persistence test: ₹{loose:,.0f}). "
          "Claimed kWh goes into the savings plan as is (src/savings.py); the earlier assumed 30 % night-lighting cut is no longer counted.", "",
          "**What it means.** " + ("No channel shows a persistent excess over its own good nights: the night base load is already as low as these hotels' "
          "best similar nights. Any further cut means a level lower than any night the meters have seen (switching areas or equipment off), which "
          "data cannot size; that is what the night walk-round below is for." if tot == 0 else
          "The channels above draw more than their own good nights, night after night; confirm each on a night walk-round before acting."), ""]
    L += ["### Night walk-round checklist (02:00, all hotels)", "", "| Area | What to check |", "|---|---|"]
    L += [f"| {LABEL[c]} | {CAUSE[c][1]} |" for c in ("ahu_public_kw", "ahu_heaters_kw", "kitchen_kw", "kitchen_exhaust_mua_kw", "lighting_public_kw", "other_kw", "pumps_pool_kw")]
    L += [""]
    L += ["### Night kW by month (all audited channels, before exclusions)", "", "| Hotel | Month | Night kW | Occupancy | Night temp °C |", "|---|---|---:|---:|---:|"]
    for a in orig.values():
        m = a["monthly"]
        if len(m):
            g = m.groupby("month").agg(kw=("kw", "sum"), occ=("occ", "first"), temp=("temp", "first"))
            L += [f"| {SITES[a['site']]} | {k} | {r.kw:.0f} | {r.occ:.0%} | {r.temp:.1f} |" for k, r in g.iterrows()]
    if live:
        lt = sum(a["table"].inr.sum() for a in live.values())
        lb = sum(a["bill"] for a in live.values())
        L += ["", "## Live year (Oct 2026 – Sep 2027, synthetic): a check, not a claim", "",
              f"Same method on the live year: ₹{lt:,.0f}/yr, {lt / lb * 100:.2f} % of its bill (₹{lb / 1e7:.2f} cr). The live year is built from copied "
              "weeks of the original year with a steady load-growth factor (tools/make_live_year.py), which makes neighbouring nights alike: that is "
              "where most of its night-to-night persistence comes from, so a live-year excess is a property of the generator, not evidence of waste.", ""]
        for a in live.values():
            L += _site_md(a, True)
    out = ROOT / "data" / "night_baseload.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    o = audit(ORIG)
    lv = audit(LIVE) if (LIVE / "sub_ggn_hourly.parquet").exists() else None
    p = write_md(o, lv)
    for s, a in o.items():
        t = a["table"]
        print(s, f"₹{t.inr.sum():,.0f}/yr", t[t.inr > 0][["label", "typical_kw", "good_kw", "excess_kw", "share", "kwh", "inr"]].round(2).to_dict("records"))
    if lv:
        print("live:", {s: round(a["table"].inr.sum()) for s, a in lv.items()})
    print("wrote", p)
