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
# Jaipur / Goa: the guardrail line for two chillers = the smaller unit's capacity in each hotel's register (ACH-1/2: 2 × 200 TR, 2 × 150 TR).
# Kept here too so a saved plan can be re-checked without the model files; tests/test_site_plan.py checks it against the register.
TWO_MIN_TR = {"GGN": CH3_MAX, "JAI": 200.0, "GOA": 150.0}
FILTRATION_MIN_H = 8                                  # CONTEXT.md §9: pool filtration >= 8 h a day
ONE_MARGIN = 0.90                                     # Jaipur / Goa: one chiller up to its capacity minus 10 %
DEMAND_STEP_FRAC = 0.92                               # Jaipur / Goa: a demand step only if the forecast comes within 8 % of the contract
CHW_MIN_H = 3                                         # a setpoint is held at least 3 h (a shorter block goes to the safer 7.0 °C)
STAGE_MIN_H = 2                                       # chillers are not switched for less than 2 h unless the load needs the bigger stage
LIGHT_LEAD_MIN = 30                                   # event lighting on 30 min before the booking, off 30 min after
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


def hold_setpoint(sp: list) -> list:
    """No setpoint block shorter than CHW_MIN_H. A short 8.0 °C block goes back to 7.0 °C; a short 7.0 °C block grows one hour at a time
    into its longer 8.0 °C neighbour. Never the other way: 7.0 °C is the safe setting, so a doubtful hour always ends up at 7.0 °C."""
    sp = list(sp)
    while True:
        w = windows(sp)
        if len(w) == 1:
            return sp
        hi = [(s, e) for s, e, v in w if v > CHW_STD and e - s < CHW_MIN_H]
        if hi:
            s, e = hi[0]
            sp[s:e] = [CHW_STD] * (e - s)
            continue
        lo = [i for i, (s, e, v) in enumerate(w) if e - s < CHW_MIN_H]
        if not lo:
            return sp
        i = lo[0]
        nb = [j for j in (i + 1, i - 1) if 0 <= j < len(w)]
        j = max(nb, key=lambda j: w[j][1] - w[j][0])                   # take the hour from the longer 8.0 °C neighbour (ties: the later one)
        sp[w[j][0] if j > i else w[j][1] - 1] = CHW_STD


def held_note(want: list, s: int, e: int) -> str:
    """Reason text for a 7.0 °C block that includes hours where 8.0 °C was possible but too short to hold (CHW_MIN_H)."""
    n = sum(1 for h in range(s, e) if want[h] > CHW_STD)
    return (f" Includes {n} h where 8.0 °C was possible, kept at 7.0 °C (the safer setting) so the setpoint does not change for less than "
            f"{CHW_MIN_H} h." if n else "")


def hold_stages(keys: list, tr: list, rank: dict, two_ok) -> list:
    """No chiller switch for less than STAGE_MIN_H. A short block of a smaller stage joins the next bigger neighbouring stage (a bigger stage
    always carries the load), unless that would run two chillers below their guardrail (two_ok). A short block of a bigger stage stays:
    the load needs it. Each block's reason says why it is short (stage_note)."""
    keys = list(keys)
    changed = True
    while changed:
        changed = False
        w = windows(keys)
        for i, (s, e, k) in enumerate(w):
            if e - s >= STAGE_MIN_H or len(w) == 1:
                continue
            up = [w[j] for j in (i - 1, i + 1) if 0 <= j < len(w) and rank[w[j][2]] > rank[k] and all(two_ok(w[j][2], tr[h]) for h in range(s, e))]
            if up:
                t = min(up, key=lambda n: rank[n[2]])[2]
                keys[s:e] = [t] * (e - s)
                changed = True
                break
    return keys


