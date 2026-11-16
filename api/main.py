"""Saffron Suites forecast / plan API (Gurugram, Jaipur, Goa) on Cloud Run. RECOMMEND ONLY: it returns a plan; it controls nothing.

GET  /health    -> ok, what the models were trained on, the dates covered, per hotel.
POST /plan      -> for one date and hotel: hourly forecast (kW, peak kVA, cooling TR), peak-demand risk and the timed operating plan with ₹
                   savings and guardrails, plus plain-English notes about the inputs.
POST /forecast  -> the same request: only the hourly forecast and the notes.
POST /risk      -> the same request: only the peak-demand risk and the notes.
POST /check     -> plan vs actual for a date (and hotel); POST /savings -> plan savings for a month (and hotel).

Body (all optional): {"date": "YYYY-MM-DD" (default tomorrow, IST), "site": "GGN" | "JAI" | "GOA" (default GGN), "rooms": int,
                      "guests": int (in house), "covers": int, "tmax": number or "temps": [24 hourly °C],
                      "bookings": [{"hall": ..., "start": "HH:MM", "end": "HH:MM", "guests": int}]}
Halls / venues: Gurugram "A" | "B" | "A+B"; Jaipur "Palace Lawns" | "Durbar Hall"; Goa "Sunset Deck + Ballroom" (aliases such as "lawns",
"durbar", "ballroom" are accepted; unknown venues are skipped with a note).

How: the frozen models in models/ (fitted on Oct 2025 - Sep 2026 only; tools/export_api_models.py, tools/train_api_models.py) are run on
the day's context with the inputs applied, then src/operating_plan.py builds the plan (Gurugram: the same rules as the web page,
web/src/plan.ts; Jaipur / Goa: only the levers their sub-meters can size and check). Inputs outside what the models saw in training are
clamped or flagged in `notes`, never an error, so a planner always gets an answer and the reason it may be less certain; aliases
(rooms_occupied, guests_in_house, restaurant_covers) are accepted and unknown fields are listed as ignored. Only a date outside the live
year (or an unknown hotel) returns 422. Weather: the hourly temperatures given, else the Open-Meteo hourly forecast when the date is
within its 16 days, else the typical weather for that date.
"""
import json
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import operating_plan as OP
import plan_check as PC
from plan_models import HALL_EVENT, add_bookings, booking_hours, predict

ROOT = Path(__file__).resolve().parents[1]
M = ROOT / "models"
MODELS = joblib.load(M / "plan_models.joblib")
CTX = pd.read_parquet(M / "context.parquet")
REFS = json.loads((M / "refs.json").read_text(encoding="utf-8"))
META = json.loads((M / "meta.json").read_text(encoding="utf-8"))
LIVE = pd.read_parquet(M / "live_meters.parquet")             # simulated live-year meters; every read is cut at the current IST hour
IST = timezone(timedelta(hours=5, minutes=30))
COORDS = {"GGN": (28.46, 77.03), "JAI": (26.91, 75.79), "GOA": (15.49, 73.83)}
HOTEL = {"GGN": "Gurugram", "JAI": "Jaipur", "GOA": "Goa"}
# per hotel: models, context, matched-day refs, meta, live meters (Gurugram's are the files above; Jaipur / Goa from tools/train_api_models.py)
RES = {"GGN": dict(models=MODELS, ctx=CTX, refs=REFS, meta=META, live=LIVE)}
for _s in ("JAI", "GOA"):
    if _s in META.get("sites", {}):
        RES[_s] = dict(models=joblib.load(M / f"plan_models_{_s}.joblib"), ctx=pd.read_parquet(M / f"context_{_s}.parquet"),
                       refs=json.loads((M / f"refs_{_s}.json").read_text(encoding="utf-8")), meta=META["sites"][_s],
                       live=pd.read_parquet(M / f"live_meters_{_s}.parquet"))

app = FastAPI(title="Saffron Suites plan API", version="1.1", description="Forecast and operating plan for Gurugram, Jaipur and Goa. Recommend only.")


def _num(x, default):
    try:
        v = float(x)
        return v if v == v else default
    except (TypeError, ValueError):
        return default


