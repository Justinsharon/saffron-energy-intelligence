"""Monthly reports for every closed month (bill issued) as static JSON: web/public/data/reports/<YYYY-MM>.json + index.json.

Why static: a closed month never changes, so the report page loads instantly and never shows "unavailable"; only the current month's
figures (Bills & savings) call the API. Everything is as of the bill's issue date (live year: bill_issued; original year: the 5th of the
next month), the same rule the page uses.

Plan savings follow the plan-accounting rule (src/plan_check.py): only APPROVED steps of SAVED plans count. Saved plans are read from the
site's plans function (GET ?month=), so the report counts exactly what the team approved; days with no saved plan add ₹0 (their suggested
plan is reported separately as "would have saved", never in a total). Verified plan ₹ counts in that month's "found" figure next to Option C,
never in the yearly savings headline (src/savings.py). Alert ₹ is reported in full (as in the headline); the part in hours an approved, followed
plan step also covered (same equipment) is shown as overlap_inr and taken off "found" once, so no rupee is counted twice.

The gap between savings found (plan + alerts) and the Option C total is explained, not hidden: the live year carries the generator's
growth (tools/make_live_year.py: load x 1.012^(1 + (d - 182.5)/365), d = days since 1 Oct 2026), which the adjusted baseline (trained on the
original year) does not adjust for; that part is computed in kWh and ₹. The rest is waste from new faults that the alerts caught but that still
happened on the (simulated) meters, plus model noise.

Run after a bill is issued (or any data change), then rebuild the site:   uv run python tools/export_reports.py
"""
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
import operating_plan as OP  # noqa: E402

PUB = ROOT / "web" / "public" / "data"
OUT = PUB / "reports"
SITES = {"GGN": "Gurugram", "JAI": "Jaipur", "GOA": "Goa"}
LIVE_START = "2026-10"
GROWTH = 1.012                     # tools/make_live_year.py make_map: yf = 1.012 ** (1 + (d - ND / 2) / 365)
PLANS_URL = "https://saffron-energy-intelligence1.netlify.app/.netlify/functions/plans?month="
RULE_GROUP = {"CHILLER_STAGING_LOW_LOAD": "chillers", "STAGING_KWTR": "chillers", "CHW_SETPOINT_LOW": "chw", "AHU_HAND_MODE": "ahu",
              "LAUNDRY_IN_PEAK": "laundry", "EV_CHARGER_NIGHT_ON": "ev"}
LEVEL = {"BREACH RISK": "risk of going over", "WARNING": "close to the limit", "STACKING WATCH": "watch the afternoon", "OK": "comfortable"}


def load(name):
    return json.loads((PUB / name).read_text(encoding="utf-8"))


def add_month(m: str, k: int) -> str:
    return (pd.Period(m) + k).strftime("%Y-%m")


def growth_factor(ts: pd.Timestamp) -> float:
    d = (ts.normalize() - pd.Timestamp("2026-10-01")).days
    return GROWTH ** (1 + (d - 182.5) / 365) if d >= 0 else 1.0


