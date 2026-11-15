"""Saffron Suites forecast / plan API (Gurugram) on Cloud Run. RECOMMEND ONLY: it returns a plan; it controls nothing.

GET  /health  -> ok, what the models were trained on, the dates covered.
POST /plan    -> for one date: hourly forecast (kW, peak kVA, cooling TR), peak-demand risk and the timed operating plan with ₹ savings and
                 guardrails, plus plain-English notes about the inputs.

Body (all optional): {"date": "YYYY-MM-DD" (default tomorrow, IST), "site": "GGN" (Jaipur / Goa: 422 for now), "rooms": int, "guests": int (in house), "covers": int,
                      "tmax": number or "temps": [24 hourly °C], "bookings": [{"hall": "A" | "B" | "A+B", "start": "HH:MM", "end": "HH:MM", "guests": int}]}

How: the frozen models in models/ (fitted on Oct 2025 - Sep 2026 only; tools/export_api_models.py) are run on the day's context with the
inputs applied, then src/operating_plan.py builds the plan (the same rules as the web page, web/src/plan.ts). Inputs outside what the
models saw in training are clamped or flagged in `notes`, never an error, so a planner always gets an answer and the reason it may be
less certain; aliases (rooms_occupied, guests_in_house, restaurant_covers) are accepted and unknown fields are listed as ignored. Weather: the hourly temperatures given, else the Open-Meteo hourly forecast when the date is within its 16 days, else the
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



# ---- reading the request: every input is used, corrected with a note, or reported as ignored; nothing is dropped silently ----------
FIELDS = {"date", "site", "rooms", "guests", "covers", "tmax", "temps", "bookings"}
ALIASES = {"rooms_occupied": "rooms", "rooms_sold": "rooms", "guests_in_house": "guests", "restaurant_covers": "covers", "covers_served": "covers"}
BOOKING_FIELDS = {"hall", "start", "end", "guests"}
BOOKING_ALIASES = {"venue": "hall", "start_time": "start", "end_time": "end", "pax": "guests", "guest_count": "guests"}
SITE_OK = {"GGN", "GURUGRAM", "GURGAON"}
SITE_LATER = {"JAI", "JAIPUR", "GOA"}
LATER_MSG = "Day plans are available for Gurugram; Jaipur and Goa are coming next."
WEEKDAY = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
HALLS_OF = {"A": {"A"}, "B": {"B"}, "A+B": {"A", "B"}}


def _fold(d: dict, known: set, aliases: dict, where: str, notes: list) -> dict:
    """Map aliases to their field, note conflicts, and list every unknown field as ignored."""
    out = {}
    for k, v in d.items():
        key = str(k).strip()
        canon = key if key in known else aliases.get(key.lower(), aliases.get(key))
        if canon is None:
            notes.append(f"{where}ignored field: {key}")
            continue
        if canon in out and out[canon] != v:
            notes.append(f"{where}both '{canon}' and an alias for it were given; '{key}' = {v!r} is used.")
        out[canon] = v
    return out


def _end_label(e: int, was_2359: bool) -> str:
    """End hour (may be >= 24, i.e. next day) back to the HH:MM form booking_hours() reads."""
    if was_2359 and e == 25:
        return "23:59"
    return f"{e % 24:02d}:00"


def read_bookings(raw, rng: dict, notes: list) -> list:
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        notes.append("bookings must be a list; ignored.")
        return []
    items = []
    for i, b0 in enumerate(raw, 1):
        if not isinstance(b0, dict):
            notes.append(f"Booking {i} is not an object; skipped.")
            continue
        b = _fold(b0, BOOKING_FIELDS, BOOKING_ALIASES, f"Booking {i}: ", notes)
        hall = str(b.get("hall", "")).upper().replace(" ", "").replace("HALL", "").replace("&", "+").replace("BANQUET", "")
        hall = {"AB": "A+B", "BOTH": "A+B", "A+B": "A+B"}.get(hall, hall)
        if hall not in HALL_EVENT:
            notes.append(f"Booking {i}: hall '{b.get('hall')}' is not A, B or A+B; skipped.")
            continue
        st, en = _hhmm(b.get("start")), _hhmm(b.get("end"))
        if st is None or en is None:
            notes.append(f"Booking {i}: start and end must be times like 14:00; skipped.")
            continue
        g = _num(b.get("guests"), None)
        if g is None or g <= 0:
            notes.append(f"Booking {i}: guests must be a positive number; skipped.")
            continue
        if en != "23:59" and (int(en[:2]) * 60 + int(en[3:])) <= (int(st[:2]) * 60 + int(st[3:])):
            notes.append(f"Booking {i} ends before it starts ({st} to {en}); treated as running past midnight to {en} next day.")
        style = "social" if hall == "A+B" else "corporate"
        cap = rng["event_guests"][style]
        if g > cap:
            notes.append(f"Booking {i}: {g:,.0f} guests is more than any {'wedding' if style == 'social' else 'conference'} in the training year "
                         f"({cap:,}); the forecast uses {cap:,}. Treat the result as a lower bound and check hall capacity.")
            g = cap
        s, e = booking_hours(st, en)
        lo, hi = rng["event_start_hours"]
        if not lo <= s <= hi:
            notes.append(f"Booking {i}: events in the training year started between {lo:02d}:00 and {hi:02d}:00; a {st} start is outside that, "
                         "so the forecast for those hours is an extrapolation.")
        if e - s > 16:
            notes.append(f"Booking {i}: {e - s} hours is longer than any event in the training year.")
        items.append(dict(n=[i], hall=hall, s=s, e=e, guests=int(round(g)), late=en == "23:59", start=st, end=en))

    # overlapping bookings that share a hall are one event: the hall can't host two at once
    merged = True
    while merged:
        merged = False
        for a in range(len(items)):
            for c in range(a + 1, len(items)):
                x, y = items[a], items[c]
                if HALLS_OF[x["hall"]] & HALLS_OF[y["hall"]] and x["s"] < y["e"] and y["s"] < x["e"]:
                    halls = HALLS_OF[x["hall"]] | HALLS_OF[y["hall"]]
                    hall = "A+B" if halls == {"A", "B"} else x["hall"]
                    s, e = min(x["s"], y["s"]), max(x["e"], y["e"])
                    late = (x["late"] and x["e"] == e) or (y["late"] and y["e"] == e)
                    m = dict(n=x["n"] + y["n"], hall=hall, s=s, e=e, guests=max(x["guests"], y["guests"]), late=late,
                             start=f"{s:02d}:00" if s != x["s"] else x["start"], end=_end_label(e, late))
                    if s == y["s"]:
                        m["start"] = y["start"]
                    lab = lambda z: f"{z['n'][0] if len(z['n']) == 1 else 'group ' + '+'.join(map(str, z['n']))} (Hall {z['hall']} {z['start']}–{z['end']}, {z['guests']} guests)"
                    notes.append(f"Bookings {lab(x)} and {lab(y)} overlap in the same hall; treated as one event in Hall {hall} {m['start']}–{m['end']} "
                                 f"with {m['guests']} guests (the larger count).")
                    items[a] = m
                    del items[c]
                    merged = True
                    break
            if merged:
                break
    return [dict(hall=b["hall"], start=b["start"], end=b["end"], guests=b["guests"]) for b in items]


@app.post("/plan")
async def plan(req: Request):
    t0 = time.perf_counter()
    notes: list[str] = []
    try:
        body = await req.json()
    except Exception:
        body = None
    if body is None:
        body = {}
        notes.append("The request had no readable JSON body; everything below comes from the usual pattern.")
    if not isinstance(body, dict):
        notes.append("The request body must be a JSON object; it was ignored.")
        body = {}
    body = _fold(body, FIELDS, ALIASES, "", notes)

    site = str(body.get("site") or "GGN").strip().upper()
    if site in SITE_LATER:
        return JSONResponse({"error": LATER_MSG, "site": site, "notes": notes}, status_code=422)
    if site not in SITE_OK:
        return JSONResponse({"error": f"Unknown site '{body.get('site')}'. {LATER_MSG}", "notes": notes}, status_code=422)

    today = datetime.now(IST).date()
    date = str(body.get("date") or (today + timedelta(days=1)).isoformat()).strip()
    try:
        day = pd.Timestamp(datetime.strptime(date, "%Y-%m-%d"))
    except ValueError:
        return JSONResponse({"error": f"date '{date}' must be YYYY-MM-DD.", "notes": notes}, status_code=422)
    if date not in REFS:
        return JSONResponse({"error": f"No plan context for {date}. Dates covered: {META['dates'][0]} to {META['dates'][1]}.", "notes": notes}, status_code=422)
    ahead = (day.date() - today).days
    if ahead < 0:
        notes.append(f"{date} is in the past: this is a look-back forecast (what the models expect for that day with these inputs), not the meter "
                     "readings for it; those are on Today and Equipment.")
    if "date" not in body:
        notes.append(f"No date given; tomorrow ({date}) is planned.")

    win = CTX[(CTX.timestamp >= day - pd.Timedelta(days=1)) & (CTX.timestamp < day + pd.Timedelta(days=2))].reset_index(drop=True)
    on_day = ((win.timestamp >= day) & (win.timestamp < day + pd.Timedelta(days=1))).to_numpy()
    rng = META["ranges"]

    # occupancy: given values replace the day's usual ones, clamped to what the models saw
    defaults = dict(rooms=int(win.loc[on_day, "rooms_sold"].iloc[0]), guests=int(win.loc[on_day, "guests_in_house"].iloc[0]),
                    covers=int(win.loc[on_day, "covers_served_fnb"].iloc[0]))
    used, from_pattern = dict(defaults), []
    for key, lo_hi, label in (("rooms", rng["rooms"], "rooms occupied"), ("guests", rng["guests_in_house"], "guests in house"),
                              ("covers", rng["covers"], "restaurant covers")):
        if body.get(key) is None:
            from_pattern.append(f"{label} {defaults[key]}")
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
    temps, source = body.get("temps"), "typical temperatures for this date"
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
    if temps is None:
        if 0 <= ahead <= 15:
            t = _open_meteo(date, notes)
            if t:
                temps, source = t, "Open-Meteo hourly forecast"
        elif ahead > 15:
            notes.append("No weather forecast that far ahead; typical temperatures for the date are used.")
    if temps is not None:
        clamped = [min(max(t, x - OP.MAX_DT), x + OP.MAX_DT) for t, x in zip(temps, tmpl)]
        if any(abs(a - b) > 1e-9 for a, b in zip(clamped, temps)):
            notes.append(f"Some temperatures are more than {OP.MAX_DT:g} °C from the usual for this date; they are limited to that range.")
        win.loc[on_day, "temp_c"] = clamped

    bookings = read_bookings(body.get("bookings"), rng, notes)
    if from_pattern or not body.get("bookings"):
        bits = ", ".join(from_pattern)
        notes.append(f"From the usual pattern for a {WEEKDAY[day.day_of_week]} at this time of year: "
                     + (bits + ". " if bits else "")
                     + ("No banquet bookings were given, so none are planned for." if not body.get("bookings") else ""))

    frame = add_bookings(win, day, bookings)
    p = predict(MODELS, frame)
    kw, tr, kva = (list(map(float, p[k][on_day])) for k in ("kw", "tr", "kva"))
    temp = list(map(float, frame.loc[on_day, "temp_c"]))
    ref = dict(REFS[date], curve=META["curve"], ahu_overrun_kwh=META["ahu_overrun_kwh"], chw_pct_per_c=META.get("chw_pct_per_c"))
    acts = OP.plan_day(tr, kva, temp, bookings, META["pf"], ref, META["tariff"])
    risk = OP.risk_for(kva, META["risk"])
    r1 = lambda xs: [round(x, 1) for x in xs]
    return {
        "date": date, "site": "GGN", "recommend_only": True,
        "inputs_used": dict(used, bookings=bookings, weather=source),
        "notes": notes,
        "forecast": dict(hours=list(range(24)), kw=r1(kw), kva=r1(kva), tr=r1(tr), temp_c=r1(temp)),
        "risk": {k: (round(v, 1) if isinstance(v, float) else v) for k, v in risk.items()},
        "actions": [{k: (round(v, 1) if isinstance(v, float) else v) for k, v in a.items()} for a in acts],
        "total_saving_inr": round(sum(a["saving_inr"] for a in acts)),
        "models": dict(trained_on=META["trained_on"], context=META["context"]),
        "ms": round((time.perf_counter() - t0) * 1000),
    }
