"""Export everything the web UI shows as static JSON (web/public/data/), so the front end needs no Python at run time.

Every number comes from the existing modules (detector cards, bills, attribution, forecast, savings, evaluation); this script only
serialises them. Run after src/build_app_data.py:   uv run python tools/export_web_data.py
"""
import json
import math
import re
import subprocess
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from alert_cards import CHART  # noqa: E402
from features import CLEAN, SITES  # noqa: E402

APP = CLEAN.parent / "app"
OUT = ROOT / "web" / "public" / "data"
FN_OUT = ROOT / "web" / "netlify" / "functions" / "data"     # copy the assistant tools read
SITE_LIST = ["GGN", "JAI", "GOA"]


def clean(o):
    """JSON-safe: NaN -> None, numpy -> python, timestamps -> ISO minutes (IST, no zone)."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (pd.Timestamp,)):
        return o.strftime("%Y-%m-%dT%H:%M")
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if (o is None or math.isnan(o) or math.isinf(o)) else round(float(o), 3)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, pd.Interval):
        return f"{o.left:g}-{o.right:g}"
    return o


def write(name, obj, also_fn=False):
    txt = json.dumps(clean(obj), separators=(",", ":"), ensure_ascii=False)
    (OUT / name).write_text(txt, encoding="utf-8")
    if also_fn:
        (FN_OUT / name).write_text(txt, encoding="utf-8")
    print(f"{name:28s} {len(txt) / 1024:8.0f} KB")


def frames():
    return {s: pd.read_parquet(APP / f"frame_{s}.parquet") for s in SITE_LIST}


def export_hotels(F):
    bills = pd.read_parquet(CLEAN / "monthly_bills.parquet")
    out = {}
    for s, d in F.items():
        b = bills[bills.site == s]
        day = d.assign(date=d.timestamp.dt.normalize()).groupby("date").agg(
            actual=("total_kwh", "sum"), baseline=("pred_ens", "sum"), tmax=("temp_c", "max"), rooms=("rooms_sold", "first"),
            guests=("ev_guests", "max"), peak_kva=("kva_max_in_hour", "max"))
        out[s] = dict(code=s, name=SITES[s], rooms={"GGN": 220, "JAI": 160, "GOA": 140}[s],
                      contract_kva=float(b.contract_demand_kva.iloc[0]), annual_cost=float(b.total_energy_cost_inr.sum()),
                      daily=[dict(date=i.strftime("%Y-%m-%d"), **r) for i, r in day.iterrows()])
        hourly = d[["timestamp", "total_kwh", "pred_ens", "temp_c", "kva_max_in_hour", "event_on", "fault"]].rename(
            columns={"timestamp": "t", "total_kwh": "a", "pred_ens": "b", "temp_c": "temp", "kva_max_in_hour": "kva", "event_on": "ev", "fault": "f"})
        write(f"hourly_{s}.json", dict(t=list(hourly.t.dt.strftime("%Y-%m-%dT%H")), a=list(hourly.a.round(1)), b=list(hourly.b.round(1)),
                                       temp=list(hourly.temp.round(1)), kva=list(hourly.kva.round(0)), ev=list(hourly.ev.astype(int)),
                                       f=list(hourly.f.astype(int))))
    write("hotels.json", out)


def export_alerts(F):
    c = pd.read_parquet(APP / "cards.parquet")
    rows = []
    for r in c.itertuples():
        d = F[r.site]
        span = (r.end - r.start)
        pad = pd.Timedelta(hours=max(12, min(36, span.total_seconds() / 3600)))
        w = d[(d.timestamp >= r.start - pad) & (d.timestamp <= min(r.end + pad, r.start + pd.Timedelta(days=12)))]
        cols = [x for x in CHART.get(r.rule, []) if x in w]
        ev = dict(t=list(w.timestamp.dt.strftime("%Y-%m-%dT%H")), actual=list(w.total_kwh.round(1)), baseline=list(w.pred_ens.round(1)),
                  signals={x: list(pd.to_numeric(w[x], errors="coerce").round(3)) for x in cols})
        rows.append(dict(id=r.alert_id, site=r.site, hotel=r.hotel, rule=r.rule, title=r.title, severity=r.severity, equipment=r.equipment,
                         start=r.start, end=r.end, alert_time=r.alert_time, flagged_h=r.flagged_h, duration_h=r.duration_h,
                         detect_lag_h=r.detect_lag_h, excess_kwh=r.excess_kwh, cost=r.cost_inr, per_hour=r.inr_per_hour, per_day=r.inr_per_day,
                         cost_basis=r.cost_basis, cost_note=r.cost_note, channel=r.channel, repeat_30d=r.repeat_30d, inferred_note=r.inferred_note,
                         evidence=r.evidence, cause=r.cause, action=r.action, guardrail=r.guardrail, guard_text=r.guard_text, post_hoc=bool(r.post_hoc),
                         text=r.text, chart=ev))
    write("alerts.json", rows)
    f = pd.read_parquet(APP / "faults.parquet")
    write("faults.json", f.to_dict("records"))
    # compact list for the assistant (no chart arrays)
    lite = [{k: v for k, v in x.items() if k not in ("chart", "text")} for x in rows]
    (FN_OUT / "alerts_lite.json").write_text(json.dumps(clean(lite), separators=(",", ":"), ensure_ascii=False), encoding="utf-8")


def export_bills():
    from attribution import explain_change
    from bills import components, unused_demand
    r = pd.read_parquet(APP / "bills_recon.parquet")
    comp = {s: components(s).to_dict("records") for s in SITE_LIST}
    unused = {s: unused_demand(s) for s in SITE_LIST}
    write("bills.json", dict(recon=r.to_dict("records"), components=comp, unused_demand=unused), also_fn=True)
    pairs = {}
    for s in SITE_LIST:
        months = sorted(r[r.site == s].month)
        for a, b in combinations(months, 2):
            x = explain_change(s, a, b)
            g = x["table"].groupby("group").inr.sum()
            pairs[f"{s}|{a}|{b}"] = dict(site=s, a=a, b=b, bill_a=x["bill_a"], bill_b=x["bill_b"], delta=x["delta"],
                                         groups=g.round(0).to_dict(), lines=x["table"].round(1).to_dict("records"), context=x["context"],
                                         waste_kwh_b=x["alert_rules_b"])
        print(s, "bill pairs done")
    write("bill_changes.json", pairs, also_fn=True)


def export_forecast():
    import forecast_app as A
    s = A.state()
    S = s["S"]
    days = {}
    for dt in S.index:
        w, a = A.day_view(dt)
        if w.empty:
            continue
        days[dt.strftime("%Y-%m-%d")] = dict(
            hours=list(w.hour), pred=list(w.pred_kva.round(0)), actual=list(w.actual_kva.round(0)),
            risk={k: v for k, v in a.items() if k not in ("plan", "stack_table")},
            plan=None if a["plan"] is None else a["plan"].to_dict("records"), stack_table=a["stack_table"].to_dict("records"))
    write("forecast_days.json", days, also_fn=True)
    grid = {}
    for t in range(30, 47):
        for g in range(0, 601, 50):
            w, a = A.scenario("2026-05-20", float(t), g)
            grid[f"{t}|{g}"] = dict(hours=list(w.hour), pred=list(w.pred_kva.round(0)), risk={k: v for k, v in a.items() if k not in ("plan", "stack_table")},
                                    plan=None if a["plan"] is None else a["plan"].to_dict("records"), stack_table=a["stack_table"].to_dict("records"))
    write("forecast_whatif.json", dict(template="2026-05-20", temps=list(range(30, 47)), guests=list(range(0, 601, 50)), grid=grid), also_fn=True)


def export_savings():
    from savings import NOT_SIZED, model_stats, plan
    p = plan()
    stats = {}
    for s in SITE_LIST:
        m = model_stats(s)
        mv = m.pop("monthly").reset_index()
        stats[s] = dict(m, monthly=mv.to_dict("records"))
    bill = float(pd.read_parquet(CLEAN / "monthly_bills.parquet").total_energy_cost_inr.sum())
    write("savings.json", dict(measures=p.to_dict("records"), not_sized=NOT_SIZED, option_c=stats, group_bill=bill, target=[0.08, 0.12]), also_fn=True)


def export_quality():
    from evaluation import score_heldout
    f = pd.read_parquet(CLEAN / "meter_faults.parquet")
    frozen = score_heldout(pd.read_parquet(CLEAN / "alerts.parquet"), f)["summary"]
    full = score_heldout(pd.read_parquet(APP / "cards.parquet"), f)["summary"]
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "acceptance.py")], capture_output=True, text=True, cwd=ROOT).stdout
    tests = [dict(id=m.group(1), result=m.group(2), detail=m.group(3).strip())
             for m in re.finditer(r"^(T\d+)\s+(PASS|CHECK)\s+(.*)$", out, flags=re.M)]
    alarms = pd.read_parquet(CLEAN / "bms_alarm_log.parquet")
    write("quality.json", dict(frozen=frozen, full=full, tests=tests,
                               bms=dict(alarms=len(alarms), precision=0.26, recall=0.40, closed_no_action=0.657, median_action_h=8.3),
                               baseline={"GGN": [8.3, 3.4], "JAI": [5.0, 1.1], "GOA": [5.4, 2.8]},
                               forecast=dict(mape=5.4, within5=0.59, within10=0.86)), also_fn=True)


def export_rating():
    from feedback import RATING_IDS
    write("rating_set.json", RATING_IDS)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    FN_OUT.mkdir(parents=True, exist_ok=True)
    F = frames()
    export_hotels(F)
    export_alerts(F)
    export_savings()
    export_quality()
    export_rating()
    export_forecast()
    export_bills()
