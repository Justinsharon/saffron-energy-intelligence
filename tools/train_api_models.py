"""Jaipur and Goa plan models and per-day references for the plan API (api/main.py), saved to models/ beside Gurugram's.

Why a separate script: Gurugram's plan models (tools/export_api_models.py) lean on sub-meters Jaipur and Goa don't have (per-chiller kW,
CHW setpoint, banquet AHUs, water heating, EV). Here the plan uses only levers the Jaipur / Goa sub-meters can size and later check
(sub_jai_goa_hourly: total chillers_kw, chiller_load_tr, lighting_kw, pumps_pool_kw, laundry_kw), and every hotel fact - chillers, pool
pumps, laundry, venues, tariff windows, contract demand - is read from that hotel's own rows of the equipment register, events calendar
and tariff table. Nothing is carried over from Gurugram.

Per hotel, trained on the ORIGINAL year only (Oct 2025 - Sep 2026; never refitted at run time), with the same features as Gurugram
(weather, rooms sold, guests, covers, events, day type, hour):
  kw   - src/baseline.py ensemble (ridge + LightGBM) on total_kwh (grid + DG; DG, imputed and fault hours excluded);
  tr   - the same method on chiller_load_tr (cooling load);
  kva  - src/forecast.py's day-ahead model (adds "yesterday" lags) on the hourly maximum kVA.
Accuracy: leave-one-month-out CV(RMSE) and NMBE per model, as notebook 03 scores the baseline.

Writes models/plan_models_<SITE>.joblib, context_<SITE>.parquet (live-year context, last year's events cleared, lags from 52 weeks
earlier), refs_<SITE>.json (per date: last year's matched days), live_meters_<SITE>.parquet (simulated live-year meters for plan vs
actual) and meta.json["sites"][SITE] (config, tariff, curves, accuracy, peak-risk calibration, training ranges).

Run: uv run python tools/train_api_models.py      (also run at the end of tools/export_api_models.py; a few minutes)
"""
import json
import re
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
import export_plan_inputs as EP  # noqa: E402
import forecast  # noqa: E402
from baseline import GBM_FEATURES, build_features, cv_rmse, nmbe  # noqa: E402
from features import CONTRACT_KVA, ROOMS, SITES as SITE_NAMES  # noqa: E402
from plan_models import EV_COLS, Ens, predict  # noqa: E402

OUT = ROOT / "models"
SITES = ("JAI", "GOA")
FILTRATION_MIN_H = 8                  # CONTEXT.md §9: pool filtration >= 8 h a day (also the register's operating limit for POOL-P)
POOR_KWTR = 1.15                      # an hour runs at "poor kW/TR" when it is 15 % above the hotel's normal for that load
TR_EDGES = [0, 40, 60, 80, 100, 120, 140, 160, 400]
KEEP = sorted(set(GBM_FEATURES + forecast.LAGS + EV_COLS + ["timestamp", "hour", "dow", "weekend", "month", "temp_c", "rel_humidity_pct", "rain_mm",
                                                              "rooms_sold", "occupancy_pct", "guests_in_house", "covers_served_fnb", "cdh", "temp_3h",
                                                              "cdh_24h", "hdh"]))


# ---- what the hotel has: its own register, events calendar and tariff rows ---------------------------------------------------------
def _window(text: str) -> list:
    a, b = re.search(r"(\d\d):00\D+(\d\d):00", text).groups()
    return [int(a), int(b)]


