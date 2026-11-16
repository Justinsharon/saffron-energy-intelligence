"""Plan vs actual: was each step of a day's operating plan carried out? Compared with the live-year sub-meters, hour by hour, ONLY up to
the hour given (`as_of`, never later than now in India). Recommend only: this checks, it controls nothing.

HONESTY: the live meters are simulated (tools/make_live_year.py) and do not react to approvals, so adherence on the live year is
illustrative; with real meters the same check shows what the team actually did.

Per step: Followed / Partly / Not followed / Not yet due / Can't tell (no meter), the hours that differed, the extra kWh and ₹ (same tariff
prices as the plan), and the verified ₹ (followed hours only: actual vs how matched days ran last year - the plan's own yardstick).
A step Not followed for 2+ hours becomes a PLAN_DEVIATION alert (₹ per occurrence; Daily digest unless ₹ > 2,000).

Only APPROVED steps of a SAVED plan count: they alone get Followed / Not followed, verified or missed ₹, deviation alerts and `covered` hours.
A saved step not approved is "Not approved"; a skipped one stays "Skipped"; with no saved plan every step is "Suggested, not approved" and
carries only `would_have_saved_inr` (shown in grey, never in a total, never an alert).

Plan savings and alert savings are separate streams and never double-counted: `covered` lists the hours each followed step covers, and
the alert side drops its ₹ for those hours and that equipment (web/src/savingsSplit.ts).
"""
import math
import re

import pandas as pd

import operating_plan as OP

RUN_KW = 5.0             # a chiller drawing more than this is running
AHU_IDLE_KW = 10.0       # banquet AHUs above this are running (detector KW_FLOOR["AHU"])
FLEX_KW = 5.0            # laundry / water-heating boost above this is a run
EV_KW = 1.0              # EV-charger draw above this (demand_ev_rules: night threshold)
DIGEST_BELOW_INR = 2000.0
HONESTY = ("The live meters are simulated and do not react to approvals, so 'followed' here is illustrative; with real meters it shows "
           "what the team actually did.")
EQUIP_COL = {"chillers": "chillers_kw", "chw": "chw_setpoint_c", "ahu": "ahu_banquet_kw", "laundry": "laundry_kw", "water": "water_heating_kw",
             "ev": "ev_chargers_kw"}
PLANNED = {"CH-3": "Chiller 3 only", "CH-1": "Chiller 1 only", "CH-1+CH-3": "Chillers 1 and 3"}


def hour_of(t: str) -> int:
    return int(t[:2]) + (24 if "next day" in t else 0)


def stage_of(setting: str) -> str:
    return "CH-1+CH-3" if "together" in setting else "CH-3" if setting.startswith("CH-3") else "CH-1"


def allowed_hours(setting: str) -> set:
    """Laundry: hours inside 'Run batches only 00:00–18:00, 22:00–00:00 (next day)'."""
    out = set()
    for a, b, nd in re.findall(r"(\d\d):00(?: \(next day\))?–(\d\d):00( \(next day\))?", setting):
        s, e = int(a), int(b) + (24 if nd else 0)
        out.update(range(s, e if e > s else e + 24))
    return out


def actual_stage(ch1: float, ch3: float) -> str:
    on1, on3 = ch1 > RUN_KW, ch3 > RUN_KW
    return "CH-1+CH-3" if on1 and on3 else "CH-1" if on1 else "CH-3" if on3 else "none"


ACTUAL = {"CH-1+CH-3": "both ran", "CH-1": "Chiller 1 ran", "CH-3": "Chiller 3 ran", "none": "no chiller ran"}


def _hm(h: int) -> str:
    return f"{h % 24:02d}:00" + (" (next day)" if h >= 24 else "")


