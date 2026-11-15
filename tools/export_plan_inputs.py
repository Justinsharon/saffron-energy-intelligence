"""Per-day inputs for the Gurugram operating plan (src/operating_plan.py, web/src/plan.ts): web/public/data/plan/<date>.json + index.json.

For each date from today (IST) for the next 60 days:
  * Context template: the live year's day (data/live: weather, rooms sold, covers) with last year's events cleared; the team enters
    bookings in the app. Weather is the template's; the browser shifts it to the real forecast with the per-°C response.
  * Base hourly forecast from frozen models fitted on the original year only (Oct 2025 - Sep 2026), never refitted:
      kW   - src/baseline.py ensemble (ridge + LightGBM) on total_kwh;
      kVA  - src/forecast.py day-ahead model; its "yesterday" lags come from the same weekday 52 weeks earlier, so no future
             live-year meter readings are used;
      TR   - a cooling-load model on sub_ggn_hourly.chiller_load_tr with the same features and method as the baseline
             (its leave-one-month-out CV(RMSE) is reported in index.json).
  * Responses by central finite differences around the base day: d(kW)/d(room) and d(kW)/d(guest) (each with the other held fixed),
    d(kW)/d(cover), d(kW)/d(°C), d(TR)/d(°C), d(TR)/d(room), d(TR)/d(guest),
    and per-100-guest banquet responses (kW and TR) for hours -3..+2 around an event's start and end, plus the mid-event level. The
    model has no venue feature, so Hall A and Hall B share the conference response; A+B uses the wedding (evening, social) response.
  * Last year's behaviour on matched days (same month, same day type, similar cooling load; original year), which the plan's ₹ savings
    are measured against: plant kW/TR by hour, laundry and water-heating boost kWh in the peak window, EV draw by hour, and banquet AHU
    run-on after events. Plus the live tariff (₹ rates) and the site PF.

index.json also carries the peak-risk calibration of src/peak_risk.py (bias, 90 % upper factor, earlier days' actual/forecast ratios,
stacking increment), so the browser applies the same risk logic to the plan's own forecast.

Run: uv run python tools/export_plan_inputs.py [first_date] [days]   (default: 2 Oct 2026 - the first live-year day - to 60 days ahead)     (needs data/live; about a minute)
"""
import json
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import baseline  # noqa: E402
import features  # noqa: E402
import forecast  # noqa: E402
import recalibration  # noqa: E402
from baseline import GBM_FEATURES, _event_hours, build_features, cv_rmse, make_gbm, make_ridge, nmbe  # noqa: E402

CLEAN, LIVE = ROOT / "data" / "clean", ROOT / "data" / "live"
OUT = ROOT / "web" / "public" / "data" / "plan"
SITE = "GGN"
EV_COLS = ["ev_guests", "ev_core", "ev_social", "ev_corp", "ev_evening"]
HALLS = {"A": ("Corporate conference", "Banquet Hall A", "09:00", "18:00"), "B": ("Corporate conference", "Banquet Hall B", "09:00", "18:00"),
         "A+B": ("Wedding / social event", "Banquet Hall A + B", "19:00", "23:59")}
D_ROOMS, D_GUESTS, D_COVERS, D_TEMP = 10, 20, 50, 1.0


@contextmanager
def data(folder: Path):
    """Point the modules that read tables at another data folder for a moment (they bind CLEAN at import)."""
    mods = (features, baseline, forecast, recalibration)
    old = [m.CLEAN for m in mods]
    for m in mods:
        m.CLEAN = folder
    try:
        yield
    finally:
        for m, o in zip(mods, old):
            m.CLEAN = o


from plan_models import Ens  # noqa: E402  (ridge + LightGBM ensemble; in src/ so saved models refer to an importable class)


def tr_frame() -> pd.DataFrame:
    d = build_features(SITE)
    s = pd.read_parquet(CLEAN / "sub_ggn_hourly.parquet")[["timestamp", "chiller_load_tr"]]
    d = d.merge(s, on="timestamp", how="left")
    d["tr_ok"] = d.chiller_load_tr.notna() & ~d.has_meter_fault          # BMS load is valid through DG hours; drop meter-fault hours
    return d