def site_config(site: str) -> dict:
    reg = pd.read_parquet(EP.CLEAN / "equipment_register.parquet").query("site == @site")
    ev = pd.read_parquet(EP.CLEAN / "events.parquet").query("site == @site")
    t = pd.read_parquet(EP.LIVE / "tariffs.parquet").query("site == @site").set_index("component")
    ch = reg[reg.description.str.contains("chiller", case=False)].iloc[0]
    n, cap = re.search(r"(\d+)\s*×\s*(\d+)\s*TR", ch.rating).groups()
    units = [float(cap)] * int(n)
    floor = float(re.search(r"(\d+(?:\.\d+)?)\s*°C", ch.operating_limit).group(1))
    lau = reg[reg.equipment_id == "LAUNDRY"].iloc[0]
    pool = reg[reg.description.str.contains("pool", case=False)]
    pool_cfg = None
    if len(pool):
        p = pool.iloc[0]
        m = re.search(r"(\d+)\s*h", str(p.operating_limit))
        pool_cfg = dict(id=p.equipment_id, description=p.description, rating=p.rating, kw=float(p.connected_kw),
                        min_hours=max(FILTRATION_MIN_H, int(m.group(1)) if m else 0))
    lights = {r.serves: dict(id=r.equipment_id, kw=float(r.connected_kw)) for r in reg[reg.description.str.contains("lighting", case=False)].itertuples()}
    venues = {}
    for v, g in ev.groupby("venue"):
        venues[v] = dict(event_type=g.event_type.mode().iloc[0], events=int(len(g)), max_guests=int(g.guests.max()),
                         start_hours=[int(g.start_time.str[:2].astype(int).min()), int(g.start_time.str[:2].astype(int).max())],
                         social=bool(g.event_type.str.contains("edding|MICE").any()), lighting=lights.get(v))
    return dict(site=site, hotel=SITE_NAMES[site], rooms=ROOMS[site],
                chillers=dict(id=ch.equipment_id, description=ch.description, units_tr=units, rating=ch.rating, floor_c=floor),
                laundry=dict(id="LAUNDRY", kw=float(lau.connected_kw)), pool=pool_cfg, venues=venues,
                peak=_window(t.loc["Peak ToD surcharge", "applies"]), offpeak=_window(t.loc["Off-peak ToD rebate", "applies"]),
                cd_kva=float(t.loc["Contract demand", "rate"]))


def tariff_of(site: str) -> dict:
    t = pd.read_parquet(EP.LIVE / "tariffs.parquet").query("site == @site").set_index("component").rate
    return dict(energy=float(t["Energy charge"]), fsa=float(t["Fuel surcharge adjustment (FSA)"]), duty=float(t["Electricity duty"]),
                peak=float(t["Peak ToD surcharge"]), offpeak=float(t["Off-peak ToD rebate"]), penalty=float(t["Excess demand penalty"]))


# ---- frames and models -----------------------------------------------------------------------------------------------------------
def frame(site: str) -> pd.DataFrame:
    """Original-year hourly frame: baseline drivers, kW target, cooling TR, kVA target with the day-ahead lags of src/forecast.py."""
    d = build_features(site)
    s = pd.read_parquet(EP.CLEAN / "sub_jai_goa_hourly.parquet").query("site == @site").drop(columns="site")
    d = d.merge(s, on="timestamp", how="left")
    d["tr_ok"] = d.chiller_load_tr.notna() & ~d.has_meter_fault & ~d.exclude_from_model
    d["y"] = d.kva_max_in_hour.where(d.valid)
    d["lag24"] = d.y.shift(24)
    d["lag168"] = d.y.shift(168)
    d["prev_day_max"] = d.date.map(d.groupby("date").y.max().shift(1))
    d["prev_day_mean"] = d.date.map(d.groupby("date").y.mean().shift(1))
    return d


def fit_all(d: pd.DataFrame) -> dict:
    return dict(kw=Ens().fit(d[d.valid], d.total_kwh[d.valid]), tr=Ens().fit(d[d.tr_ok], d.chiller_load_tr[d.tr_ok]),
                kva=forecast.Forecaster().fit(d))


def lomo(d: pd.DataFrame) -> pd.DataFrame:
    """Leave-one-month-out predictions of the three models (each month predicted by models that never saw it)."""
    p = pd.DataFrame(np.nan, index=d.index, columns=["kw", "tr", "kva"])
    for m in sorted(d.month.unique()):
        te, tr = (d.month == m).to_numpy(), d[d.month != m]
        mods = fit_all(tr)
        p.loc[te, "kw"] = mods["kw"].predict(d[te])
        p.loc[te, "tr"] = np.clip(mods["tr"].predict(d[te]), 0, None)
        ok = te & d[forecast.LAGS].notna().all(axis=1).to_numpy()
        p.loc[ok, "kva"] = mods["kva"].predict(d[ok])
    return p


