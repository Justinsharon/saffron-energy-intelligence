"""Guardrail tests for the operating plan (src/operating_plan.py). Run: uv run pytest tests

The brief's limits are non-negotiable, so they are tested on many generated days, not just the defaults: no chilled-water setpoint below
6.5 °C, nothing planned for kitchen exhaust / guest-room thermostats / lifts / fire and life-safety, never two chillers below 130 TR,
banquet AHUs never on more than 2 h before an event. validate() must also reject hand-made breaches.
"""
import json
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import operating_plan as OP  # noqa: E402

PLAN = ROOT / "web" / "public" / "data" / "plan"


def days():
    idx = json.loads((PLAN / "index.json").read_text(encoding="utf-8"))["days"]
    return [json.loads((PLAN / f"{d}.json").read_text(encoding="utf-8")) for d in sorted(idx)]


def random_bookings(rng):
    out = []
    for _ in range(rng.randint(0, 3)):
        hall = rng.choice(["A", "B", "A+B"])
        if hall == "A+B":
            s, end = rng.randint(17, 20), "23:59"
        else:
            s = rng.randint(7, 15)
            end = f"{min(s + rng.randint(2, 9), 23):02d}:00"
        out.append(dict(hall=hall, start=f"{s:02d}:00", end=end, guests=rng.choice([50, 150, 300, 600])))
    return out


@pytest.fixture(scope="module")
def all_days():
    d = days()
    assert len(d) >= 10, "run tools/export_plan_inputs.py first"
    return d


def test_guardrails_on_generated_days(all_days):
    rng = random.Random(7)
    n = 0
    for day in all_days:
        for _ in range(8):                                    # defaults, plus hot / cold / busy variations
            tmax = day["template_tmax"] + rng.uniform(-12, 18)
            bk = random_bookings(rng)
            f = OP.compose_day(day, rooms=rng.randint(60, 220), covers=rng.randint(100, 900), tmax=tmax, bookings=bk)
            acts = OP.plan_day(f["tr"], f["kva"], f["temp"], bk, day["pf"], day["ref"], day["tariff"])
            n += 1
            for a in acts:
                text = (a["equipment"] + " " + a["setting"]).lower()
                assert not any(w in text for w in OP.EXCLUDED), a
                assert a["kind"] == "plan" and a["group"] in {"chillers", "chw", "ahu", "laundry", "water", "ev"}
                if a["group"] == "chw":
                    assert a["setpoint_c"] >= OP.CHW_FLOOR and a["setpoint_c"] in (OP.CHW_STD, OP.CHW_RESET)
                if a["group"] == "ahu":
                    assert a["start_h"] - a["on_h"] <= 2
            # hour by hour: a two-chiller window never covers an hour under 130 TR
            for a in (x for x in acts if x["group"] == "chillers" and "together" in x["setting"]):
                s, e = int(a["start"][:2]), int(a["end"][:2]) or 24
                assert all(f["tr"][h] >= OP.CH3_MAX for h in range(s, e)), (day["date"], a)
            # every hour of the day has exactly one chiller stage and one setpoint
            for g in ("chillers", "chw"):
                hrs = sum((int(x["end"][:2]) or 24) - int(x["start"][:2]) for x in acts if x["group"] == g)
                assert hrs == 24, (g, day["date"])
    assert n >= 80


def test_two_chillers_only_above_one_chiller_band():
    for tr in range(0, 500, 5):
        if OP.stage(tr) == "CH-1+CH-3":
            assert tr * OP.TR_MARGIN > OP.CH1_MAX and tr >= OP.CH3_MAX
        if tr < OP.CH3_MAX:
            assert OP.stage(tr) != "CH-1+CH-3"


def test_setpoint_rule():
    day = days()[0]
    flat = lambda v: [v] * 24
    hot = OP.plan_day(flat(150.0), flat(600.0), flat(30.0), [], day["pf"], day["ref"], day["tariff"])
    cool = OP.plan_day(flat(100.0), flat(500.0), flat(18.0), [], day["pf"], day["ref"], day["tariff"])
    heavy_cool = OP.plan_day(flat(300.0), flat(700.0), flat(18.0), [], day["pf"], day["ref"], day["tariff"])
    sp = lambda acts: {a["setpoint_c"] for a in acts if a["group"] == "chw"}
    assert sp(hot) == {7.0} and sp(cool) == {8.0} and sp(heavy_cool) == {7.0}


def test_banquet_ahu_timing_and_laundry_peak():
    day = days()[0]
    bk = [dict(hall="A", start="10:00", end="17:00", guests=200), dict(hall="A+B", start="19:00", end="23:59", guests=400)]
    f = OP.compose_day(day, bookings=bk)
    acts = OP.plan_day(f["tr"], f["kva"], f["temp"], bk, day["pf"], day["ref"], day["tariff"])
    ahu = [a for a in acts if a["group"] == "ahu"]
    assert [(a["start"], a["end"]) for a in ahu] == [("09:00", "18:00"), ("18:00", "02:00 (next day)")]
    lau = [a for a in acts if a["group"] == "laundry"][0]
    for h in range(18, 22):
        assert f"{h:02d}:00–" not in lau["setting"] or h == 22


def test_ev_limit_only_above_920():
    day = days()[0]
    flat = lambda v: [v] * 24
    low = OP.plan_day(flat(150.0), flat(900.0), flat(30.0), [], day["pf"], day["ref"], day["tariff"])
    kva = flat(800.0); kva[15] = 1050.0
    high = OP.plan_day(flat(150.0), kva, flat(30.0), [], day["pf"], day["ref"], day["tariff"])
    assert not [a for a in low if a["group"] == "ev"]
    ev = [a for a in high if a["group"] == "ev"]
    assert [(a["start"], a["end"]) for a in ev] == [("15:00", "16:00")]


@pytest.mark.parametrize("bad", [
    dict(group="ahu", equipment="Kitchen exhaust and make-up air", setting="Off at 23:00", start_h=10, on_h=9),
    dict(group="chw", equipment="Guest-room thermostats", setting="26 °C", setpoint_c=7.0),
    dict(group="water", equipment="Lifts", setting="Park 2 of 6", ),
    dict(group="water", equipment="Fire pumps", setting="Off"),
    dict(group="chw", equipment="Chilled-water supply setpoint", setting="6.0 °C", setpoint_c=6.0),
    dict(group="chillers", equipment="Chillers (CH-1, CH-3)", setting="CH-1 + CH-3 together", min_tr=100.0, max_tr=140.0),
    dict(group="ahu", equipment="Banquet AHUs, Hall A (AHU-BQ-A)", setting="On at 06:00, off at 18:00", start_h=9, on_h=6),
])
def test_validate_rejects_breaches(bad):
    a = dict(kind="plan", start="00:00", end="01:00", reason="", saving_inr=0.0, guardrail="", **bad)
    with pytest.raises(ValueError):
        OP.validate([a])


def test_plan_needs_reference():
    with pytest.raises(ValueError):
        OP.plan_day([100.0] * 24, [500.0] * 24, [20.0] * 24, [], 0.97)