START_SLACK_MIN = 60     # a start within 1 h of the training range is ordinary; only further out is flagged as an extrapolation


def _far_from(st: str, lo: int, hi: int) -> bool:
    """True when an HH:MM start is more than START_SLACK_MIN outside the training start hours [lo:00, hi:00]."""
    m = int(st[:2]) * 60 + int(st[3:])
    return m < lo * 60 - START_SLACK_MIN or m > hi * 60 + START_SLACK_MIN


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


def _open_meteo(date: str, notes: list, site: str = "GGN") -> list | None:
    hit = _WX.get((site, date))
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    try:
        lat, lon = COORDS[site]
        url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m"
               f"&timezone=Asia%2FKolkata&start_date={date}&end_date={date}")
        with urllib.request.urlopen(url, timeout=3) as r:
            j = json.load(r)
        t = j["hourly"]["temperature_2m"]
        t = t if len(t) == 24 and all(v is not None for v in t) else None
        _WX[(site, date)] = (time.time(), t)
        return t
    except Exception:                                       # no forecast for that date, or the service is slow: use typical weather
        notes.append("The live weather forecast could not be read; the typical weather for this date is used.")
        return None


@app.get("/health")
def health():
    hotels = {"GGN": dict(dates=META["dates"], cooling_model_cv_rmse_pct=META["cooling_model"]["hourly_cv_rmse_pct"])}
    for s, r in RES.items():
        if s != "GGN":
            a = r["meta"]["accuracy"]
            hotels[s] = dict(dates=r["meta"]["dates"], cv_rmse_pct={k: a[k]["hourly_cv_rmse_pct"] for k in ("kw", "tr", "kva")})
    return {"status": "ok", "site": META["site"], "sites": sorted(RES), "models_trained_on": META["trained_on"], "dates": META["dates"],
            "cooling_model_cv_rmse_pct": META["cooling_model"]["hourly_cv_rmse_pct"], "hotels": hotels, "recommend_only": True}



# ---- reading the request: every input is used, corrected with a note, or reported as ignored; nothing is dropped silently ----------
FIELDS = {"date", "site", "rooms", "guests", "covers", "tmax", "temps", "bookings"}
ALIASES = {"rooms_occupied": "rooms", "rooms_sold": "rooms", "guests_in_house": "guests", "restaurant_covers": "covers", "covers_served": "covers"}
BOOKING_FIELDS = {"hall", "start", "end", "guests"}
BOOKING_ALIASES = {"venue": "hall", "start_time": "start", "end_time": "end", "pax": "guests", "guest_count": "guests"}
SITE_ALIASES = {"GGN": "GGN", "GURUGRAM": "GGN", "GURGAON": "GGN", "JAI": "JAI", "JAIPUR": "JAI", "GOA": "GOA"}
# Jaipur / Goa venues come from each hotel's events calendar (models/meta.json); these are only the extra names people type for them
VENUE_ALIASES = {"JAI": {"Palace Lawns": ("lawns", "lawn", "palacelawn", "palace", "lawnwedding"), "Durbar Hall": ("durbar", "hall", "durbarhall")},
                 "GOA": {"Sunset Deck + Ballroom": ("ballroom", "sunsetdeck", "deck", "sunset", "beach", "sunsetdeckballroom", "sunsetdeckandballroom")}}
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


def _key(x) -> str:
    return re.sub(r"[^a-z0-9]", "", str(x or "").lower())


def venue_of(site: str, raw, venues: dict) -> str | None:
    """The hotel's venue for what was typed: exact name, then the aliases; None if it is not one of this hotel's venues."""
    k = _key(raw)
    for v in venues:
        if k == _key(v) or k in VENUE_ALIASES.get(site, {}).get(v, ()):
            return v
    return None