def accuracy(d: pd.DataFrame, p: pd.DataFrame) -> dict:
    out = {}
    for key, y, mask in (("kw", "total_kwh", d.valid), ("tr", "chiller_load_tr", d.tr_ok), ("kva", "y", d.y.notna() & p.kva.notna())):
        v = pd.DataFrame(dict(a=d[y], p=p[key], month=d.month))[mask.to_numpy()]
        mm = v.groupby("month").agg(a=("a", "mean"), p=("p", "mean"))
        out[key] = dict(hourly_cv_rmse_pct=round(cv_rmse(v.a, v.p), 1), hourly_nmbe_pct=round(nmbe(v.a, v.p), 2),
                        monthly_cv_rmse_pct=round(cv_rmse(mm.a, mm.p), 1), hours=int(len(v)))
    out["scheme"] = "leave-one-month-out on Oct 2025 – Sep 2026"
    return out


def risk_cal(d: pd.DataFrame, p: pd.DataFrame, cd: float) -> dict:
    """Peak-risk calibration from the out-of-fold kVA forecasts: bias (actual / forecast daily peak), the 90 % upper factor and the ratios
    for P(over the contract). No load-stacking study exists for this hotel, so the stacking increment is 0 (said in stack_basis)."""
    x = pd.DataFrame(dict(date=d.date, a=d.y, p=p.kva)).dropna().groupby("date").agg(a=("a", "max"), p=("p", "max"), n=("a", "size"))
    x = x[x.n >= 20]
    r = (x.a / x.p).to_numpy()
    bias = float(np.median(r))
    ratios = r / bias
    return dict(bias=round(bias, 5), upper_factor=round(float(np.quantile(ratios, 0.90)), 5), ratios=[round(float(v), 5) for v in ratios],
                stack_increment=0.0, stack_basis="no load-stacking study for this hotel (its peak stayed far below the contract last year)",
                stack_table=[], cd=cd, warn=round(0.92 * cd, 1), watch_frac=forecast.WATCH_FRAC)


# ---- last year's behaviour: the yardsticks for the plan's ₹ -----------------------------------------------------------------------
def kwtr_curve(sub: pd.DataFrame) -> dict:
    """Normal plant kW per TR by cooling-load band: the median over the original year (the poor-staging hours are a small minority)."""
    x = sub[sub.chiller_load_tr > 20]
    k = (x.chillers_kw / x.chiller_load_tr).groupby(pd.cut(x.chiller_load_tr, TR_EDGES), observed=False).median()
    vals = k.ffill().bfill().to_numpy()
    return dict(edges=TR_EDGES, values=[round(float(v), 4) for v in vals])


def curve_at(tr, curve: dict) -> float:
    for hi, v in zip(curve["edges"][1:], curve["values"]):
        if tr <= hi:
            return v
    return curve["values"][-1]


def lighting_profile(sub: pd.DataFrame, ev: pd.DataFrame) -> list:
    """Normal lighting kW by hour on days with no event (event days and the morning after excluded)."""
    days = set(ev.date) | set(ev.date + pd.Timedelta(days=1))
    x = sub[~sub.timestamp.dt.normalize().isin(days)]
    return [round(float(v), 1) for v in x.groupby(x.timestamp.dt.hour).lighting_kw.median().reindex(range(24))]


def _end(r) -> pd.Timestamp:
    if r.ends_after_midnight:
        return pd.Timestamp(r.date) + pd.Timedelta(days=1, hours=1)
    return pd.Timestamp(r.date) + pd.Timedelta(hours=int(r.end_time[:2]), minutes=int(r.end_time[3:]))


def venue_lighting(sub: pd.DataFrame, ev: pd.DataFrame, norm: list) -> dict:
    """Per venue: event lighting kW (median extra lighting while guests are in) and the mean kWh of lighting left on after events ended
    (continuous run above half the event kW from 30 min after the end, up to 8 h) - last year's EVENT_LIGHTING_LEFT_ON pattern in meters."""
    s = sub.set_index("timestamp").lighting_kw
    extra = s - np.array(norm)[s.index.hour]
    out = {}
    for v, g in ev.groupby("venue"):
        during, runon = [], []
        for r in g.itertuples():
            st = pd.Timestamp(r.date) + pd.Timedelta(hours=int(r.start_time[:2]))
            en = _end(r)
            during += list(extra[st: en - pd.Timedelta(hours=1)])
        kw = float(np.median(during)) if during else 0.0
        for r in g.itertuples():
            first = (_end(r) + pd.Timedelta(minutes=30)).ceil("h")
            run = 0.0
            for val in extra[first: first + pd.Timedelta(hours=7)]:
                if val <= max(5.0, 0.5 * kw):
                    break
                run += val
            runon.append(run)
        out[v] = dict(event_kw=round(kw, 1), left_on_kwh=round(float(np.mean(runon)), 1), events=len(runon),
                      events_left_on=int(sum(x > 0 for x in runon)))
    return out