def check_day(date: str, actions: list, meters: pd.DataFrame, as_of: str, ref: dict, tariff: dict, pf: float, suggested: bool = False,
              site: str = "GGN", cfg: dict | None = None) -> dict:
    """meters: hourly rows covering the date and the next day, columns timestamp, chiller_ch1_kw, chiller_ch3_kw, chillers_kw,
    chiller_load_tr, chw_setpoint_c, ahu_banquet_kw, laundry_kw, water_heating_kw, ev_chargers_kw, kva, total_kwh.
    Jaipur / Goa (site, cfg): timestamp, chillers_kw, chiller_load_tr, lighting_kw, pumps_pool_kw, laundry_kw, kva, total_kwh."""
    if site != "GGN":
        return check_site(date, actions, meters, as_of, ref, tariff, pf, suggested, site, cfg)
    day = pd.Timestamp(date)
    cut = pd.Timestamp(as_of[:13] + ":00")                              # the current hour is the last one with a reading
    m = meters.set_index("timestamp")
    rate = (tariff["energy"] + tariff["fsa"] + tariff["duty"]) / pf

    def row(h):
        t = day + pd.Timedelta(hours=h)
        return m.loc[t] if (t <= cut and t in m.index) else None

    steps, alerts, covered = [], [], {}
    for a in actions:
        g, s, e = a["group"], hour_of(a["start"]), hour_of(a["end"])
        if e <= s:
            e += 24
        planned_inr = float(a.get("saving_inr", 0.0))
        sid = a.get("id") or f"{g}|{a['start']}|{a.get('equipment', '')}"
        if suggested or a.get("decision") != "approve":
            # only approved steps of a saved plan are checked or counted
            st = "Suggested, not approved" if suggested else "Skipped" if a.get("decision") == "skip" else "Not approved"
            steps.append(dict(id=sid, group=g, start=a["start"], end=a["end"], setting=a["setting"], equipment=a.get("equipment", ""), status=st,
                              reason=a.get("decision_reason") or "", hours_checked=0, hours_differed=[], extra_kwh=0.0, extra_inr=0.0, planned_inr=0.0,
                              verified_inr=0.0, would_have_saved_inr=round(planned_inr, 1) if st != "Skipped" else 0.0,
                              what_was_checked={"Skipped": "skipped by the team with a reason, so not checked",
                                                "Not approved": "not approved, so not checked or counted"}.get(st, "suggested only: no plan was saved")))
            continue
        dev, hrs, extra_kwh, extra_inr, ver, no_meter, per_hour_extra = [], [], 0.0, 0.0, 0.0, 0, {}
        # hours this step is judged on
        if g == "laundry":
            ok_h = allowed_hours(a["setting"])
            span = range(0, 24)
        elif g == "water":
            span = range(OP.PEAK[0], OP.PEAK[1])                         # plan: no boost heating in the evening peak; heat overnight
        elif g == "ahu":
            span = range(max(0, s - 3), e + 12)                          # before the planned start and after the planned stop
        else:
            span = range(s, e)
        boost_floor = None
        if g == "water":
            day_rows = [row(h) for h in range(0, 24)]
            vals = [r["water_heating_kw"] for r in day_rows if r is not None and not pd.isna(r["water_heating_kw"])]
            boost_floor = min(vals) if vals else None
        for h in span:
            r = row(h)
            if r is None:
                continue
            col = EQUIP_COL[g]
            if pd.isna(r.get(col, float("nan"))):
                no_meter += 1
                continue
            hrs.append(h)
            bad, kwh, inr = False, 0.0, 0.0
            if g == "chillers":
                want, got = stage_of(a["setting"]), actual_stage(r.chiller_ch1_kw, r.chiller_ch3_kw)
                tr = float(r.chiller_load_tr)
                normal = OP.kwtr_plan(tr, ref["curve"])
                if got != want and got != "none" and not (want == "CH-1+CH-3"):
                    bad = True
                    kwh = max(0.0, r.chillers_kw - tr * (normal if normal is not None else r.chillers_kw / max(tr, 1)))
                    inr = kwh * rate
                elif h < 24 and ref["kwtr_ly"][h] is not None and tr > 20:
                    ver += tr * max(0.0, ref["kwtr_ly"][h] - r.chillers_kw / tr) * rate
            elif g == "chw":
                want, got = float(a.get("setpoint_c", 7.0)), float(r.chw_setpoint_c)
                pct = OP.chw_pct(float(r.chiller_load_tr), ref)
                if got < want - 0.05:
                    bad = True
                    kwh = r.chillers_kw * pct * (want - got)
                    inr = kwh * rate
                elif want > OP.CHW_STD:
                    ver += r.chillers_kw * pct * (min(got, want) - OP.CHW_STD) * rate
            elif g == "ahu":
                if not (s - 1 <= h < e) and r.ahu_banquet_kw > AHU_IDLE_KW:
                    bad, kwh = True, float(r.ahu_banquet_kw)
                    inr = kwh * rate
            elif g == "laundry":
                if h not in ok_h and r.laundry_kw > FLEX_KW:
                    bad, kwh = True, float(r.laundry_kw)
                    inr = kwh / pf * tariff["peak"] if OP.in_win(h % 24, OP.PEAK) else 0.0
            elif g == "water":
                boost = float(r.water_heating_kw) - (boost_floor or 0.0)
                if boost > FLEX_KW:
                    bad, kwh = True, boost
                    inr = boost / pf * (tariff["peak"] - tariff["offpeak"])
            elif g == "ev":
                if r.ev_chargers_kw > EV_KW:
                    bad, kwh = True, float(r.ev_chargers_kw)
                    inr = min(kwh / pf, max(0.0, float(r.kva) - OP.CD_KVA)) * tariff["penalty"]
            if bad:
                dev.append(h)
                extra_kwh += kwh
                extra_inr += inr
                per_hour_extra[h] = kwh
        n, d = len(hrs), len(dev)
        whole = len([h for h in span])
        if n == 0 and no_meter:
            status = "Can't tell (no meter)"
        elif n == 0:
            status = "Not yet due"
        elif d == 0:
            status = "Followed"
        elif d >= 2 and d >= n / 2:
            status = "Not followed"
        else:
            status = "Partly"
        if g in ("ahu", "laundry", "water", "ev"):                    # these steps save a fixed amount if kept: pro-rate to the hours seen
            ver = planned_inr * (n / max(whole, 1)) if status == "Followed" else 0.0
        elif status in ("Not followed",):
            ver = 0.0
        fol = [h for h in hrs if h not in dev]
        if status in ("Followed", "Partly") and fol:
            covered.setdefault(g, []).extend(h for h in fol if h < 24)
        step = dict(id=sid, group=g, start=a["start"], end=a["end"], setting=a["setting"], would_have_saved_inr=0.0,
                    equipment=a.get("equipment", ""), status=status, hours_checked=n, hours_differed=[_hm(h) for h in dev],
                    extra_kwh=round(extra_kwh, 1), extra_inr=round(extra_inr, 1), planned_inr=round(planned_inr, 1), verified_inr=round(ver, 1),
                    what_was_checked=_checked(g))
        steps.append(step)
        if status == "Not followed":
            alerts.append(_alert(date, a, dev, n, extra_kwh, extra_inr, meters, day, cut, per_hour_extra))
    tot = lambda k: round(sum(x[k] for x in steps), 1)
    cnt = lambda st: sum(1 for x in steps if x["status"] == st)
    approved = [x for x in steps if x["status"] not in ("Skipped", "Not approved", "Suggested, not approved")]
    due = [x for x in approved if x["status"] not in ("Not yet due", "Can't tell (no meter)")]
    return dict(date=date, as_of=cut.strftime("%Y-%m-%dT%H:00"), honesty=HONESTY, steps=steps, alerts=alerts,
                covered={k: sorted(set(v)) for k, v in covered.items()},
                summary=dict(steps=len(steps), approved=len(approved), due=len(due), not_approved=cnt("Not approved"), suggested=cnt("Suggested, not approved"),
                             would_have_saved_inr=tot("would_have_saved_inr"), followed=cnt("Followed"), partly=cnt("Partly"), not_followed=cnt("Not followed"),
                             not_yet_due=cnt("Not yet due"), cant_tell=cnt("Can't tell (no meter)"), skipped=cnt("Skipped"), planned_inr=tot("planned_inr"),
                             verified_inr=tot("verified_inr"), missed_inr=tot("extra_inr")))


