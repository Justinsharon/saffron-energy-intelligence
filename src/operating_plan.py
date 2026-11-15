"""Gurugram operating plan: timed actions for one day from the forecast. RECOMMEND ONLY - a person approves and carries out every action.

Why a rule engine and not an optimiser: every action must be explainable in one sentence and checkable against the engineering guide's
limits. The rules are the guide's (equipment register + engineering and tariff guide); the inputs are the day-ahead forecasts exported by
tools/export_plan_inputs.py (frozen models fitted on Oct 2025 - Sep 2026). The same rules run in the browser (web/src/plan.ts) so the plan
updates when bookings change; tests/test_plan_parity.py checks the two give the same actions and ₹.

₹ saving per action = how last year ran on matched days (same month, same day type, similar cooling load; original year only) minus the
plan, priced with the tariff. Plan savings are a separate stream from alert savings (src/savings.py): never add them together.

Pure Python on lists/dicts (no pandas) so the TypeScript port can mirror it line for line.
"""
import math
import re

CH3_MAX, CH1_MAX, PAIR_MAX = 130.0, 280.0, 430.0     # TR: CH-3 alone, CH-1 alone, CH-1 + CH-3 (CH-2 unavailable)
TR_MARGIN = 1.10                                      # +10 % on forecast TR before switching up
CHW_STD, CHW_RESET, CHW_FLOOR = 7.0, 8.0, 6.5          # °C; never below 6.5
RESET_BELOW_C = 24.0                                  # 8.0 °C only when outdoor is below this
SETPOINT_PCT_PER_C = 0.035                            # guide's ~3.5 % per °C: fallback only when no measured value is supplied
PEAK = (18, 22)                                       # GGN peak tariff window [start, end)
OFFPEAK = (23, 5)                                     # GGN off-peak window (wraps midnight)
DEMAND_WATCH_KVA, CD_KVA = 920.0, 1000.0              # EV-throttle / laundry line, contract demand
LAUNDRY_KW, WATER_KW = 95.0, 80.0                     # connected kW (equipment register)
AHU = {"A": "AHU-BQ-A", "B": "AHU-BQ-B", "A+B": "AHU-BQ-A and AHU-BQ-B"}
EXCLUDED = ("kitchen exhaust", "exhaust", "make-up air", "thermostat", "guest room", "guest-room", "lift", "elevator", "fire", "life-safety", "life safety")

GUARD = {
    "chillers": "Recommendation only: the duty engineer stages the chillers. CH-3 leads below 130 TR, CH-1 alone up to 280 TR, both up to 430 TR; CH-2 is out of service. Never two chillers below 130 TR.",
    "chw": "Recommendation only. Never below 6.5 °C leaving water. Go back to 7.0 °C at once if a guest area runs warm (guest rooms 22–25 °C).",
    "ahu": "Recommendation only: the banquet team switches the AHUs. On 1 h before the event (never more than 2 h), off 1 h after it ends.",
    "laundry": "Recommendation only: the laundry supervisor schedules batches. Flexible load; no effect on guests.",
    "water": "Recommendation only. The daily ≥ 60 °C storage cycle (Legionella) must complete; if it has not by 05:00 it runs regardless.",
    "ev": "Recommendation only. Throttling is allowed above 920 kVA site demand (guide); tell affected guests first.",
}


def hh(h: int) -> str:
    return f"{h % 24:02d}:00" + (" (next day)" if h >= 24 else "")


def stage(tr: float) -> str:
    t = tr * TR_MARGIN
    return "CH-3" if t <= CH3_MAX else "CH-1" if t <= CH1_MAX else "CH-1+CH-3"


def kwtr_plan(tr: float, curve: dict) -> float | None:
    """Normal one-chiller kW/TR at this load (original-year single-chiller hours at 7.0 °C, recalibration.fit); None for two chillers."""
    if tr * TR_MARGIN > CH1_MAX:
        return None
    for hi, v in zip(curve["edges"][1:], curve["values"]):
        if tr <= hi:
            return v
    return curve["values"][-1]


def chw_pct(tr: float, ref: dict) -> float:
    """Chiller power saved per °C of warmer chilled water at this load: measured on these chillers (recalibration.fit, 5.5 vs 7.0 °C,
    per load band, divided by 1.5 °C; 4.3-6.9 %), else the guide's 3.5 %."""
    pct = ref.get("chw_pct_per_c")
    if not pct:
        return SETPOINT_PCT_PER_C
    for hi, v in zip(ref["curve"]["edges"][1:], pct):
        if tr <= hi:
            return v
    return pct[-1]


