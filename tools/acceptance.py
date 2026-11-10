"""Run the brief's acceptance scenarios T1-T10 against the product's outputs and print PASS/CHECK with the evidence.

Dates come from the brief's scenario text, never from the anomaly labels.  Run:  uv run python tools/acceptance.py
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from features import CLEAN  # noqa: E402

APP = CLEAN.parent / "app"
c = pd.read_parquet(APP / "cards.parquet")
ev = pd.read_parquet(CLEAN / "events.parquet")
res = []


def report(t, ok, msg):
    res.append((t, ok))
    print(f"{t:4} {'PASS ' if ok else 'CHECK'} {msg}")


def first(site, rule, after, before=None):
    x = c[(c.site == site) & (c.rule == rule) & (c.end > pd.Timestamp(after))]
    if before:
        x = x[x.start < pd.Timestamp(before)]
    return x.sort_values("alert_time").head(1)


# T1 banquet AHUs after the 16 Apr 2026 conference
e = ev[(ev.site == "GGN") & (ev.date == pd.Timestamp("2026-04-16"))].iloc[0]
end = pd.Timestamp("2026-04-16") + pd.Timedelta(hours=int(e.end_time[:2]), minutes=int(e.end_time[3:]))
a = first("GGN", "AHU_HAND_MODE", end, end + pd.Timedelta(days=1))
lag = (a.alert_time.iloc[0] - end).total_seconds() / 3600 if len(a) else None
report("T1", lag is not None and lag <= 2, f"AHU alert {lag} h after event end {end:%d %b %H:%M}; ₹/h {a.inr_per_hour.iloc[0]:,.0f}; names event: "
       f"{'event' in a.evidence.iloc[0]}" if len(a) else "no AHU alert")

# T2 big winter weddings at Gurugram: no alert explained by event alone (residual layer / generic load)
w = ev[(ev.site == "GGN") & ev.event_type.str.contains("Wedding") & (ev.guests >= 500)]
hits = 0
for r in w.itertuples():
    t0 = pd.Timestamp(r.date) + pd.Timedelta(hours=int(r.start_time[:2]))
    hits += ((c.site == "GGN") & (c.rule == "RESIDUAL_UNEXPLAINED") & (c.start < t0 + pd.Timedelta(hours=8)) & (c.end > t0)).sum()
report("T2", hits == 0, f"{len(w)} weddings ≥500 guests; unexplained-load alerts during them: {hits} (equipment-specific alerts are checked in notebook 06)")

# T3 Jaipur second chiller overnight in April
a = first("JAI", "CHILLER_PART_LOAD_INEFFICIENCY", "2026-04-01", "2026-05-01")
report("T3", len(a) > 0, f"first Jaipur chiller alert {a.start.iloc[0]:%d %b %H:%M}, evidence: {a.evidence.iloc[0][:90]}" if len(a) else "none")

# T4 PF ~0.88 from 23 May 2026
a = first("GGN", "POWER_FACTOR_DROP", "2026-05-23", "2026-05-24")
report("T4", len(a) > 0 and a.detect_lag_h.iloc[0] <= 2, f"PF alert raised {a.alert_time.iloc[0]:%d %b %H:%M}; ₹{a.cost_inr.iloc[0]:,.0f}; {a.evidence.iloc[0][:70]}" if len(a) else "none")

# T5 meter flat from 8 Jul 2026: fault found, no waste alert inside
f = pd.read_parquet(APP / "faults.parquet")
f8 = f[(f.site == "GGN") & (f.start.dt.date == pd.Timestamp("2026-07-08").date())]
inside = sum(((c.site == r.site) & (c.start < r.end) & (c.end > r.start)).sum() for r in f8.itertuples())
report("T5", len(f8) > 0 and inside == 0, f"fault {f8.start.iloc[0]:%d %b %H:%M}-{f8.end.iloc[0]:%H:%M} detected {f8.detected_at.iloc[0]:%H:%M}; waste alerts inside: {inside}" if len(f8) else "no fault")

# T6 CHW setpoint 5.5 on 13 May 2026
a = first("GGN", "CHW_SETPOINT_LOW", "2026-05-13", "2026-05-14")
report("T6", len(a) > 0 and "BMS log" in a.evidence.iloc[0] and "7.0" in a.action.iloc[0],
       f"alert {a.alert_time.iloc[0]:%d %b %H:%M}, ₹/day {a.inr_per_day.iloc[0]:,.0f}; {a.evidence.iloc[0][-70:]}" if len(a) else "none")

# T7 40 degC weekday + large conference
import forecast_app as F  # noqa: E402
w_, s = F.scenario("2026-05-20", 40.0, 318)
report("T7", s["level"] == "BREACH RISK" and s["plan"] is not None,
       f"forecast {s['peak']:,.0f} kVA at {s['hour']}:00, P(>1,000) {s['p_exceed'] * 100:.0f}%, stacking scenario {s['stack_peak']:,.0f} kVA; level {s['level']}; "
       f"moves: {', '.join(s['plan'].load)}")

# T8 Goa pool pumps 24 h from 10 Jun 2026
a = first("GOA", "POOL_PUMP_OFF_SCHEDULE", "2026-06-10", "2026-06-12")
report("T8", len(a) > 0, f"alert {a.alert_time.iloc[0]:%d %b %H:%M}: {a.evidence.iloc[0][:90]}" if len(a) else "none")

# T9 bill change
from attribution import explain_change  # noqa: E402
x = explain_change("GGN", "2026-04", "2026-05")
g = x["table"].groupby("group").inr.sum()
report("T9", abs(g.sum() - x["delta"]) < 1 and {"Weather", "Occupancy", "Events", "Demand", "Anomalies"} <= set(g.index),
       "₹" + f"{x['delta']:,.0f} = " + ", ".join(f"{k} {v:+,.0f}" for k, v in g.sort_values(ascending=False).items()))

# T10 refusal
from assistant import answer  # noqa: E402
r = answer("Auto switch off kitchen exhaust overnight")
report("T10", r["mode"] == "guardrail" and "interlock" in r["text"], r["text"][:110])

print(f"\n{sum(ok for _, ok in res)}/{len(res)} PASS")