def _checked(g: str) -> str:
    return {"chillers": "which chillers drew power (CH-1, CH-3 sub-meters, above 5 kW)", "chw": "the chilled-water setpoint in the building control system",
            "ahu": "banquet AHU draw outside the planned on/off times (above 10 kW idle)", "laundry": "laundry draw outside the allowed hours",
            "water": "boost heating in the 18:00–22:00 peak", "ev": "EV-charger draw while the limit was planned"}[g]


def _end(t: str) -> str:
    return "midnight" if t == "00:00 (next day)" else t.replace(" (next day)", "")


def _window(a: dict) -> str:
    return "all day" if a["start"] == "00:00" and a["end"] == "00:00 (next day)" else f"{a['start']}–{_end(a['end'])}"


def _title(a: dict, dev: list, meters_row) -> str:
    g, first, last = a["group"], _hm(dev[0]), _hm(dev[-1] + 1)
    until = "all day" if a["start"] == "00:00" and a["end"] == "00:00 (next day)" else f"until {_end(a['end'])}"
    if g == "chillers":
        got = actual_stage(meters_row.chiller_ch1_kw, meters_row.chiller_ch3_kw)
        return f"Plan said {PLANNED[stage_of(a['setting'])]} {until}; {ACTUAL[got].replace(' ran', '')} ran from {first}"
    if g == "chw":
        return f"Plan said chilled water {a['setting']} {until}; it was set colder from {first}"
    if g == "ahu":
        return f"Plan said banquet AHUs off at {_end(a['end'])}; they ran {first}–{last}"
    if g == "laundry":
        return f"Plan said no laundry in the 18:00–22:00 peak; it ran from {first}"
    if g == "water":
        return f"Plan said water heating overnight; it boosted in the evening peak from {first}"
    return f"Plan said limit EV charging {a['start']}–{a['end']}; the chargers drew power from {first}"