def saved_plans(month: str) -> dict:
    try:
        with urllib.request.urlopen(PLANS_URL + month, timeout=20) as r:
            return json.load(r).get("plans", {})
    except Exception as e:                                       # storage unreachable: say so in the report rather than guess
        print(f"  {month}: saved plans could not be read ({e}); plan savings reported as unavailable")
        return None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    today = (datetime.now(timezone.utc) + timedelta(hours=5.5)).date().isoformat()
    bo, bl = load("bills.json"), load("live_feed/bills.json")
    recon = bo["recon"] + bl["recon"]
    changes = {**load("bill_changes.json"), **load("live_feed/bill_changes.json")}
    alerts = load("alerts.json") + load("live_feed/alerts.json")
    hourly = {s: {k: load(f"hourly_{s}.json")[k] + load(f"live_feed/hourly_{s}.json")[k] for k in ("t", "a", "b", "f")} for s in SITES}
    idx = load("plan/index.json")
    past = load("forecast_days.json")
    A = None                                                      # the API module (models), loaded only for live months

    issued = lambda r: (r.get("bill_issued") or f"{add_month(r['month'], 1)}-05")[:10]
    months = sorted({r["month"] for r in recon if issued(r) <= today})
    index = []
    for m in months:
        rows = {s: next((r for r in recon if r["site"] == s and r["month"] == m), None) for s in SITES}
        as_of_date = issued(rows["GGN"] or next(r for r in rows.values() if r))
        as_of = f"{as_of_date}T09:00"
        prev, ly = add_month(m, -1), add_month(m, -12)
        bill = lambda s, mm: next((r["billed_total"] for r in recon if r["site"] == s and r["month"] == mm and issued(r) <= as_of_date), None)
        rate = {s: (rows[s]["billed_total"] / max(rows[s]["billed_kvah"] * rows[s]["pf"], 1)) if rows[s] else 0.0 for s in SITES}

        # Option C and the growth built into the live year
        oc, growth = {}, {}
        for s in SITES:
            h = hourly[s]
            a = b = g = 0.0
            for t, x, y, f in zip(h["t"], h["a"], h["b"], h["f"]):
                if t[:7] == m and t <= as_of[:13] and not f:
                    a += x; b += y
                    if m >= LIVE_START:
                        g += x * (1 - 1 / growth_factor(pd.Timestamp(t[:10])))
            oc[s] = dict(actual_kwh=round(a), baseline_kwh=round(b), kwh=round(b - a), inr=round((b - a) * rate[s]))
            growth[s] = dict(kwh=round(g), inr=round(g * rate[s]))

        # plan savings: approved steps of saved plans only (days without a saved plan add nothing)
        plan, covered = None, {}
        if m >= LIVE_START:
            saved = saved_plans(m)
            if saved is not None:
                if A is None:
                    import api.main as A                         # noqa: N811
                    A._open_meteo = lambda d, n: None             # closed months: never the live weather
                ver = pl = miss = would = 0.0
                appr = 0
                for d in sorted(x for x in A.REFS if x.startswith(m) and x <= as_of[:10]):
                    st, c = A._check(d, saved.get(d) or None, as_of)
                    if st != 200:
                        continue
                    sm = c["summary"]
                    ver += sm["verified_inr"]; pl += sm["planned_inr"]; miss += sm["missed_inr"]; would += sm["would_have_saved_inr"]
                    appr += sm["approved"]
                    covered[d] = c["covered"]
                plan = dict(verified_inr=round(ver), planned_inr=round(pl), missed_inr=round(miss), would_have_saved_inr=round(would),
                            approved_steps=appr, saved_days=len(saved))

        # alert savings in full; overlap = the part in hours an approved, followed plan step covered (same equipment) - display only
        al = [x for x in alerts if x["alert_time"] <= as_of and x["start"][:7] == m and x["cost"] > 0 and x["rule"] != "PLAN_DEVIATION"]
        a_inr = overlap = 0.0
        for x in al:
            g = RULE_GROUP.get(x["rule"]) if x["site"] == "GGN" else None
            keep = x["cost"]
            if g:
                t0, t1 = pd.Timestamp(x["start"]), pd.Timestamp(x["end"])
                hrs = max(1, round((t1 - t0) / pd.Timedelta(hours=1)))
                ov = sum(1 for t in pd.date_range(t0, t1, freq="h", inclusive="left") if t.hour in covered.get(t.strftime("%Y-%m-%d"), {}).get(g, []))
                keep = x["cost"] * (1 - ov / hrs)
                overlap += x["cost"] - keep
            a_inr += x["cost"]

        oc_inr = sum(v["inr"] for v in oc.values())
        found = a_inr - overlap + (plan["verified_inr"] if plan else 0)          # the overlap is in both; count it once
        g_inr = sum(v["inr"] for v in growth.values())
        gap = None
        if m >= LIVE_START:
            gap = dict(found_inr=round(found), overlap_inr=round(overlap), option_c_inr=round(oc_inr), gap_inr=round(found - oc_inr), growth_inr=round(g_inr),
                       growth_kwh=sum(v["kwh"] for v in growth.values()), rest_inr=round(found - oc_inr - g_inr))

        # drivers vs last month, all hotels
        groups, have = {}, 0
        for s in SITES:
            c = changes.get(f"{s}|{prev}|{m}")
            if c:
                have += 1
                for k, v in c["groups"].items():
                    groups[k] = groups.get(k, 0) + v
        steps = sorted(((k, v) for k, v in groups.items() if abs(v) >= 1), key=lambda kv: -abs(kv[1]))
        drivers = [dict(group=k, inr=round(v)) for k, v in steps[:5]]
        rest = sum(v for _, v in steps[5:])
        if abs(rest) >= 1:
            drivers.append(dict(group="Other", inr=round(rest)))

        probs = sorted(al, key=lambda x: -x["cost"])[:5]
        nm = add_month(m, 1)
        watch = [dict(date=d, peak_kva=round(OP.risk_for([x["peak_kva"]], idx["risk"])["peak_kva"]), level=OP.risk_for([x["peak_kva"]], idx["risk"])["level"])
                 for d, x in idx["days"].items() if d.startswith(nm) and d > as_of_date]
        if not watch:
            watch = [dict(date=d, peak_kva=round(f["risk"]["peak"]), level=f["risk"]["level"]) for d, f in past.items() if d.startswith(nm) and d > as_of_date]
        watch = sorted(watch, key=lambda w: -w["peak_kva"])[:4]

        rep = dict(
            month=m, as_of=as_of_date, simulated=m >= LIVE_START,
            bills={s: dict(this=rows[s]["billed_total"] if rows[s] else None, prev=bill(s, prev), last_year=bill(s, ly)) for s in SITES},
            option_c=dict(by_site=oc, kwh=sum(v["kwh"] for v in oc.values()), inr=round(oc_inr)),
            savings=dict(plan=plan, plan_note=None if m >= LIVE_START else "Daily plans started in Oct 2026.",
                         alerts=dict(inr=round(a_inr), overlap_inr=round(overlap), alerts=len(al))),
            gap=gap, drivers=dict(complete=have == len(SITES), prev_total=sum(bill(s, prev) or 0 for s in SITES),
                                  this_total=sum((rows[s] or {}).get("billed_total", 0) for s in SITES), steps=drivers),
            bill_check=[dict(site=s, status=rows[s]["status"], billed_minus_corrected=rows[s]["billed_minus_corrected"]) for s in SITES if rows[s]],
            problems=[dict(hotel=x["hotel"], rule=x["rule"], title=x["title"], inr=round(x["cost"]), status="resolved" if x["end"] <= as_of else "still running") for x in probs],
            watch=[dict(w, level_text=LEVEL.get(w["level"], w["level"])) for w in watch],
            method=("Plan = approved steps of saved plans that were followed, meters vs matched days last year; alerts = waste caught, counted once and never "
                    "for hours an approved plan step covered; Option C = actual vs the weather-, occupancy- and event-adjusted baseline (IPMVP)."),
            honesty=("Meters from Oct 2026 are simulated and do not react to approvals, so plan adherence is illustrative." if m >= LIVE_START else ""))
        (OUT / f"{m}.json").write_text(json.dumps(rep, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        index.append(m)
        if m >= LIVE_START:
            print(f"{m}: bills ₹{rep['drivers']['this_total']:,.0f}; plan verified ₹{plan['verified_inr'] if plan else '—'}; alerts ₹{a_inr:,.0f}; "
                  f"Option C ₹{oc_inr:,.0f}; gap ₹{gap['gap_inr']:,} of which growth ₹{gap['growth_inr']:,}")
    (OUT / "index.json").write_text(json.dumps(dict(months=index, made=today)), encoding="utf-8")
    print(f"wrote {len(index)} closed months to {OUT}")


if __name__ == "__main__":
    main()