def pool_schedule(sub: pd.DataFrame, pool: dict) -> dict:
    """Usual filtration schedule on normal days: hours when the pumps (pumps_pool_kw above the day's minimum) usually run, and their kW."""
    x = sub.assign(date=sub.timestamp.dt.normalize(), hour=sub.timestamp.dt.hour)
    x["run"] = x.pumps_pool_kw - x.groupby("date").pumps_pool_kw.transform("min")
    on = x.run > 0.5 * pool["kw"]
    hours_per_day = on.groupby(x.date).sum()
    normal = hours_per_day[hours_per_day <= hours_per_day.median() + 1].index          # days that ran the usual hours (not 24 h)
    y = x[x.date.isin(normal)]
    share = (y.run > 0.5 * pool["kw"]).groupby(y.hour).mean()
    hours = [int(h) for h in share.index if share[h] >= 0.5]
    kw = float(y[y.hour.isin(hours)].run.median())
    return dict(hours=hours, kw=round(kw, 1), normal_days=int(len(normal)))


def matched_refs(daily: pd.DataFrame, sub: pd.DataFrame, cfg: dict, curve: dict, day: pd.Timestamp, tr_mean: float) -> dict:
    """Matched days (same month, same day type, daily mean TR within ±15 %, else the 5 closest) and how the plant, laundry and pool ran then."""
    c = daily[(daily.month == day.month) & (daily.wk == int(day.day_of_week >= 5))]
    m = c[(c.tr - tr_mean).abs() <= 0.15 * tr_mean]
    if len(m) < 3:
        m = c.iloc[(c.tr - tr_mean).abs().argsort()[:5]]
    s = sub[sub.timestamp.dt.normalize().isin(m.index)].copy()
    s["hour"], s["date"] = s.timestamp.dt.hour, s.timestamp.dt.normalize()
    normal = s.chiller_load_tr.map(lambda t: curve_at(t, curve))
    kwtr = s.chillers_kw / s.chiller_load_tr.where(s.chiller_load_tr > 20)
    s["poor_kwh"] = (s.chillers_kw - s.chiller_load_tr * normal).where(kwtr > POOR_KWTR * normal, 0.0).clip(lower=0)
    nd = max(1, s.date.nunique())
    pk = s.hour.map(lambda h: in_win(h, cfg["peak"]))
    out = dict(matched_days=[d.strftime("%Y-%m-%d") for d in m.index],
               poor_kwh_ly=[round(float(v), 2) for v in s.groupby("hour").poor_kwh.sum().reindex(range(24)).fillna(0) / nd],
               laundry_peak_kwh=round(float(s[pk].laundry_kw.sum() / nd), 1))
    if cfg.get("pool"):
        run = s.pumps_pool_kw - s.groupby("date").pumps_pool_kw.transform("min")
        out_h = ~s.hour.isin(cfg["pool"]["schedule"]["hours"]) & (run > 0.5 * cfg["pool"]["kw"])
        out["pool_outside_kwh"] = round(float(run[out_h].sum() / nd), 1)
    return out


def in_win(h: int, w) -> bool:
    a, b = w
    return a <= h < b if a < b else (h >= a or h < b)