def read_site_bookings(site: str, raw, meta: dict, notes: list) -> list:
    """Jaipur / Goa bookings: venue validated against the hotel's own venues; guests capped at the largest event there last year; overlapping
    bookings at one venue are one event. Same rules for times as Gurugram."""
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        notes.append("bookings must be a list; ignored.")
        return []
    venues, rng = meta["config"]["venues"], meta["ranges"]
    names = ", ".join(venues)
    items = []
    for i, b0 in enumerate(raw, 1):
        if not isinstance(b0, dict):
            notes.append(f"Booking {i} is not an object; skipped.")
            continue
        b = _fold(b0, BOOKING_FIELDS, BOOKING_ALIASES, f"Booking {i}: ", notes)
        v = venue_of(site, b.get("hall"), venues)
        if v is None:
            notes.append(f"Booking {i}: '{b.get('hall')}' is not a {HOTEL[site]} venue ({names}); skipped.")
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
        cap = rng["event_guests"][v]
        if g > cap:
            notes.append(f"Booking {i}: {g:,.0f} guests is more than any event at {v} in the training year ({cap:,}); the forecast uses {cap:,}. "
                         "Treat the result as a lower bound and check the venue's capacity.")
            g = cap
        s, e = booking_hours(st, en)
        lo, hi = rng["event_start_hours"][v]
        if _far_from(st, lo, hi):
            when = f"at {lo:02d}:00" if lo == hi else f"between {lo:02d}:00 and {hi:02d}:00"
            notes.append(f"Booking {i}: events at {v} in the training year started {when}; a {st} start is more than 1 h outside that, so the "
                         "forecast for those hours is an extrapolation.")
        if e - s > 16:
            notes.append(f"Booking {i}: {e - s} hours is longer than any event in the training year.")
        if str(b.get("hall")).strip() != v:
            notes.append(f"Booking {i}: '{b.get('hall')}' read as {v}.")
        items.append(dict(n=[i], hall=v, s=s, e=e, guests=int(round(g)), late=en == "23:59", start=st, end=en))
    merged = True
    while merged:
        merged = False
        for a in range(len(items)):
            for c in range(a + 1, len(items)):
                x, y = items[a], items[c]
                if x["hall"] == y["hall"] and x["s"] < y["e"] and y["s"] < x["e"]:
                    s, e = min(x["s"], y["s"]), max(x["e"], y["e"])
                    late = (x["late"] and x["e"] == e) or (y["late"] and y["e"] == e)
                    m = dict(n=x["n"] + y["n"], hall=x["hall"], s=s, e=e, guests=max(x["guests"], y["guests"]), late=late,
                             start=x["start"] if x["s"] == s else y["start"], end=_end_label(e, late))
                    notes.append(f"Bookings {'+'.join(map(str, x['n']))} and {'+'.join(map(str, y['n']))} overlap at {x['hall']}; treated as one event "
                                 f"{m['start']}–{m['end']} with {m['guests']} guests (the larger count).")
                    items[a] = m
                    del items[c]
                    merged = True
                    break
            if merged:
                break
    return [dict(hall=b["hall"], start=b["start"], end=b["end"], guests=b["guests"]) for b in items]


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
        if _far_from(st, lo, hi):
            notes.append(f"Booking {i}: events in the training year started between {lo:02d}:00 and {hi:02d}:00; a {st} start is more than 1 h "
                         "outside that, so the forecast for those hours is an extrapolation.")
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


async def _read_body(req: Request, notes: list) -> dict:
    try:
        body = await req.json()
    except Exception:
        body = None
    if body is None:
        notes.append("The request had no readable JSON body; everything below comes from the usual pattern.")
        return {}
    if not isinstance(body, dict):
        notes.append("The request body must be a JSON object; it was ignored.")
        return {}
    return body


@app.post("/plan")
async def plan(req: Request):
    notes: list[str] = []
    body = await _read_body(req, notes)
    status, out = compute_plan(body, notes)
    return out if status == 200 else JSONResponse(out, status_code=status)


@app.post("/forecast")
async def forecast_ep(req: Request):
    """The hourly forecast for the request (same body as /plan), without the plan."""
    notes: list[str] = []
    body = await _read_body(req, notes)
    status, out = compute_plan(body, notes)
    if status != 200:
        return JSONResponse(out, status_code=status)
    return {k: out[k] for k in ("date", "site", "hotel", "recommend_only", "inputs_used", "notes", "forecast", "models")}