def _alert(date, a, dev, n, extra_kwh, extra_inr, meters, day, cut, per_hour_extra, site="GGN", hotel="Gurugram", col=None, title=None) -> dict:
    m = meters.set_index("timestamp")
    t0, t1 = day + pd.Timedelta(hours=dev[0]), day + pd.Timedelta(hours=dev[-1] + 1)
    at = day + pd.Timedelta(hours=dev[1] + 1)                         # known once the second hour has passed
    w = m[(m.index >= t0 - pd.Timedelta(hours=6)) & (m.index <= min(t1 + pd.Timedelta(hours=6), cut))]
    col = col or EQUIP_COL[a["group"]]
    base = [float(v) - per_hour_extra.get(int((t - day) / pd.Timedelta(hours=1)), 0.0) for t, v in zip(w.index, w.total_kwh)]
    fmt = lambda t: t.strftime("%Y-%m-%dT%H:%M")
    title = title or _title(a, dev, m.loc[t0])
    ev = (f"Planned: {a['setting']} ({_window(a)}). The meters differ in {len(dev)} of {n} hours checked "
          f"({', '.join(_hm(h) for h in dev[:8])}{'…' if len(dev) > 8 else ''}): about {extra_kwh:,.0f} kWh more than the plan")
    return dict(id=f"PD-{date}-{'' if site == 'GGN' else site + '-'}{a['group']}-{a['start'][:2]}", site=site, hotel=hotel, rule="PLAN_DEVIATION", title=title, severity="Medium",
                equipment=a.get("equipment", ""), start=fmt(t0), end=fmt(t1), alert_time=fmt(at), flagged_h=len(dev), duration_h=float(len(dev)),
                detect_lag_h=float((at - t0) / pd.Timedelta(hours=1)), excess_kwh=round(extra_kwh, 1), cost=round(extra_inr, 1),
                per_hour=round(extra_inr / max(len(dev), 1), 1), per_day=round(extra_inr, 1), cost_basis="per_occurrence", cost_note="",
                channel="Alert" if extra_inr > DIGEST_BELOW_INR else "Daily digest", repeat_30d=0, inferred_note="", evidence=ev,
                cause="An approved plan step was not carried out on the floor (or the plan changed without being updated).",
                action="Ask the duty team why; either carry out the step or record a reason with Skip on Tomorrow's plan.",
                guardrail="recommend", guard_text="Recommendation only. A person approves.", post_hoc=False, text=f"{hotel} · {title}. {ev}.",
                chart=dict(t=[t.strftime("%Y-%m-%dT%H") for t in w.index], actual=[round(float(v), 1) for v in w.total_kwh],
                           baseline=[round(v, 1) for v in base], signals={col: [None if pd.isna(v) else round(float(v), 2) for v in w[col]]}))


def meters_for(live: pd.DataFrame, date: str) -> pd.DataFrame:
    day = pd.Timestamp(date)
    return live[(live.timestamp >= day) & (live.timestamp < day + pd.Timedelta(days=2))].reset_index(drop=True)