def in_win(h: int, w: tuple) -> bool:
    a, b = w
    return a <= h < b if a < b else (h >= a or h < b)


def windows(keys: list) -> list:
    """Runs of equal keys over the 24 hours: [(start_h, end_h_exclusive, key)]."""
    out, s = [], 0
    for h in range(1, len(keys) + 1):
        if h == len(keys) or keys[h] != keys[s]:
            out.append((s, h, keys[s]))
            s = h
    return out


def parse_booking(b: dict) -> tuple:
    """(start_h, end_h) as integers; an end of 23:59 means past midnight, taken as 01:00 next day (= 25), as the baseline assumes."""
    sh = int(b["start"][:2])
    eh, em = int(b["end"][:2]), int(b["end"][3:5])
    e = 25 if b["end"] == "23:59" else eh + (1 if em > 0 else 0)
    if e <= sh:
        e += 24
    return sh, e


# ---- forecast for the day with the user's inputs (the browser does the same with plan.ts) ----------------------------------
def banquet_delta(h: int, s: int, e: int, r: dict) -> float:
    """Response per 100 guests at hour h of an event [s, e): end-relative wins near the end, then start-relative, then 'during'."""
    de, ds = h - e, h - s
    if -3 <= de <= 2:
        return r["end"][de + 3]
    if -3 <= ds <= 2:
        return r["start"][ds + 3]
    return r["during"] if s < h < e else 0.0


MAX_DT = 15.0     # °C: the per-°C responses are local slopes; a forecast further than this from the template is clamped


def compose_day(day: dict, rooms=None, covers=None, tmax=None, bookings=(), guests=None, temps=None) -> dict:
    """Base forecast + finite-difference responses. Temperature: an hourly forecast (temps, 24 values) or a shift to a daily max (tmax).
    kVA moves with kW at the site PF."""
    b, r, pf, dfl = day["base"], day["resp"], day["pf"], day["defaults"]
    dr = (rooms if rooms is not None else dfl["rooms"]) - dfl["rooms"]
    dg = (guests if guests is not None else dfl.get("guests", 0)) - dfl.get("guests", 0)
    dc = (covers if covers is not None else dfl["covers"]) - dfl["covers"]
    shift = (tmax if tmax is not None else day["template_tmax"]) - day["template_tmax"]
    kw, tr, kva, temp = [], [], [], []
    for h in range(24):
        dt = (temps[h] - b["temp"][h]) if temps is not None else shift
        dt = max(-MAX_DT, min(MAX_DT, dt))
        k = b["kw"][h] + r["kw_per_room"][h] * dr + r["kw_per_guest"][h] * dg + r["kw_per_cover"][h] * dc + r["kw_per_c"][h] * dt
        t = b["tr"][h] + r["tr_per_room"][h] * dr + r["tr_per_guest"][h] * dg + r["tr_per_c"][h] * dt
        for bk in bookings:
            s, e = parse_booking(bk)
            q = day["banquet"][bk["hall"]]
            k += bk["guests"] / 100 * banquet_delta(h, s, e, q["kw"])
            t += bk["guests"] / 100 * banquet_delta(h, s, e, q["tr"])
        kw.append(k)
        tr.append(max(t, 0.0))
        kva.append(b["kva"][h] + (k - b["kw"][h]) / pf)
        temp.append(b["temp"][h] + dt)
    return dict(kw=kw, tr=tr, kva=kva, temp=temp)