# ---- main --------------------------------------------------------------------------------------------------------------------------
def build(site: str) -> dict:
    with EP.data(EP.CLEAN):
        cfg = site_config(site)
        d = frame(site)
        print(f"{site}: fitting on {d.timestamp.min():%d %b %Y} – {d.timestamp.max():%d %b %Y} ...", flush=True)
        p = lomo(d)
        acc = accuracy(d, p)
        models = fit_all(d)
    joblib.dump(models, OUT / f"plan_models_{site}.joblib", compress=3)
    sub_o = pd.read_parquet(EP.CLEAN / "sub_jai_goa_hourly.parquet").query("site == @site").drop(columns="site")
    ev_o = pd.read_parquet(EP.CLEAN / "events.parquet").query("site == @site")
    curve = kwtr_curve(sub_o)
    norm = lighting_profile(sub_o, ev_o)
    vl = venue_lighting(sub_o, ev_o, norm)
    for v in cfg["venues"]:
        cfg["venues"][v].update(vl[v])
    if cfg["pool"]:
        cfg["pool"]["schedule"] = pool_schedule(sub_o, cfg["pool"])
    cfg["lighting_norm_kw"] = norm

    with EP.data(EP.LIVE):
        live = build_features(site)
    lag = d.set_index("timestamp")[forecast.LAGS]
    live[forecast.LAGS] = lag.reindex(live.timestamp - pd.Timedelta(days=364)).to_numpy()
    ctx = EP.with_events(live, [])
    ctx[KEEP].to_parquet(OUT / f"context_{site}.parquet", index=False)

    base = predict(models, ctx, site)
    daily = (sub_o.assign(date=sub_o.timestamp.dt.normalize()).groupby("date").chiller_load_tr.mean().to_frame("tr")
             .assign(month=lambda x: x.index.month, wk=lambda x: (x.index.day_of_week >= 5).astype(int)))
    refs = {}
    days = sorted(ctx.timestamp.dt.normalize().unique())
    for dd in days[1:-1]:
        msk = (ctx.timestamp.dt.normalize() == dd).to_numpy()
        refs[pd.Timestamp(dd).strftime("%Y-%m-%d")] = matched_refs(daily, sub_o, cfg, curve, pd.Timestamp(dd), float(np.mean(base["tr"][msk])))
    (OUT / f"refs_{site}.json").write_text(json.dumps(refs, separators=(",", ":")), encoding="utf-8")

    sub_l = pd.read_parquet(EP.LIVE / "sub_jai_goa_hourly.parquet").query("site == @site").drop(columns="site")
    ml = pd.read_parquet(EP.LIVE / f"meter_{site.lower()}_hourly.parquet")[["timestamp", "kva_max_in_hour", "total_kwh"]].rename(columns={"kva_max_in_hour": "kva"})
    cols = ["timestamp", "chillers_kw", "chiller_load_tr", "lighting_kw", "pumps_pool_kw", "laundry_kw"]
    sub_l[cols].merge(ml, on="timestamp", how="left").to_parquet(OUT / f"live_meters_{site}.parquet", index=False)

    bills = pd.read_parquet(EP.CLEAN / "monthly_bills.parquet").query("site == @site")
    occ = pd.read_parquet(EP.CLEAN / "occupancy_daily.parquet").query("site == @site")
    return dict(site=site, hotel=SITE_NAMES[site], trained_on="Oct 2025 – Sep 2026 (original year only; never refitted)",
                dates=[min(refs), max(refs)], context="live year Oct 2026 – Sep 2027 (synthetic, simulated meters); last year's events cleared",
                pf=round(float(bills.grid_kwh.sum() / bills.grid_kvah.sum()), 4), tariff=tariff_of(site), config=cfg, curve=curve,
                accuracy=acc, risk=risk_cal(d, p, cfg["cd_kva"]),
                ranges=dict(rooms=[0, ROOMS[site]], guests_in_house=[int(occ.guests_in_house.min()), int(occ.guests_in_house.max())],
                            covers=[int(occ.covers_served_fnb.min()), int(occ.covers_served_fnb.max())],
                            training_period=[d.timestamp.min().strftime("%Y-%m-%d"), d.timestamp.max().strftime("%Y-%m-%d")],
                            temp_c=[round(float(d.temp_c.min()), 1), round(float(d.temp_c.max()), 1)],
                            event_guests={v: c["max_guests"] for v, c in cfg["venues"].items()},
                            event_start_hours={v: c["start_hours"] for v, c in cfg["venues"].items()}))


def main(sites=SITES):
    OUT.mkdir(exist_ok=True)
    meta_path = OUT / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.setdefault("sites", {})
    for site in sites:
        m = build(site)
        meta["sites"][site] = m
        a = m["accuracy"]
        print(f"{site}: CV(RMSE) hourly kW {a['kw']['hourly_cv_rmse_pct']} %, cooling TR {a['tr']['hourly_cv_rmse_pct']} %, "
              f"peak kVA {a['kva']['hourly_cv_rmse_pct']} %  ({a['scheme']}); {len(json.loads((OUT / f'refs_{site}.json').read_text()))} dates", flush=True)
    meta_path.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main(tuple(a.upper() for a in sys.argv[1:]) or SITES)