def stage_note(w: list, i: int, raw: list, rank: dict, need: str, guard: str) -> str:
    """Reason text for a staging block that was lengthened, or that is shorter than STAGE_MIN_H and kept."""
    s, e, k = w[i]
    out = ""
    lower = sum(1 for h in range(s, e) if rank[raw[h]] < rank[k])
    if lower:
        out += f" Includes {lower} h a smaller stage could carry, kept on this stage so the chillers do not switch for less than {STAGE_MIN_H} h."
    if e - s < STAGE_MIN_H and len(w) > 1:
        nb = [w[j][2] for j in (i - 1, i + 1) if 0 <= j < len(w)]
        if any(rank[n] < rank[k] for n in nb):
            out += f" Only {e - s} h, but the load needs it: {need}."
        else:
            out += f" Only {e - s} h: joining the neighbouring stage would {guard}."
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
def plan_day(hourly_tr, hourly_kva, temp_c, bookings, pf, ref=None, tariff=None, site: str = "GGN", cfg: dict | None = None) -> list:
    """Timed actions for one day. ref: matched-day behaviour from last year (tools/export_plan_inputs.py; Jaipur / Goa:
    tools/train_api_models.py); tariff: ₹ rates; cfg: the hotel's own equipment, venues and tariff windows (Jaipur / Goa only)."""
    if ref is None or tariff is None:
        raise ValueError("plan_day needs ref (last year's matched-day behaviour) and tariff")
    if site != "GGN":
        if cfg is None:
            raise ValueError(f"plan_day for {site} needs the hotel's config (models/meta.json sites.{site}.config)")
        return plan_site(site, cfg, hourly_tr, hourly_kva, temp_c, bookings, pf, ref, tariff)
    rate = (tariff["energy"] + tariff["fsa"] + tariff["duty"]) / pf          # ₹ per kWh at the margin
    acts = []
    raw = [stage(x) for x in hourly_tr]
    rank = {"CH-3": 0, "CH-1": 1, "CH-1+CH-3": 2}
    st = hold_stages(raw, hourly_tr, rank, lambda k, tr: k != "CH-1+CH-3" or tr >= CH3_MAX)
    sw = windows(st)
    for i, (s, e, key) in enumerate(sw):
        trs = hourly_tr[s:e]
        sav = 0.0
        for h in range(s, e):
            p = kwtr_plan(hourly_tr[h], ref["curve"]) if key != "CH-1+CH-3" else None
            ly = ref["kwtr_ly"][h]
            if p is not None and ly is not None:
                sav += hourly_tr[h] * max(0.0, ly - p) * rate
        lo, hi = min(trs), max(trs)
        cap = " Forecast load is above what CH-1 + CH-3 can carry (430 TR): expect warm spaces; plan comfort messaging." if hi * TR_MARGIN > PAIR_MAX else ""
        setting = {"CH-3": "CH-3 alone (150 TR scroll chiller)", "CH-1": "CH-1 alone (300 TR screw chiller)", "CH-1+CH-3": "CH-1 + CH-3 together"}[key]
        why = {"CH-3": f"Cooling load {lo:.0f}–{hi:.0f} TR stays under 130 TR with a 10 % margin, so the small chiller carries it alone at its best efficiency.",
               "CH-1": f"Cooling load {lo:.0f}–{hi:.0f} TR is too much for CH-3 (130 TR with margin) but within CH-1 alone (280 TR); one chiller at good part load beats two lightly loaded.",
               "CH-1+CH-3": f"Cooling load {lo:.0f}–{hi:.0f} TR needs more than one chiller (280 TR with margin)."}[key] + cap
        why += stage_note(sw, i, raw, rank, "a smaller stage cannot carry this load with the 10 % margin",
                          "run two chillers below 130 TR, which is never allowed")
        acts.append(dict(kind="plan", group="chillers", start=hh(s), end=hh(e), equipment="Chillers (CH-1, CH-3)", setting=setting, reason=why,
                         saving_inr=sav, guardrail=GUARD["chillers"], min_tr=lo, max_tr=hi))

    want = [CHW_RESET if (temp_c[h] < RESET_BELOW_C and st[h] != "CH-1+CH-3") else CHW_STD for h in range(24)]
    sp = hold_setpoint(want)
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
               if v > CHW_STD else "Standard setting: outdoor 24 °C or warmer, or two chillers needed.") + held_note(want, s, e)
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


def validate(acts: list, cfg: dict | None = None) -> None:
    """Guardrails (CLAUDE.md, brief §9). Raises on any breach: excluded equipment, setpoint below 6.5 °C, two chillers below 130 TR
    (Jaipur / Goa: below the smaller chiller's capacity), AHU on > 2 h early, pool filtration under the daily minimum."""
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
        two_min = TWO_MIN_TR.get(a.get("site", "GGN"), CH3_MAX)
        if cfg is not None and a.get("site", "GGN") != "GGN":
            two_min = min(cfg["chillers"]["units_tr"])
        if a["group"] == "chillers" and "together" in a["setting"] and a["min_tr"] < two_min:
            raise ValueError(f"two chillers planned at {a['min_tr']:.0f} TR (< {two_min:.0f})")
        if a["group"] == "pool" and a.get("run_hours", 99) < FILTRATION_MIN_H:
            raise ValueError(f"pool filtration planned for {a.get('run_hours')} h (< {FILTRATION_MIN_H} h a day)")
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


