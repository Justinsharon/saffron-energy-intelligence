"""Saffron Suites forecast / plan API (Gurugram) on Cloud Run. RECOMMEND ONLY: it returns a plan; it controls nothing.

GET  /health  -> ok, what the models were trained on, the dates covered.
POST /plan    -> for one date: hourly forecast (kW, peak kVA, cooling TR), peak-demand risk and the timed operating plan with ₹ savings and
                 guardrails, plus plain-English notes about the inputs.

Body (all optional): {"date": "YYYY-MM-DD" (default tomorrow, IST), "rooms": int, "guests": int (in house), "covers": int,
                      "tmax": number or "temps": [24 hourly °C], "bookings": [{"hall": "A" | "B" | "A+B", "start": "HH:MM", "end": "HH:MM", "guests": int}]}

How: the frozen models in models/ (fitted on Oct 2025 - Sep 2026 only; tools/export_api_models.py) are run on the day's context with the
inputs applied, then src/operating_plan.py builds the plan (the same rules as the web page, web/src/plan.ts). Inputs outside what the
models saw in training are clamped or flagged in `notes`, never an error, so a planner always gets an answer and the reason it may be
less certain. Weather: the hourly temperatures given, else the Open-Meteo hourly forecast when the date is within its 16 days, else the
typical weather for that date.
"""
import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import operating_plan as OP
from plan_models import HALL_EVENT, add_bookings, booking_hours, predict

ROOT = Path(__file__).resolve().parents[1]
M = ROOT / "models"
MODELS = joblib.load(M / "plan_models.joblib")
CTX = pd.read_parquet(M / "context.parquet")
REFS = json.loads((M / "refs.json").read_text(encoding="utf-8"))
META = json.loads((M / "meta.json").read_text(encoding="utf-8"))
IST = timezone(timedelta(hours=5, minutes=30))
GGN = (28.46, 77.03)

app = FastAPI(title="Saffron Suites plan API", version="1.0", description="Forecast and operating plan for Gurugram. Recommend only.")


def _num(x, default):
    try:
        v = float(x)
        return v if v == v else default
    except (TypeError, ValueError):
        return default


def _hhmm(t) -> str | None:
    s = str(t or "").strip()
    try:
        h, m = (s.split(":") + ["0"])[:2]
        h, m = int(h), int(m)
    except ValueError:
        return None
    if h == 24 and m == 0:
        return "23:59"
    return f"{h:02d}:{m:02d}" if 0 <= h <= 23 and 0 <= m <= 59 else None


_WX: dict = {}                                              # date -> (fetched at, hourly temps): the forecast changes slowly


def _open_meteo(date: str, notes: list) -> list | None:
    hit = _WX.get(date)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    try:
        url = (f"https://api.open-meteo.com/v1/forecast?latitude={GGN[0]}&longitude={GGN[1]}&hourly=temperature_2m"
               f"&timezone=Asia%2FKolkata&start_date={date}&end_date={date}")
        with urllib.request.urlopen(url, timeout=3) as r:
            j = json.load(r)
        t = j["hourly"]["temperature_2m"]
        t = t if len(t) == 24 and all(v is not None for v in t) else None
        _WX[date] = (time.time(), t)
        return t
    except Exception:                                       # no forecast for that date, or the service is slow: use typical weather
        notes.append("The live weather forecast could not be read; the typical weather for this date is used.")
        return None


@app.get("/health")
def health():
    return {"status": "ok", "site": META["site"], "models_trained_on": META["trained_on"], "dates": META["dates"],
            "cooling_model_cv_rmse_pct": META["cooling_model"]["hourly_cv_rmse_pct"], "recommend_only": True}