def tr_accuracy(d: pd.DataFrame) -> dict:
    """Leave-one-month-out, as notebook 03 scores the baseline."""
    p = pd.Series(np.nan, index=d.index)
    for m in sorted(d.month.unique()):
        te, tr = d.month == m, d[(d.month != m) & d.tr_ok]
        p[te] = Ens().fit(tr, tr.chiller_load_tr).predict(d[te])
    v = d[d.tr_ok].assign(p=p.clip(lower=0))
    mm = v.groupby("month").agg(a=("chiller_load_tr", "mean"), p=("p", "mean"))
    return dict(hourly_cv_rmse_pct=round(cv_rmse(v.chiller_load_tr, v.p), 1), hourly_nmbe_pct=round(nmbe(v.chiller_load_tr, v.p), 2),
                monthly_cv_rmse_pct=round(cv_rmse(mm.a, mm.p), 1), monthly_nmbe_pct=round(nmbe(mm.a, mm.p), 2), hours=int(len(v)),
                scheme="leave-one-month-out on Oct 2025 – Sep 2026")


def with_events(d: pd.DataFrame, rows: list) -> pd.DataFrame:
    x = d.copy()
    x[EV_COLS] = 0.0
    if rows:
        e = _event_hours(pd.DataFrame(rows), late_end_hour=1)
        x = x.drop(columns=EV_COLS[:4]).merge(e, on="timestamp", how="left")
        x[EV_COLS[:4]] = x[EV_COLS[:4]].fillna(0.0)
    x["ev_evening"] = x.ev_guests * x.hour.between(17, 23)
    return x


def matched_refs(orig: pd.DataFrame, sub: pd.DataFrame, day: pd.Timestamp, tr_mean: float) -> dict:
    """Last year's behaviour on matched days: same month, same day type (weekend or not), daily mean TR within ±15 % (else the 5 closest)."""
    o = orig.assign(date=orig.timestamp.dt.normalize())
    daily = o.groupby("date").agg(tr=("chiller_load_tr", "mean"), month=("timestamp", lambda t: t.iloc[0].month), wk=("weekend", "first"))
    c = daily[(daily.month == day.month) & (daily.wk == int(day.day_of_week >= 5))]
    m = c[(c.tr - tr_mean).abs() <= 0.15 * tr_mean]
    if len(m) < 3:
        m = c.iloc[(c.tr - tr_mean).abs().argsort()[:5]]
    s = sub[sub.timestamp.dt.normalize().isin(m.index)].copy()
    s["hour"] = s.timestamp.dt.hour
    s["date"] = s.timestamp.dt.normalize()
    ch = s.chiller_ch1_kw + s.chiller_ch2_kw + s.chiller_ch3_kw
    s["kwtr"] = (ch / s.chiller_load_tr).where(s.chiller_load_tr > 20)
    kwtr = s.groupby("hour").kwtr.mean().reindex(range(24))
    pk = s.hour.between(18, 21)
    wh_floor = s.groupby("date").water_heating_kw.transform("min")
    return dict(matched_days=[d.strftime("%Y-%m-%d") for d in m.index],
                kwtr_ly=[None if pd.isna(v) else round(float(v), 4) for v in kwtr],
                laundry_peak_kwh=round(float(s[pk].groupby("date").laundry_kw.sum().mean()), 1),
                water_peak_kwh=round(float((s.water_heating_kw - wh_floor)[pk].groupby(s.date[pk]).sum().mean()), 1),
                ev_kw=[round(float(v), 2) for v in s.groupby("hour").ev_chargers_kw.mean().reindex(range(24)).fillna(0)])


def ahu_overrun(sub: pd.DataFrame, ev: pd.DataFrame) -> dict:
    """Mean banquet-AHU kWh drawn after an event ended (continuous run from end + 1 h, up to 12 h, above 10 kW). Mean, not median: most events
    end cleanly and a few run on for hours (hand mode), so the expected run-on per event is the fair comparison."""
    a = sub.set_index("timestamp").ahu_banquet_kw
    out = {}
    for style, kind in (("corporate", "Corporate"), ("social", "Wedding")):
        vals = []
        for r in ev[ev.event_type.str.startswith(kind)].itertuples():
            end = pd.Timestamp(r.date) + (pd.Timedelta(days=1, hours=1) if r.ends_after_midnight else pd.Timedelta(hours=int(r.end_time[:2])))
            w = a[end + pd.Timedelta(hours=1): end + pd.Timedelta(hours=12)]
            run = 0.0
            for v in w:                                     # continuous run-on only
                if v <= 10:
                    break
                run += v
            vals.append(run)
        out[style] = round(float(np.mean(vals)), 1) if vals else 0.0
    return out


