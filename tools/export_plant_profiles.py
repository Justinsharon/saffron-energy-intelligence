"""Equipment profiles for the Plant Room simulation (web/plant.html): what each Gurugram sub-meter usually draws, hour by hour, on the
plan's own matched days (models/refs.json `matched_days`: same month, same day type, similar cooling load; original year only).

Why: the plan API returns only site kW / kVA / TR. The Plant Room shows each piece of equipment following "habit" (how last year ran on
matched days) until the duty engineer applies an approved step, then the plan. The habit side must come from our data, not invented
numbers, so it is the mean of the matched days' sub-meter readings. Nothing here is refitted: it reads the cleaned original year.

Writes web/public/data/plant/<date>.json for every live-year date (one per plan date) and web/public/data/plant/index.json (constants
measured on the whole original year: banquet AHU draw during events per hall, CHW supply-vs-setpoint offset, CH-1's share when both run).
Run: uv run python tools/export_plant_profiles.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean"
OUT = ROOT / "web" / "public" / "data" / "plant"
RUN_KW = 5.0                     # src/plan_check.RUN_KW: a chiller above this is running
HALL = {"Banquet Hall A": "A", "Banquet Hall B": "B", "Banquet Hall A + B": "A+B"}


def r(xs, n=1):
    return [round(float(v), n) for v in xs]


def main():
    refs = json.loads((ROOT / "models" / "refs.json").read_text(encoding="utf-8"))
    sub = pd.read_parquet(CLEAN / "sub_ggn_hourly.parquet")
    sub["date"] = sub.timestamp.dt.strftime("%Y-%m-%d")
    sub["hour"] = sub.timestamp.dt.hour
    ev = pd.read_parquet(CLEAN / "events.parquet").query("site == 'GGN'")

    # banquet AHU draw while an event is on, per hall (hours inside [start, end) of each original-year event)
    a = sub.set_index("timestamp").ahu_banquet_kw
    per_hall: dict[str, list] = {"A": [], "B": [], "A+B": []}
    event_hours = set()
    for e in ev.itertuples():
        h = HALL.get(e.venue)
        if h is None:
            continue
        s = pd.Timestamp(e.date) + pd.Timedelta(hours=int(e.start_time[:2]))
        end = pd.Timestamp(e.date) + (pd.Timedelta(days=1, hours=1) if e.ends_after_midnight else pd.Timedelta(hours=int(e.end_time[:2])))
        w = a[s: end - pd.Timedelta(hours=1)]
        per_hall[h].extend(w.to_numpy().tolist())
        event_hours.update(w.index)
    ahu_event_kw = {k: round(float(np.mean(v)), 1) for k, v in per_hall.items() if v}
    idle = a[~a.index.isin(event_hours)]
    both = sub[(sub.chiller_ch1_kw > RUN_KW) & (sub.chiller_ch3_kw > RUN_KW)]
    ch1_share_both = float((both.chiller_ch1_kw / (both.chiller_ch1_kw + both.chiller_ch3_kw)).mean()) if len(both) else 2 / 3
    supply_offset = float((sub.chw_supply_temp_c - sub.chw_setpoint_c).mean())
    index = dict(
        source="Mean of the matched days' sub-meter readings (models/refs.json matched_days; original year Oct 2025 - Sep 2026). Not refitted.",
        ahu_event_kw=ahu_event_kw, ahu_event_hours={k: len(v) for k, v in per_hall.items()},
        ahu_idle_kw=round(float(idle.median()), 1), ch1_share_both=round(ch1_share_both, 3), chw_supply_offset_c=round(supply_offset, 2),
        laundry_connected_kw=95.0, water_connected_kw=80.0, ahu_rated_kw={"A": 45.0, "B": 45.0, "A+B": 90.0},
        note="Connected / rated kW from the equipment register (data/clean/equipment_register.parquet). Return water temperature is not metered.",
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")

    by_date = {d: g.set_index("hour").sort_index() for d, g in sub.groupby("date")}
    cols = dict(laundry="laundry_kw", water="water_heating_kw", ev="ev_chargers_kw", kitchen_exhaust="kitchen_exhaust_mua_kw", lifts="lifts_kw",
                rooms="rooms_fcu_plug_kw", ahu="ahu_banquet_kw")
    n = 0
    for date, ref in refs.items():
        days = [by_date[d] for d in ref["matched_days"] if d in by_date and len(by_date[d]) == 24]
        if not days:
            continue
        st = pd.DataFrame({i: np.where((g.chiller_ch1_kw > RUN_KW) & (g.chiller_ch3_kw > RUN_KW), "CH-1+CH-3",
                                       np.where(g.chiller_ch1_kw > RUN_KW, "CH-1", np.where(g.chiller_ch3_kw > RUN_KW, "CH-3", "none")))
                           for i, g in enumerate(days)})
        stage = [st.loc[h].mode().iloc[0] for h in range(24)]                     # the usual staging at that hour on matched days
        out = dict(date=date, matched_days=ref["matched_days"], habit_stage=stage,
                   habit_chillers_on=[float(st.loc[h].isin(["CH-1+CH-3"]).mean()) for h in range(24)])
        for k, c in cols.items():
            out[k] = r(np.mean([g[c].to_numpy() for g in days], axis=0))
        (OUT / f"{date}.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
        n += 1
    print(f"wrote {n} days + index.json to {OUT.relative_to(ROOT)}; AHU event kW {ahu_event_kw}, CH-1 share when both run {ch1_share_both:.2f}")


if __name__ == "__main__":
    main()