# ---- the plan ------------------------------------------------------------------------------------------------------------
def plan_day(hourly_tr, hourly_kva, temp_c, bookings, pf, ref=None, tariff=None) -> list:
    """Timed actions for one day. ref: matched-day behaviour from last year (tools/export_plan_inputs.py); tariff: ₹ rates."""
    if ref is None or tariff is None:
        raise ValueError("plan_day needs ref (last year's matched-day behaviour) and tariff")
    rate = (tariff["energy"] + tariff["fsa"] + tariff["duty"]) / pf          # ₹ per kWh at the margin
    acts = []
    st = [stage(x) for x in hourly_tr]
    for s, e, key in windows(st):
        trs = hourly_tr[s:e]
        sav = 0.0
        for h in range(s, e):
            p, ly = kwtr_plan(hourly_tr[h], ref["curve"]), ref["kwtr_ly"][h]
            if p is not None and ly is not None:
                sav += hourly_tr[h] * max(0.0, ly - p) * rate
        lo, hi = min(trs), max(trs)
        cap = " Forecast load is above what CH-1 + CH-3 can carry (430 TR): expect warm spaces; plan comfort messaging." if hi * TR_MARGIN > PAIR_MAX else ""
        setting = {"CH-3": "CH-3 alone (150 TR scroll chiller)", "CH-1": "CH-1 alone (300 TR screw chiller)", "CH-1+CH-3": "CH-1 + CH-3 together"}[key]
        why = {"CH-3": f"Cooling load {lo:.0f}–{hi:.0f} TR stays under 130 TR with a 10 % margin, so the small chiller carries it alone at its best efficiency.",
               "CH-1": f"Cooling load {lo:.0f}–{hi:.0f} TR is too much for CH-3 (130 TR with margin) but within CH-1 alone (280 TR); one chiller at good part load beats two lightly loaded.",
               "CH-1+CH-3": f"Cooling load {lo:.0f}–{hi:.0f} TR needs more than one chiller (280 TR with margin)."}[key] + cap
        acts.append(dict(kind="plan", group="chillers", start=hh(s), end=hh(e), equipment="Chillers (CH-1, CH-3)", setting=setting, reason=why,
                         saving_inr=sav, guardrail=GUARD["chillers"], min_tr=lo, max_tr=hi))

    sp = [CHW_RESET if (temp_c[h] < RESET_BELOW_C and stage(hourly_tr[h]) != "CH-1+CH-3") else CHW_STD for h in range(24)]
    for s, e, v in windows(sp):
        sav = 0.0
        pcts = [chw_pct(hourly_tr[h], ref) for h in range(s, e)]
        if v > CHW_STD:
            for h, pc in zip(range(s, e), pcts):
                p = kwtr_plan(hourly_tr[h], ref["curve"])
                sav += hourly_tr[h] * (p or 0.0) * pc * (v - CHW_STD) * rate
        lo_p, hi_p = min(pcts) * 100, max(pcts) * 100
        span = f"{lo_p:.1f} %" if hi_p - lo_p < 0.05 else f"{lo_p:.1f}–{hi_p:.1f} %"
        src = "measured on these chillers" if ref.get("chw_pct_per_c") else "engineering guide"
        why = (f"Outdoor {min(temp_c[s:e]):.0f}–{max(temp_c[s:e]):.0f} °C and one chiller running: warmer chilled water still holds comfort and saves about {span} of chiller power per °C at this load ({src})."
               if v > CHW_STD else "Standard setting: outdoor 24 °C or warmer, or two chillers needed.")
        acts.append(dict(kind="plan", group="chw", start=hh(s), end=hh(e), equipment="Chilled-water supply setpoint", setting=f"{v:.1f} °C",
                         reason=why, saving_inr=sav, guardrail=GUARD["chw"], setpoint_c=v))

    for bk in bookings:
        s, e = parse_booking(bk)
        on, off = max(s - 1, s - 2, 0), e + 1
        style = "social" if bk["hall"] == "A+B" else "corporate"
        ly = ref["ahu_overrun_kwh"][style]
        acts.append(dict(kind="plan", group="ahu", start=hh(on), end=hh(off), equipment=f"Banquet AHUs, Hall {bk['hall']} ({AHU[bk['hall']]})",
                         setting=f"On at {hh(on)}, off at {hh(off)}",
                         reason=(f"Event in Hall {bk['hall']} {bk['start']}–{bk['end']} ({bk['guests']} guests): pre-cool 1 h before, stop 1 h after. "
                                 f"Last year the AHUs ran on about {ly:.0f} kWh after similar events ended (left in hand mode)."),
                         saving_inr=ly * rate, guardrail=GUARD["ahu"], on_h=on, start_h=s))

    blocked = [in_win(h, PEAK) or hourly_kva[h] + LAUNDRY_KW / pf > DEMAND_WATCH_KVA for h in range(24)]
    ok = [(s, e) for s, e, v in windows(blocked) if not v]
    by_demand = [h for h in range(24) if blocked[h] and not in_win(h, PEAK)]
    if ok:
        txt = ", ".join(f"{hh(s)}–{hh(e)}" for s, e in ok)
        acts.append(dict(kind="plan", group="laundry", start=hh(ok[0][0]), end=hh(ok[-1][1]), equipment="Laundry (washer-extractors, dryers)",
                         setting=f"Run batches only {txt}",
                         reason=(f"Keep laundry out of the 18:00–22:00 peak tariff" + (f" and out of {len(by_demand)} hour(s) where site demand plus laundry would pass 920 kVA" if by_demand else "") +
                                 f". Last year on similar days about {ref['laundry_peak_kwh']:.0f} kWh of laundry ran in the peak window."),
                         saving_inr=ref["laundry_peak_kwh"] / pf * tariff["peak"], guardrail=GUARD["laundry"]))

    acts.append(dict(kind="plan", group="water", start=hh(OFFPEAK[0]), end=hh(OFFPEAK[1] + 24), equipment="Heat-pump water heaters (HP-DHW)",
                     setting="Heat storage 23:00–05:00 (off-peak); finish the ≥ 60 °C cycle by 05:00",
                     reason=(f"Overnight heating is cheaper (off-peak rebate) and keeps the evening peak clear. Last year on similar days about "
                             f"{ref['water_peak_kwh']:.0f} kWh of boost heating ran in the 18:00–22:00 peak."),
                     saving_inr=ref["water_peak_kwh"] / pf * (tariff["peak"] - tariff["offpeak"]), guardrail=GUARD["water"]))

    hot = [hourly_kva[h] > DEMAND_WATCH_KVA for h in range(24)]
    for s, e, v in windows(hot):
        if not v:
            continue
        pk = max(hourly_kva[s:e])
        relief = min(max(0.0, pk - CD_KVA), max(ref["ev_kw"][s:e]) / pf)
        acts.append(dict(kind="plan", group="ev", start=hh(s), end=hh(e), equipment="EV chargers (EVC-1..4)", setting="Limit charging while site demand is above 920 kVA",
                         reason=f"Site demand forecast up to {pk:.0f} kVA (contract 1,000 kVA)." + (" Holding EV charging back keeps the month's maximum demand down." if relief > 0 else ""),
                         saving_inr=relief * tariff["penalty"], guardrail=GUARD["ev"]))
    validate(acts)
    return acts