def risk_calibration() -> dict:
    """src/peak_risk.py's numbers for a forecast made today (full original year, as the live scenarios use): the browser then runs
    peak_risk.assess on the plan's own peak. Thresholds are the guide's (920 / 1,000 kVA, 90 % watch line)."""
    import forecast_app
    import peak_risk as R
    s = forecast_app.state()
    S, d, hot, pf = s["S"], s["d"], s["hot"], s["pf"]
    b = R.bias_factor(S)
    h = R._hist(S)
    ratios = (h.actual_peak / (h.pred_peak * b)).to_numpy()
    inc, tab, basis = R.stacking_increment(d, hot, pf)
    return dict(bias=round(b, 5), upper_factor=round(float(np.quantile(ratios, 0.90)), 5), ratios=[round(float(x), 5) for x in ratios],
                stack_increment=round(inc, 1), stack_basis=basis, stack_table=tab.round(1).to_dict("records"), cd=R.CD, warn=R.WARN,
                watch_frac=forecast.WATCH_FRAC)


def main(first: date, n: int):
    OUT.mkdir(parents=True, exist_ok=True)
    print("fitting frozen models on the original year ...", flush=True)
    with data(CLEAN):
        orig = tr_frame()
        kw_model = Ens().fit(orig[orig.valid], orig.total_kwh[orig.valid])
        tr_model = Ens().fit(orig[orig.tr_ok], orig.chiller_load_tr[orig.tr_ok])
        fo = forecast.build_frame()
        kva_model = forecast.Forecaster().fit(fo)
        F = recalibration.fit(recalibration._frame())
        acc = tr_accuracy(orig)
    print("cooling-load model:", acc, flush=True)
    sub_o = pd.read_parquet(CLEAN / "sub_ggn_hourly.parquet")
    ev_o = pd.read_parquet(CLEAN / "events.parquet").query("site == @SITE")
    overrun = ahu_overrun(sub_o, ev_o)

    bills = pd.read_parquet(CLEAN / "monthly_bills.parquet").query("site == @SITE")
    pf = round(float(bills.grid_kwh.sum() / bills.grid_kvah.sum()), 4)
    t = pd.read_parquet(LIVE / "tariffs.parquet").query("site == @SITE").set_index("component").rate
    tariff = dict(energy=float(t["Energy charge"]), fsa=float(t["Fuel surcharge adjustment (FSA)"]), duty=float(t["Electricity duty"]),
                  peak=float(t["Peak ToD surcharge"]), offpeak=float(t["Off-peak ToD rebate"]), penalty=float(t["Excess demand penalty"]))
    curve = dict(edges=[20, 80, 130, 200, 280], values=[round(float(v), 4) for v in F["curve"].to_numpy()])
    # measured setpoint penalty (5.5 vs 7.0 °C, per load band) -> chiller power per °C; replaces the guide's 3.5 %
    chw_pct = [round(float(v) / 1.5, 4) for v in F["chw_penalty"].reindex(F["curve"].index).fillna(F["chw_penalty"].mean()).to_numpy()]

    with data(LIVE):
        live = build_features(SITE)                     # live-year weather, rooms sold, covers (template context)
    days = [pd.Timestamp(first + timedelta(days=k)) for k in range(n)]
    # one day of warm-up before the first date so the rolling temperature features (3 h, 24 h) are complete
    span = live[(live.timestamp >= days[0] - pd.Timedelta(days=1)) & (live.timestamp < days[-1] + pd.Timedelta(days=2))].reset_index(drop=True)
    lag = fo.set_index("timestamp")[forecast.LAGS]
    span[forecast.LAGS] = lag.reindex(span.timestamp - pd.Timedelta(days=364)).to_numpy()   # "yesterday" from 52 weeks earlier
    base = with_events(span, [])

    def scen(dd):
        dd = forecast.thermal_features(dd)
        return dict(kw=kw_model.predict(dd), tr=np.clip(tr_model.predict(dd), 0, None), kva=kva_model.predict(dd))

    def rooms(dd, k):                                   # guests held fixed: the form asks for rooms and guests separately
        x = dd.copy()
        x["rooms_sold"] = x.rooms_sold + k
        x["occupancy_pct"] = x.rooms_sold / 220
        return x
    P0 = scen(base)
    V = {"rooms+": scen(rooms(base, D_ROOMS)), "rooms-": scen(rooms(base, -D_ROOMS)),
         "g+": scen(base.assign(guests_in_house=base.guests_in_house + D_GUESTS)), "g-": scen(base.assign(guests_in_house=base.guests_in_house - D_GUESTS)),
         "cov+": scen(base.assign(covers_served_fnb=base.covers_served_fnb + D_COVERS)), "cov-": scen(base.assign(covers_served_fnb=base.covers_served_fnb - D_COVERS)),
         "t+": scen(base.assign(temp_c=base.temp_c + D_TEMP)), "t-": scen(base.assign(temp_c=base.temp_c - D_TEMP))}
    BQ = {}
    for hall, (typ, venue, st, en) in HALLS.items():
        rows = [dict(date=d, event_type=typ, venue=venue, guests=100, start_time=st, end_time=en, ends_after_midnight=en == "23:59") for d in days]
        BQ[hall] = scen(with_events(span, rows))

    ts = base.timestamp
    index = {}
    for d in days:
        i0 = int(np.flatnonzero((ts == d).to_numpy())[0])
        sl = slice(i0, i0 + 24)
        r1 = lambda x: [round(float(v), 1) for v in x]
        r4 = lambda x: [round(float(v), 4) for v in x]
        cen = lambda key, a, b, step: r4((V[a][key][sl] - V[b][key][sl]) / (2 * step))
        banquet = {}
        for hall, (_, _, st, en) in HALLS.items():
            s = int(st[:2]); e = 25 if en == "23:59" else int(en[:2])
            out = {}
            for key in ("kw", "tr"):
                delta = BQ[hall][key][i0:i0 + 48] - P0[key][i0:i0 + 48]
                mid = delta[s + 3:e - 3] if e - s > 6 else delta[s:e]
                out[key] = dict(start=r4(delta[s - 3:s + 3]), end=r4(delta[e - 3:e + 3]), during=round(float(np.median(mid)), 4))
            banquet[hall] = dict(out, reference=f"{st}–{en}, 100 guests", style="social" if hall == "A+B" else "corporate")
        day_tr = P0["tr"][sl]
        dd = base.iloc[i0]
        rec = dict(date=d.strftime("%Y-%m-%d"), site=SITE, template=f"live-year context for {d:%Y-%m-%d} (synthetic), last year's events cleared",
                   template_tmax=round(float(base.temp_c[sl].max()), 1), pf=pf, tariff=tariff,
                   defaults=dict(rooms=int(dd.rooms_sold), guests=int(dd.guests_in_house), covers=int(dd.covers_served_fnb), events=[]),
                   base=dict(kw=r1(P0["kw"][sl]), kva=r1(P0["kva"][sl]), tr=r1(day_tr), temp=r1(base.temp_c[sl])),
                   resp=dict(kw_per_room=cen("kw", "rooms+", "rooms-", D_ROOMS), kw_per_cover=cen("kw", "cov+", "cov-", D_COVERS),
                             kw_per_guest=cen("kw", "g+", "g-", D_GUESTS), kw_per_c=cen("kw", "t+", "t-", D_TEMP), tr_per_c=cen("tr", "t+", "t-", D_TEMP),
                             tr_per_room=cen("tr", "rooms+", "rooms-", D_ROOMS), tr_per_guest=cen("tr", "g+", "g-", D_GUESTS)),
                   banquet=banquet,
                   ref=dict(matched_refs(orig, sub_o, d, float(np.mean(day_tr))), curve=curve, ahu_overrun_kwh=overrun, chw_pct_per_c=chw_pct))
        txt = json.dumps(rec, separators=(",", ":"), ensure_ascii=False)
        assert len(txt) < 100_000, f"{d:%Y-%m-%d}: {len(txt)} bytes"
        (OUT / f"{d:%Y-%m-%d}.json").write_text(txt, encoding="utf-8")
        index[d.strftime("%Y-%m-%d")] = dict(tmax=rec["template_tmax"], rooms=rec["defaults"]["rooms"], covers=rec["defaults"]["covers"],
                                             peak_kva=round(float(P0["kva"][sl].max())), tr_max=round(float(day_tr.max())))
    (OUT / "index.json").write_text(json.dumps(dict(days=index, cooling_model=acc, risk=risk_calibration(), made=datetime.now(timezone(timedelta(hours=5.5))).strftime("%Y-%m-%d %H:%M IST")),
                                               separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(index)} days to {OUT} ({max(f.stat().st_size for f in OUT.glob('2*.json')) / 1024:.0f} kB largest)")


if __name__ == "__main__":
    today = (datetime.now(timezone.utc) + timedelta(hours=5.5)).date()
    # default: every live-year day so far (look back, plan vs actual) through 60 days ahead
    first = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 10, 2)
    n = int(sys.argv[2]) if len(sys.argv) > 2 else (today - first).days + 60
    main(first, n)