# ---- Jaipur and Goa: only levers their sub-meters can size and later check ------------------------------------------------------
# sub_jai_goa_hourly has total chillers_kw and chiller_load_tr (no per-chiller split, no CHW setpoint), lighting_kw, pumps_pool_kw and
# laundry_kw. So: chiller staging (checked by total kW per TR), CHW setpoint (shown, never counted: no setpoint meter), event lighting,
# pool filtration (where the register has pool pumps), laundry timing and a demand watch. Every hotel fact comes from cfg (the hotel's
# own register, events calendar and tariff rows; tools/train_api_models.py).
def hm(minutes: int) -> str:
    """Minutes from the day's midnight -> 'HH:MM', with ' (next day)' past midnight."""
    return f"{(minutes // 60) % 24:02d}:{minutes % 60:02d}" + (" (next day)" if minutes >= 24 * 60 else "")


def booking_minutes(b: dict) -> tuple:
    """(start, end) in minutes from midnight; 23:59 = past midnight, taken as 01:00 next day (as the baseline); end <= start = next day."""
    s = int(b["start"][:2]) * 60 + int(b["start"][3:5])
    e = 25 * 60 if b["end"] == "23:59" else int(b["end"][:2]) * 60 + int(b["end"][3:5])
    if e <= s:
        e += 24 * 60
    return s, e


def curve_at(tr: float, curve: dict) -> float:
    for hi, v in zip(curve["edges"][1:], curve["values"]):
        if tr <= hi:
            return v
    return curve["values"][-1]


def site_stage(tr: float, units: list) -> str:
    """'one': within one chiller's capacity minus 10 %; 'one-full': above that but below the smaller unit's capacity, where two chillers
    are not allowed (never two below the smaller unit's capacity), so one runs near full with the second on standby; 'two' otherwise."""
    if tr <= ONE_MARGIN * max(units):
        return "one"
    return "one-full" if tr < min(units) else "two"


def site_guard(cfg: dict) -> dict:
    u, ch = cfg["chillers"]["units_tr"], cfg["chillers"]
    pool = cfg.get("pool")
    return {
        "chillers": (f"Recommendation only: the duty engineer stages {ch['id']} ({ch['rating']}). One chiller up to {ONE_MARGIN * max(u):.0f} TR "
                     f"(capacity minus 10 %); never two chillers below {min(u):.0f} TR."),
        "chw": f"Recommendation only. Never below {CHW_FLOOR} °C leaving water. Go back to 7.0 °C at once if a guest area runs warm (guest rooms 22–25 °C).",
        "lighting": "Recommendation only: the banquet team switches the event lighting (timer). Safety, path and emergency lighting stay on.",
        "pool": (f"Recommendation only. Filtration runs at least {pool['min_hours']} h every day for water quality; never less." if pool else ""),
        "laundry": "Recommendation only: the laundry supervisor schedules batches. Flexible load; no effect on guests.",
        "demand": "Recommendation only: a person decides what to hold back. Never kitchen exhaust, guest-room thermostats, lifts or fire / life-safety.",
    }