@app.post("/plan")
async def plan(req: Request):
    t0 = time.perf_counter()
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    notes: list[str] = []
    today = datetime.now(IST).date()
    date = str(body.get("date") or (today + timedelta(days=1)).isoformat())
    if date not in REFS:
        return JSONResponse({"error": f"No context for {date}. Dates covered: {META['dates'][0]} to {META['dates'][1]}.", "notes": notes}, status_code=422)
    day = pd.Timestamp(date)
    win = CTX[(CTX.timestamp >= day - pd.Timedelta(days=1)) & (CTX.timestamp < day + pd.Timedelta(days=2))].reset_index(drop=True)
    on_day = ((win.timestamp >= day) & (win.timestamp < day + pd.Timedelta(days=1))).to_numpy()
    rng = META["ranges"]

    # occupancy: given values replace the day's typical ones, clamped to what the models saw
    defaults = dict(rooms=int(win.loc[on_day, "rooms_sold"].iloc[0]), guests=int(win.loc[on_day, "guests_in_house"].iloc[0]),
                    covers=int(win.loc[on_day, "covers_served_fnb"].iloc[0]))
    used = dict(defaults)
    for key, col, lo_hi, label in (("rooms", "rooms_sold", rng["rooms"], "rooms occupied"), ("guests", "guests_in_house", rng["guests_in_house"], "guests in house"),
                                   ("covers", "covers_served_fnb", rng["covers"], "restaurant covers")):
        if body.get(key) is None:
            continue
        v = _num(body[key], None)
        if v is None:
            notes.append(f"{label}: '{body[key]}' is not a number; the usual value {defaults[key]} is used.")
            continue
        lo, hi = lo_hi
        c = min(max(v, lo), hi)
        if c != v:
            notes.append(f"{label}: {v:g} is outside what the models saw in training ({lo}–{hi}); {c:g} is used.")
        used[key] = int(round(c))
    win.loc[on_day, "rooms_sold"] = used["rooms"]
    win.loc[on_day, "occupancy_pct"] = used["rooms"] / 220
    win.loc[on_day, "guests_in_house"] = used["guests"]
    win.loc[on_day, "covers_served_fnb"] = used["covers"]

    # weather
    tmpl = win.loc[on_day, "temp_c"].to_numpy().copy()
    temps, source = body.get("temps"), "typical weather for this date (the live year's)"
    if temps is not None:
        if isinstance(temps, list) and len(temps) == 24 and all(_num(x, None) is not None for x in temps):
            temps, source = [float(x) for x in temps], "hourly temperatures given"
        else:
            notes.append("temps must be 24 hourly numbers; ignored.")
            temps = None
    if temps is None and body.get("tmax") is not None:
        tm = _num(body["tmax"], None)
        if tm is None:
            notes.append(f"tmax '{body['tmax']}' is not a number; ignored.")
        else:
            temps, source = list(tmpl + (tm - tmpl.max())), f"typical daily shape shifted to a top of {tm:g} °C"
    if temps is None and 0 <= (day.date() - today).days <= 15:
        t = _open_meteo(date, notes)
        if t:
            temps, source = t, "Open-Meteo hourly forecast"
    if temps is not None:
        clamped = [min(max(t, x - OP.MAX_DT), x + OP.MAX_DT) for t, x in zip(temps, tmpl)]
        if any(abs(a - b) > 1e-9 for a, b in zip(clamped, temps)):
            notes.append(f"Some temperatures are more than {OP.MAX_DT:g} °C from the usual for this date; they are limited to that range.")
        win.loc[on_day, "temp_c"] = clamped

    # bookings
    bookings = []
    for i, b in enumerate(body.get("bookings") or []):
        if not isinstance(b, dict):
            notes.append(f"Booking {i + 1} is not an object; skipped.")
            continue
        hall = str(b.get("hall", "")).upper().replace(" ", "").replace("HALL", "").replace("&", "+")
        hall = {"AB": "A+B", "BOTH": "A+B"}.get(hall, hall)
        if hall not in HALL_EVENT:
            notes.append(f"Booking {i + 1}: hall '{b.get('hall')}' is not A, B or A+B; skipped.")
            continue
        st, en = _hhmm(b.get("start")), _hhmm(b.get("end"))
        if st is None or en is None:
            notes.append(f"Booking {i + 1}: start and end must be times like 14:00; skipped.")
            continue
        g = _num(b.get("guests"), None)
        if g is None or g <= 0:
            notes.append(f"Booking {i + 1}: guests must be a positive number; skipped.")
            continue
        style = "social" if hall == "A+B" else "corporate"
        cap = rng["event_guests"][style]
        if g > cap:
            notes.append(f"Booking {i + 1}: {g:,.0f} guests is more than any {'wedding' if style == 'social' else 'conference'} in the training year "
                         f"({cap:,}); the forecast uses {cap:,}. Treat the result as a lower bound and check hall capacity.")
            g = cap
        s, e = booking_hours(st, en)
        lo, hi = rng["event_start_hours"]
        if not lo <= s <= hi:
            notes.append(f"Booking {i + 1}: events in the training year started between {lo:02d}:00 and {hi:02d}:00; a {st} start is outside that, "
                         "so the forecast for those hours is an extrapolation.")
        if e - s > 16:
            notes.append(f"Booking {i + 1}: {e - s} hours is longer than any event in the training year.")
        bookings.append(dict(hall=hall, start=st, end=en, guests=int(round(g))))

    frame = add_bookings(win, day, bookings)
    p = predict(MODELS, frame)
    kw, tr, kva = (list(map(float, p[k][on_day])) for k in ("kw", "tr", "kva"))
    temp = list(map(float, frame.loc[on_day, "temp_c"]))
    ref = dict(REFS[date], curve=META["curve"], ahu_overrun_kwh=META["ahu_overrun_kwh"])
    acts = OP.plan_day(tr, kva, temp, bookings, META["pf"], ref, META["tariff"])
    risk = OP.risk_for(kva, META["risk"])
    r1 = lambda xs: [round(x, 1) for x in xs]
    return {
        "date": date, "site": META["site"], "recommend_only": True,
        "inputs_used": dict(used, bookings=bookings, weather=source),
        "notes": notes,
        "forecast": dict(hours=list(range(24)), kw=r1(kw), kva=r1(kva), tr=r1(tr), temp_c=r1(temp)),
        "risk": {k: (round(v, 1) if isinstance(v, float) else v) for k, v in risk.items()},
        "actions": [{k: (round(v, 1) if isinstance(v, float) else v) for k, v in a.items()} for a in acts],
        "total_saving_inr": round(sum(a["saving_inr"] for a in acts)),
        "models": dict(trained_on=META["trained_on"], context=META["context"]),
        "ms": round((time.perf_counter() - t0) * 1000),
    }