@app.post("/risk")
async def risk_ep(req: Request):
    """The peak-demand risk for the request (same body as /plan), against that hotel's contract demand."""
    notes: list[str] = []
    body = await _read_body(req, notes)
    status, out = compute_plan(body, notes)
    if status != 200:
        return JSONResponse(out, status_code=status)
    return {k: out[k] for k in ("date", "site", "hotel", "recommend_only", "inputs_used", "notes", "risk", "contract_kva", "models")}


def site_of(raw) -> str | None:
    return SITE_ALIASES.get(str(raw or "GGN").strip().upper().replace(" ", ""))


def compute_plan(body: dict, notes: list) -> tuple[int, dict]:
    """The plan for one date and hotel from the request body (also used by /check for the suggested plan). Returns (HTTP status, payload)."""
    t0 = time.perf_counter()
    body = _fold(body, FIELDS, ALIASES, "", notes)

    site = site_of(body.get("site"))
    if site is None or site not in RES:
        return 422, {"error": f"Unknown site '{body.get('site')}'. Hotels: GGN (Gurugram), JAI (Jaipur), GOA (Goa).", "notes": notes}
    R = RES[site]
    meta, refs = R["meta"], R["refs"]

    today = datetime.now(IST).date()
    date = str(body.get("date") or (today + timedelta(days=1)).isoformat()).strip()
    try:
        day = pd.Timestamp(datetime.strptime(date, "%Y-%m-%d"))
    except ValueError:
        return 422, {"error": f"date '{date}' must be YYYY-MM-DD.", "notes": notes}
    if date not in refs:
        return 422, {"error": f"No plan context for {date}. Dates covered: {meta['dates'][0]} to {meta['dates'][1]}.", "notes": notes}
    ahead = (day.date() - today).days
    if ahead < 0:
        notes.append(f"{date} is in the past: this is a look-back forecast (what the models expect for that day with these inputs), not the meter "
                     "readings for it; those are on Today and Equipment.")
    if "date" not in body:
        notes.append(f"No date given; tomorrow ({date}) is planned.")

    ctx = R["ctx"]
    win = ctx[(ctx.timestamp >= day - pd.Timedelta(days=1)) & (ctx.timestamp < day + pd.Timedelta(days=2))].reset_index(drop=True)
    on_day = ((win.timestamp >= day) & (win.timestamp < day + pd.Timedelta(days=1))).to_numpy()
    rng = meta["ranges"]

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
    win.loc[on_day, "occupancy_pct"] = used["rooms"] / rng["rooms"][1]
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
            t = _open_meteo(date, notes, site)
            if t:
                temps, source = t, "Open-Meteo hourly forecast"
        elif ahead > 15:
            notes.append("No weather forecast that far ahead; typical temperatures for the date are used.")
    if temps is not None:
        clamped = [min(max(t, x - OP.MAX_DT), x + OP.MAX_DT) for t, x in zip(temps, tmpl)]
        if any(abs(a - b) > 1e-9 for a, b in zip(clamped, temps)):
            notes.append(f"Some temperatures are more than {OP.MAX_DT:g} °C from the usual for this date; they are limited to that range.")
        win.loc[on_day, "temp_c"] = clamped

    if site == "GGN":
        bookings = read_bookings(body.get("bookings"), rng, notes)
    else:
        bookings = read_site_bookings(site, body.get("bookings"), meta, notes)
    if from_pattern:
        notes.append(f"From the usual pattern for a {WEEKDAY[day.day_of_week]} at this time of year: {', '.join(from_pattern)}.")
    if not body.get("bookings"):
        notes.append("No banquet bookings were given, so none are planned for." if site == "GGN" else "No event bookings were given, so none are planned for.")

    frame = add_bookings(win, day, bookings, None if site == "GGN" else meta["config"]["venues"])
    p = predict(R["models"], frame, site)
    kw, tr, kva = (list(map(float, p[k][on_day])) for k in ("kw", "tr", "kva"))
    temp = list(map(float, frame.loc[on_day, "temp_c"]))
    if site == "GGN":
        ref = dict(refs[date], curve=META["curve"], ahu_overrun_kwh=META["ahu_overrun_kwh"], chw_pct_per_c=META.get("chw_pct_per_c"))
        acts = OP.plan_day(tr, kva, temp, bookings, META["pf"], ref, META["tariff"])
        cd = 1000.0
    else:
        ref = dict(refs[date], curve=meta["curve"])
        acts = OP.plan_day(tr, kva, temp, bookings, meta["pf"], ref, meta["tariff"], site=site, cfg=meta["config"])
        cd = meta["config"]["cd_kva"]
    risk = OP.risk_for(kva, meta["risk"])
    r1 = lambda xs: [round(x, 1) for x in xs]
    out = {
        "date": date, "site": site, "hotel": HOTEL[site], "recommend_only": True,
        "inputs_used": dict(used, bookings=bookings, weather=source),
        "notes": notes,
        "forecast": dict(hours=list(range(24)), kw=r1(kw), kva=r1(kva), tr=r1(tr), temp_c=r1(temp)),
        "risk": {k: (round(v, 1) if isinstance(v, float) else v) for k, v in risk.items()},
        "contract_kva": cd,
        "actions": [{k: (round(v, 1) if isinstance(v, float) else v) for k, v in a.items()} for a in acts],
        "total_saving_inr": round(sum(a["saving_inr"] for a in acts)),
        "models": dict(trained_on=meta["trained_on"], context=meta["context"]),
        "ms": round((time.perf_counter() - t0) * 1000),
    }
    if site != "GGN":
        out["equipment"] = dict(chillers=meta["config"]["chillers"]["rating"], venues=list(meta["config"]["venues"]),
                                pool_pumps=(meta["config"]["pool"] or {}).get("rating"), peak_window=meta["config"]["peak"])
        out["models"]["cv_rmse_pct"] = {k: meta["accuracy"][k]["hourly_cv_rmse_pct"] for k in ("kw", "tr", "kva")}
        out["not_counted_inr"] = round(sum(a.get("estimate_inr", 0.0) for a in acts))
    return 200, out