def plan_site(site, cfg, hourly_tr, hourly_kva, temp_c, bookings, pf, ref, tariff) -> list:
    rate = (tariff["energy"] + tariff["fsa"] + tariff["duty"]) / pf          # ₹ per kWh at the margin
    G, units, ch = site_guard(cfg), cfg["chillers"]["units_tr"], cfg["chillers"]
    curve, peak, off, cd = ref["curve"], tuple(cfg["peak"]), tuple(cfg["offpeak"]), cfg["cd_kva"]
    acts = []
    base = dict(kind="plan", site=site)

    # chillers: staging bands from the register; ₹ = last year's matched-day hours at poor kW/TR (two chillers on a light load)
    st = [site_stage(x, units) for x in hourly_tr]
    raw = ["two" if x == "two" else "one" for x in st]
    rank = {"one": 0, "two": 1}
    keys = hold_stages(raw, hourly_tr, rank, lambda k, tr: k != "two" or tr >= min(units))
    sw = windows(keys)
    for i, (s, e, key) in enumerate(sw):
        trs = hourly_tr[s:e]
        lo, hi = min(trs), max(trs)
        full = [h for h in range(s, e) if st[h] == "one-full"]
        sav = sum(ref["poor_kwh_ly"][h] for h in range(s, e)) * rate if key == "one" else 0.0
        one = f"{ch['id'].replace('/', ' or ACH-')}, {max(units):.0f} TR"
        if key == "two":
            setting, why = "Both chillers together (ACH-1 + ACH-2)", f"Cooling load {lo:.0f}–{hi:.0f} TR needs both chillers."
        else:
            setting = f"One chiller only ({one})" + ("; near full load at times, second on standby" if full else "")
            why = (f"Cooling load {lo:.0f}–{hi:.0f} TR stays within one chiller ({ONE_MARGIN * max(units):.0f} TR with a 10 % margin"
                   + (f"; {len(full)} h between that and {min(units):.0f} TR, where two chillers are not run: keep one near full load and the second ready" if full else "")
                   + "). Last year on similar days " + (f"the plant ran at poor kW per TR (two chillers sharing a light load) for about {sum(ref['poor_kwh_ly'][h] for h in range(s, e)):.0f} kWh in these hours."
                                                       if sav > 0 else "the plant held its normal kW per TR in these hours."))
        why += stage_note(sw, i, raw, rank, f"one chiller cannot carry this load with its 10 % margin ({ONE_MARGIN * max(units):.0f} TR)",
                          f"run two chillers below {min(units):.0f} TR, which is never allowed")
        if hi > sum(units):
            why += f" Forecast load is above what both chillers can carry ({sum(units):.0f} TR): expect warm spaces; plan comfort messaging."
        acts.append(dict(base, group="chillers", start=hh(s), end=hh(e), equipment=f"Chillers ({ch['id']}, {ch['description'].lower()})", setting=setting,
                         reason=why + " Can't verify the exact chiller from meters; checked by total kW per TR.", saving_inr=sav,
                         guardrail=G["chillers"], min_tr=lo, max_tr=hi, verifiable="total kW per TR"))

    # CHW setpoint: 7.0 °C, 8.0 °C when outdoor < 24 °C and one chiller carries the load; never < 6.5 °C. No setpoint meter: shown, not counted
    want = [CHW_RESET if (temp_c[h] < RESET_BELOW_C and st[h] == "one" and keys[h] == "one") else CHW_STD for h in range(24)]
    sp = hold_setpoint(want)
    for s, e, v in windows(sp):
        est = sum(hourly_tr[h] * curve_at(hourly_tr[h], curve) * SETPOINT_PCT_PER_C * (v - CHW_STD) for h in range(s, e)) * rate
        why = (f"Outdoor {min(temp_c[s:e]):.0f}–{max(temp_c[s:e]):.0f} °C and one chiller carrying the load: warmer chilled water still holds comfort."
               if v > CHW_STD else "Standard setting: outdoor 24 °C or warmer, or the load needs more than one chiller at its margin.")
        why += (f" The guide's ~3.5 % per °C would put this at about ₹{est:,.0f}, but there is no setpoint meter here, so it is not verifiable and is "
                "not counted in any ₹ total." if v > CHW_STD else " No setpoint meter here: not verifiable.") + held_note(want, s, e)
        acts.append(dict(base, group="chw", start=hh(s), end=hh(e), equipment="Chilled-water supply setpoint", setting=f"{v:.1f} °C", reason=why,
                         saving_inr=0.0, estimate_inr=est, counted=False, guardrail=G["chw"], setpoint_c=v, verifiable="not verifiable (no setpoint meter)"))

    # event lighting: on 30 min before each booking, off 30 min after; ₹ = last year's lighting left on after events at that venue
    for bk in bookings:
        v = cfg["venues"][bk["hall"]]
        s, e = booking_minutes(bk)
        on, offm = max(0, s - LIGHT_LEAD_MIN), e + LIGHT_LEAD_MIN
        lt = v.get("lighting")
        equip = f"Event lighting, {bk['hall']}" + (f" ({lt['id']}, {lt['kw']:.0f} kW)" if lt else f" (about {v['event_kw']:.0f} kW on the lighting sub-meter)")
        ly = v["left_on_kwh"]
        acts.append(dict(base, group="lighting", start=hm(on), end=hm(offm), equipment=equip, setting=f"On at {hm(on)}, off at {hm(offm)}",
                         reason=(f"Event at {bk['hall']} {bk['start']}–{bk['end']} ({bk['guests']} guests): lights on 30 min before, off 30 min after. "
                                 + (f"Last year the lighting stayed on after {v['events_left_on']} of {v['events']} events here, about {ly:.0f} kWh per event on average."
                                    if ly > 0 else f"Last year's {v['events']} events here switched off on time; this keeps it that way.")),
                         saving_inr=ly * rate, guardrail=G["lighting"], venue=bk["hall"], on_min=on, off_min=offm))

    # pool filtration (only where the register lists pool pumps): last year's usual schedule, never under the daily minimum
    pool = cfg.get("pool")
    if pool:
        hrs = pool["schedule"]["hours"]
        runs = [(a, b) for a, b, v in windows([h in hrs for h in range(24)]) if v]
        n = len(hrs)
        if n < pool["min_hours"]:                                  # never below the daily filtration hours
            hrs = list(range(hrs[0] if hrs else 7, (hrs[0] if hrs else 7) + pool["min_hours"]))
            runs, n = [(hrs[0], hrs[-1] + 1)], len(hrs)
        txt = ", ".join(f"{hh(a)}–{hh(b)}" for a, b in runs)
        acts.append(dict(base, group="pool", start=hh(runs[0][0]), end=hh(runs[-1][1]), equipment=f"Pool filtration pumps ({pool['id']}, {pool['rating']})",
                         setting=f"Run filtration {txt} ({n} h); off the rest of the day",
                         reason=(f"The usual schedule on last year's normal days: {n} h at about {pool['schedule']['kw']:.0f} kW (at least {pool['min_hours']} h for water quality). "
                                 + (f"On similar days last year the pumps ran about {ref.get('pool_outside_kwh', 0):.0f} kWh outside the schedule."
                                    if ref.get("pool_outside_kwh", 0) > 0 else "Last year's similar days kept to it.")),
                         saving_inr=ref.get("pool_outside_kwh", 0.0) * rate, guardrail=G["pool"], run_hours=n))

    # laundry: out of the hotel's own peak window and out of hours near the contract; Goa: best in its off-peak window
    watch = DEMAND_STEP_FRAC * cd
    lkw = cfg["laundry"]["kw"]
    blocked = [in_win(h, peak) or hourly_kva[h] + lkw / pf > watch for h in range(24)]
    ok = [(s, e) for s, e, v in windows(blocked) if not v]
    by_demand = [h for h in range(24) if blocked[h] and not in_win(h, peak)]
    if ok:
        txt = ", ".join(f"{hh(s)}–{hh(e)}" for s, e in ok)
        offp = f"; best {hh(off[0])}–{hh(off[1])} (off-peak rebate)" if site == "GOA" else ""
        acts.append(dict(base, group="laundry", start=hh(ok[0][0]), end=hh(ok[-1][1]), equipment=f"Laundry ({cfg['laundry']['kw']:.0f} kW connected)",
                         setting=f"Run batches only {txt}{offp}",
                         reason=(f"Keep laundry out of the {hh(peak[0])}–{hh(peak[1])} peak tariff" + (f" and out of {len(by_demand)} hour(s) near the contract demand" if by_demand else "")
                                 + (f". Off-peak {hh(off[0])}–{hh(off[1])} also earns the rebate where the team can run night batches" if site == "GOA" else "")
                                 + f". Last year on similar days about {ref['laundry_peak_kwh']:.0f} kWh of laundry ran in the peak window."),
                         saving_inr=ref["laundry_peak_kwh"] / pf * tariff["peak"], guardrail=G["laundry"]))

    # demand: watch only; a step only if the forecast comes within 8 % of the contract
    near = [hourly_kva[h] >= watch for h in range(24)]
    for s, e, v in windows(near):
        if not v:
            continue
        pk = max(hourly_kva[s:e])
        acts.append(dict(base, group="demand", start=hh(s), end=hh(e), equipment="Flexible loads (laundry, event set-up)",
                         setting=f"Hold flexible loads while demand is above {watch:,.0f} kVA",
                         reason=f"Site demand forecast up to {pk:,.0f} kVA, within 8 % of the {cd:,.0f} kVA contract. Watch only: no ₹ is claimed.",
                         saving_inr=0.0, guardrail=G["demand"]))
    validate(acts, cfg)
    return acts