def validate(acts: list) -> None:
    """Guardrails (CLAUDE.md, brief §9). Raises on any breach: excluded equipment, setpoint below 6.5 °C, two chillers below 130 TR, AHU on > 2 h early."""
    for a in acts:
        text = (a["equipment"] + " " + a["setting"]).lower()
        bad = [w for w in EXCLUDED if w in text]
        if bad:
            raise ValueError(f"plan touches excluded equipment ({bad[0]}): {a['equipment']}")
        for m in re.finditer(r"(\d+(?:\.\d+)?)\s*°C", a["setting"]):
            if a["group"] == "chw" and float(m.group(1)) < CHW_FLOOR:
                raise ValueError(f"setpoint below {CHW_FLOOR} °C: {a['setting']}")
        if a["group"] == "chw" and a["setpoint_c"] < CHW_FLOOR:
            raise ValueError("setpoint below 6.5 °C")
        if a["group"] == "chillers" and "together" in a["setting"] and a["min_tr"] < CH3_MAX:
            raise ValueError(f"two chillers planned at {a['min_tr']:.0f} TR (< 130)")
        if a["group"] == "ahu" and a["start_h"] - a["on_h"] > 2:
            raise ValueError("banquet AHU on more than 2 h before the event")
        if not math.isfinite(a["saving_inr"]):
            raise ValueError("saving is not a number")


def risk_for(kva: list, cal: dict) -> dict:
    """src/peak_risk.assess applied to a plan's own hourly kVA with the exported calibration (same as web/src/plan.ts riskFor)."""
    raw = max(kva)
    hour = kva.index(raw)
    peak = raw * cal["bias"]
    upper, stack = peak * cal["upper_factor"], peak + cal["stack_increment"]
    r = cal["ratios"]
    p = sum(1 for x in r if x >= cal["cd"] / peak) / len(r) if len(r) >= 10 else None
    level = ("BREACH RISK" if upper >= cal["cd"] or stack >= cal["cd"] else "WARNING" if upper >= cal["warn"]
             else "STACKING WATCH" if stack >= cal["watch_frac"] * cal["cd"] else "OK")
    return dict(raw_peak_kva=raw, hour=hour, peak_kva=peak, upper_kva=upper, stack_kva=stack, p_exceed=p, level=level)
