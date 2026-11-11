"""Day-ahead power-demand scenarios for real future dates (Gurugram), so the web app can plan for tomorrow, not last year.

There is no meter feed after 30 Sep 2026, so each future date borrows the same weekday 52 weeks earlier as its template (typical
occupancy and load shape for that time of year), with last year's events cleared. The browser then picks the cell that matches
the real weather forecast (Open-Meteo) and any conference the team enters. One small file per date: web/public/data/live/<date>.json.

    uv run python tools/export_live_forecast.py [first_date] [days]
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import forecast_app as A  # noqa: E402

OUT = ROOT / "web" / "public" / "data" / "live"
GUESTS = list(range(0, 601, 100))


def main(first: date, n: int):
    OUT.mkdir(parents=True, exist_ok=True)
    s = A.state()
    d = s["d"]
    have = set(d.date.dt.strftime("%Y-%m-%d"))
    index = {}
    for k in range(n):
        real = first + timedelta(days=k)
        tpl = real - timedelta(days=364)  # same weekday, last year
        if tpl.isoformat() not in have:
            continue
        tmax = float(d.loc[d.date == str(tpl), "temp_c"].max())
        temps = list(range(round(tmax) - 9, round(tmax) + 10))
        grid, stack = {}, None
        for t in temps:
            for g in GUESTS:
                w, a = A.scenario(str(tpl), float(t), g, clear_events=True)
                stack = a["stack_table"].to_dict("records")
                grid[f"{t}|{g}"] = dict(pred=[round(float(x)) for x in w.pred_kva],
                                        risk={k2: v for k2, v in a.items() if k2 not in ("plan", "stack_table")},
                                        plan=None if a["plan"] is None else a["plan"].to_dict("records"))
        rec = dict(date=real.isoformat(), template=tpl.isoformat(), template_tmax=round(tmax, 1), hours=list(range(24)),
                   temps=temps, guests=GUESTS, grid=grid, stack_table=stack)
        (OUT / f"{real.isoformat()}.json").write_text(json.dumps(rec, separators=(",", ":"), default=float))
        index[real.isoformat()] = tpl.isoformat()
        print(real, "from", tpl, flush=True)
    (OUT / "index.json").write_text(json.dumps(index))


if __name__ == "__main__":
    first = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    main(first, int(sys.argv[2]) if len(sys.argv) > 2 else 60)