# ---- plan vs actual (src/plan_check.py): live meters cut at the current IST hour; never later ---------------------------------------
_CHECK: dict = {}                                            # finished days don't change: cache their check by (date, plan)


def _as_of(raw) -> str:
    now = datetime.now(IST).strftime("%Y-%m-%dT%H:%M")
    a = str(raw or "")[:16]
    return a if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", a) and a < now else now      # look back is allowed; ahead is not


def _check(date: str, actions: list | None, as_of: str, suggested: bool = False, site: str = "GGN") -> tuple[int, dict]:
    notes: list[str] = []
    source = "suggested plan (no plan was saved for this day)" if suggested else "saved plan"
    if not actions:
        suggested = True
        st, p = compute_plan({"date": date, "site": site}, [])
        if st != 200:
            return st, p
        actions, source = p["actions"], "suggested plan (no plan was saved for this day: usual pattern, no bookings)"
        notes.append("No plan was saved for this day: the suggested plan is shown with what it would have saved, but nothing is checked or counted.")
    if date > as_of[:10]:
        return 200, dict(date=date, site=site, as_of=as_of, source=source, notes=notes + ["This day has not started yet; nothing to check."],
                         honesty=PC.HONESTY, steps=[], alerts=[], covered={}, summary=dict(steps=len(actions), due=0, followed=0, partly=0,
                         not_followed=0, not_yet_due=len(actions), cant_tell=0, planned_inr=round(sum(a.get("saving_inr", 0) for a in actions), 1),
                         verified_inr=0.0, missed_inr=0.0))
    final = as_of[:10] > (pd.Timestamp(date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")      # next day over too: water heating window done
    key = (site, date, json.dumps(actions, sort_keys=True), suggested, "final" if final else as_of[:13])
    if key not in _CHECK:
        R = RES[site]
        if site == "GGN":
            ref = dict(REFS[date], curve=META["curve"], ahu_overrun_kwh=META["ahu_overrun_kwh"], chw_pct_per_c=META.get("chw_pct_per_c"))
            _CHECK[key] = PC.check_day(date, actions, PC.meters_for(LIVE, date), as_of, ref, META["tariff"], META["pf"], suggested=suggested)
        else:
            m = R["meta"]
            _CHECK[key] = PC.check_day(date, actions, PC.meters_for(R["live"], date), as_of, dict(R["refs"][date], curve=m["curve"]), m["tariff"], m["pf"],
                                       suggested=suggested, site=site, cfg=m["config"])
    out = dict(_CHECK[key], source=source, notes=notes)
    return 200, out


@app.post("/check")
async def check(req: Request):
    """Plan vs actual for one date: {date, site?, as_of?, actions? (the saved plan's steps; omitted = the suggested plan)}."""
    notes: list[str] = []
    b = await _read_body(req, notes)
    site = site_of(b.get("site"))
    if site is None or site not in RES:
        return JSONResponse({"error": f"Unknown site '{b.get('site')}'. Hotels: GGN, JAI, GOA."}, status_code=422)
    date = str(b.get("date") or datetime.now(IST).date().isoformat())
    m = RES[site]["meta"]
    if date not in RES[site]["refs"]:
        return JSONResponse({"error": f"No plan context for {date}. Dates covered: {m['dates'][0]} to {m['dates'][1]}."}, status_code=422)
    acts = b.get("actions") if isinstance(b.get("actions"), list) else None
    sugg = b.get("plan_source") == "suggested"                           # the page sends the suggested plan it shows
    st, out = _check(date, acts, _as_of(b.get("as_of")), suggested=sugg, site=site)
    if st == 200 and acts and sugg:
        out["notes"] = ["No plan was saved for this day: the suggested plan is shown with what it would have saved, but nothing is checked or counted."] + out["notes"]
    if st == 200:
        out["notes"] = notes + out["notes"]
    return out if st == 200 else JSONResponse(out, status_code=st)


@app.post("/savings")
async def savings(req: Request):
    """Plan savings for a month, day by day, up to now: {month: YYYY-MM, site?, as_of?, saved?: {date: actions}}. Planned vs verified ₹ (plan only;
    alert ₹ are a separate stream) and the hours each followed step covers, so the alert side can avoid counting them twice."""
    notes: list[str] = []
    b = await _read_body(req, notes)
    as_of = _as_of(b.get("as_of"))
    month = str(b.get("month") or as_of[:7])
    saved = b.get("saved") if isinstance(b.get("saved"), dict) else {}
    site = site_of(b.get("site"))
    if site is None or site not in RES:
        return JSONResponse({"error": f"Unknown site '{b.get('site')}'. Hotels: GGN, JAI, GOA."}, status_code=422)
    days = [d for d in sorted(RES[site]["refs"]) if d.startswith(month) and d <= as_of[:10]]
    if not days:
        return JSONResponse({"error": f"No live-year days to check for {month} up to {as_of[:10]}."}, status_code=422)
    rows = []
    for d in days:
        st, c = _check(d, saved.get(d) or None, as_of, site=site)
        if st != 200:
            continue
        rows.append(dict(date=d, source="saved" if saved.get(d) else "suggested", **{k: c["summary"][k] for k in ("planned_inr", "verified_inr", "missed_inr",
                         "would_have_saved_inr", "approved", "followed", "partly", "not_followed", "due", "steps")}, covered=c["covered"], deviations=len(c["alerts"])))
    tot = lambda k: round(sum(r[k] for r in rows), 1)
    return dict(month=month, site=site, as_of=as_of, honesty=PC.HONESTY, days=rows, notes=notes,
                totals=dict(planned_inr=tot("planned_inr"), verified_inr=tot("verified_inr"), missed_inr=tot("missed_inr"), days=len(rows),
                            would_have_saved_inr=tot("would_have_saved_inr"), approved_steps=sum(r["approved"] for r in rows),
                            saved_days=sum(1 for r in rows if r["source"] == "saved")),
                method="Only approved steps of saved plans count. Verified = approved steps that were followed, actual meters vs how matched days ran last year (same month, day type, cooling load), "
                       "at the plan's tariff prices; never added to alert savings for the same hours.")