def finite(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


# ---- Jaipur and Goa: what their sub-meters can check (total chillers_kw / chiller_load_tr, lighting_kw, pumps_pool_kw, laundry_kw) -------
SITE_COL = {"chillers": "chillers_kw", "chw": None, "lighting": "lighting_kw", "pool": "pumps_pool_kw", "laundry": "laundry_kw", "demand": "laundry_kw"}
SITE_CHECKED = {"chillers": "total chiller kW per TR against the hotel's normal for that load (can't verify the exact chiller from meters)",
                "chw": "nothing: there is no chilled-water setpoint meter here", "lighting": "lighting draw above the usual for the hour after the planned off time",
                "pool": "pool-pump draw outside the planned filtration hours, and the hours run", "laundry": "laundry draw outside the allowed hours",
                "demand": "laundry draw while flexible loads were to be held back"}
LIGHT_IDLE_KW = 5.0


def _minute_of(t: str) -> int:
    return int(t[:2]) * 60 + int(t[3:5]) + (24 * 60 if "next day" in t else 0)


def check_site(date, actions, meters, as_of, ref, tariff, pf, suggested, site, cfg) -> dict:
    day = pd.Timestamp(date)
    cut = pd.Timestamp(as_of[:13] + ":00")
    m = meters.set_index("timestamp")
    rate = (tariff["energy"] + tariff["fsa"] + tariff["duty"]) / pf
    hotel = cfg["hotel"]
    norm = cfg["lighting_norm_kw"]
    peak = tuple(cfg["peak"])

    def row(h):
        t = day + pd.Timedelta(hours=h)
        return m.loc[t] if (t <= cut and t in m.index) else None

    pool_run_min = None
    if cfg.get("pool"):
        day_vals = [r["pumps_pool_kw"] for r in (row(h) for h in range(24)) if r is not None and not pd.isna(r["pumps_pool_kw"])]
        pool_run_min = min(day_vals) if day_vals else None

    steps, alerts, covered = [], [], {}
    for a in actions:
        g, s, e = a["group"], hour_of(a["start"]), hour_of(a["end"])
        if e <= s:
            e += 24
        planned_inr = float(a.get("saving_inr", 0.0))
        sid = a.get("id") or f"{g}|{a['start']}|{a.get('equipment', '')}"
        if suggested or a.get("decision") != "approve":
            st = "Suggested, not approved" if suggested else "Skipped" if a.get("decision") == "skip" else "Not approved"
            steps.append(dict(id=sid, group=g, start=a["start"], end=a["end"], setting=a["setting"], equipment=a.get("equipment", ""), status=st,
                              reason=a.get("decision_reason") or "", hours_checked=0, hours_differed=[], extra_kwh=0.0, extra_inr=0.0, planned_inr=0.0,
                              verified_inr=0.0, would_have_saved_inr=round(planned_inr, 1) if st != "Skipped" else 0.0,
                              what_was_checked={"Skipped": "skipped by the team with a reason, so not checked",
                                                "Not approved": "not approved, so not checked or counted"}.get(st, "suggested only: no plan was saved")))
            continue
        col = SITE_COL.get(g)
        if g == "lighting":
            off = -(-_minute_of(a["end"]) // 60)                     # first whole hour after the planned off time
            span = range(off, off + 6)
        elif g == "laundry":
            ok_h, span = allowed_hours(a["setting"]), range(0, 24)
        elif g == "pool":
            plan_h = allowed_hours(a["setting"])
            span = range(0, 24)
        else:
            span = range(s, e)
        dev, hrs, extra_kwh, extra_inr, ver, no_meter, per_hour = [], [], 0.0, 0.0, 0.0, 0, {}
        pool_on = 0
        for h in span:
            r = row(h)
            if r is None:
                continue
            if col is None or pd.isna(r.get(col, float("nan"))):
                no_meter += 1
                continue
            hrs.append(h)
            bad, kwh, inr = False, 0.0, 0.0
            if g == "chillers":
                tr = float(r.chiller_load_tr)
                normal = OP.curve_at(tr, ref["curve"])
                if tr > 20 and r.chillers_kw / tr > 1.15 * normal:          # poor kW per TR: more plant running than the load needs
                    bad, kwh = True, float(r.chillers_kw - tr * normal)
                    inr = kwh * rate
                elif h < 24:
                    ver += ref["poor_kwh_ly"][h] * rate
            elif g == "lighting":
                extra = float(r.lighting_kw) - norm[h % 24]
                if extra > LIGHT_IDLE_KW:
                    bad, kwh = True, extra
                    inr = kwh * rate
            elif g == "pool":
                run = float(r.pumps_pool_kw) - (pool_run_min or 0.0)
                on = run > 0.5 * cfg["pool"]["kw"]
                pool_on += on and h in plan_h
                if on and h not in plan_h:
                    bad, kwh = True, run
                    inr = kwh * rate
            elif g in ("laundry", "demand"):
                allowed = ok_h if g == "laundry" else set(range(0, 48)) - set(range(s, e))
                if h not in allowed and r.laundry_kw > FLEX_KW:
                    bad, kwh = True, float(r.laundry_kw)
                    inr = kwh / pf * tariff["peak"] if OP.in_win(h % 24, peak) else 0.0
            if bad:
                dev.append(h)
                extra_kwh += kwh
                extra_inr += inr
                per_hour[h] = kwh
        n, d = len(hrs), len(dev)
        if g == "chw" or (n == 0 and no_meter):
            status = "Can't tell (no meter)"
        elif n == 0:
            status = "Not yet due"
        elif d == 0:
            status = "Followed"
        elif d >= 2 and d >= n / 2:
            status = "Not followed"
        else:
            status = "Partly"
        if g in ("lighting", "pool", "laundry", "demand"):
            ver = planned_inr * (n / max(len(span), 1)) if status == "Followed" else 0.0
        elif status == "Not followed" or g == "chw":
            ver = 0.0
        fol = [h for h in hrs if h not in dev]
        if status in ("Followed", "Partly") and fol:
            covered.setdefault(g, []).extend(h for h in fol if h < 24)
        note = SITE_CHECKED[g]
        if g == "pool" and n:
            note += f" (filtration ran {pool_on} h in the planned window so far)"
        steps.append(dict(id=sid, group=g, start=a["start"], end=a["end"], setting=a["setting"], would_have_saved_inr=0.0, equipment=a.get("equipment", ""),
                          status=status, hours_checked=n, hours_differed=[_hm(h) for h in dev], extra_kwh=round(extra_kwh, 1), extra_inr=round(extra_inr, 1),
                          planned_inr=round(planned_inr, 1), verified_inr=round(ver, 1), what_was_checked=note))
        if status == "Not followed":
            title = {"chillers": f"Plan said {a['setting'].split(':')[0].lower()}; the plant ran at poor kW per TR from {_hm(dev[0])}",
                     "lighting": f"Plan said event lighting off at {_end(a['end'])}; it stayed on {_hm(dev[0])}–{_hm(dev[-1] + 1)}",
                     "pool": f"Plan said pool filtration only in its schedule; the pumps ran from {_hm(dev[0])}",
                     "laundry": f"Plan said no laundry in the {_hm(peak[0])}–{_hm(peak[1])} peak; it ran from {_hm(dev[0])}",
                     "demand": f"Plan said hold flexible loads {a['start']}–{_end(a['end'])}; laundry ran from {_hm(dev[0])}"}.get(g)
            alerts.append(_alert(date, a, dev, n, extra_kwh, extra_inr, meters, day, cut, per_hour, site=site, hotel=hotel, col=col, title=title))
    tot = lambda k: round(sum(x[k] for x in steps), 1)
    cnt = lambda st: sum(1 for x in steps if x["status"] == st)
    approved = [x for x in steps if x["status"] not in ("Skipped", "Not approved", "Suggested, not approved")]
    due = [x for x in approved if x["status"] not in ("Not yet due", "Can't tell (no meter)")]
    return dict(date=date, site=site, as_of=cut.strftime("%Y-%m-%dT%H:00"), honesty=HONESTY, steps=steps, alerts=alerts,
                covered={k: sorted(set(v)) for k, v in covered.items()},
                summary=dict(steps=len(steps), approved=len(approved), due=len(due), not_approved=cnt("Not approved"), suggested=cnt("Suggested, not approved"),
                             would_have_saved_inr=tot("would_have_saved_inr"), followed=cnt("Followed"), partly=cnt("Partly"), not_followed=cnt("Not followed"),
                             not_yet_due=cnt("Not yet due"), cant_tell=cnt("Can't tell (no meter)"), skipped=cnt("Skipped"), planned_inr=tot("planned_inr"),
                             verified_inr=tot("verified_inr"), missed_inr=tot("extra_inr")))
