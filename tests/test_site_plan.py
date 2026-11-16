"""Jaipur and Goa operating plans (src/operating_plan.plan_site, api/main.py): guardrails per hotel, venue validation, odd inputs, and plan
vs actual on their sub-meters. Weather is stubbed (no network in tests). Run: uv run pytest tests
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from fastapi.testclient import TestClient  # noqa: E402

import api.main as A  # noqa: E402
import operating_plan as OP  # noqa: E402
import plan_check as PC  # noqa: E402

TOMORROW = (datetime.now(timezone(timedelta(hours=5, minutes=30))).date() + timedelta(days=1)).isoformat()
META = json.loads((ROOT / "models" / "meta.json").read_text(encoding="utf-8"))["sites"]
WEDDING = {"JAI": {"hall": "Palace Lawns", "start": "19:00", "end": "23:30", "guests": 400},
           "GOA": {"hall": "Sunset Deck + Ballroom", "start": "18:00", "end": "23:00", "guests": 300}}


@pytest.fixture(scope="module")
def c():
    A._open_meteo = lambda date, notes, site="GGN": None
    return TestClient(A.app)


def post(c, body, path="/plan"):
    r = c.post(path, json=body)
    return r, r.json()


def joined(j):
    return " | ".join(j.get("notes", []))


# ---- guardrails per hotel -----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("site", ["JAI", "GOA"])
@pytest.mark.parametrize("date", ["2026-10-05", "2026-12-20", "2027-01-15", "2027-05-20", "2027-06-15", "2027-08-10"])
def test_guardrails_hold_every_day(c, site, date):
    r, j = post(c, {"site": site, "date": date, "bookings": [WEDDING[site]], "tmax": 45 if "-05-" in date or "-06-" in date else None})
    assert r.status_code == 200 and j["site"] == site and j["recommend_only"]
    cfg = META[site]["config"]
    two_min = min(cfg["chillers"]["units_tr"])
    for a in j["actions"]:
        text = (a["equipment"] + " " + a["setting"]).lower()
        assert not any(w in text for w in OP.EXCLUDED), a                         # never kitchen exhaust, thermostats, lifts, fire / life-safety
        if a["group"] == "chw":
            assert a["setpoint_c"] >= 6.5 and a["saving_inr"] == 0 and a["counted"] is False and "not verifiable" in a["reason"]
        if a["group"] == "chillers":
            assert "Can't verify the exact chiller from meters; checked by total kW per TR" in a["reason"]
            if "together" in a["setting"]:
                assert a["min_tr"] >= two_min
            else:
                assert a["max_tr"] < two_min or a["max_tr"] <= OP.ONE_MARGIN * max(cfg["chillers"]["units_tr"])
        if a["group"] == "pool":
            assert a["run_hours"] >= 8
        if a["group"] == "laundry":
            pk = range(*cfg["peak"]) if cfg["peak"][0] < cfg["peak"][1] else None
            assert pk is None or not set(PC.allowed_hours(a["setting"].split(";")[0])) & set(pk)
        if a["group"] == "demand":
            assert a["saving_inr"] == 0
    assert j["total_saving_inr"] == round(sum(a["saving_inr"] for a in j["actions"]))          # CHW estimate never in the total
    assert j["contract_kva"] == cfg["cd_kva"]


def test_two_chiller_line_matches_each_register():
    reg = pd.read_parquet(ROOT / "data" / "clean" / "equipment_register.parquet")
    for site in ("JAI", "GOA"):
        units = META[site]["config"]["chillers"]["units_tr"]
        assert OP.TWO_MIN_TR[site] == min(units)
        assert reg[(reg.site == site) & reg.description.str.contains("chiller", case=False)].rating.iloc[0].startswith(f"{len(units)} × {units[0]:.0f}")
    assert META["GOA"]["config"]["pool"]["min_hours"] >= 8 and META["JAI"]["config"]["pool"] is None      # Jaipur's register has no pool pumps


@pytest.mark.parametrize("bad", [
    dict(group="chillers", setting="Both chillers together (ACH-1 + ACH-2)", equipment="Chillers", min_tr=120.0),
    dict(group="chw", setting="6.0 °C", equipment="Chilled-water supply setpoint", setpoint_c=6.0),
    dict(group="pool", setting="Run filtration 07:00–13:00 (6 h)", equipment="Pool filtration pumps", run_hours=6),
    dict(group="demand", setting="Hold", equipment="Kitchen exhaust fans"),
    dict(group="demand", setting="Turn off lifts 2 and 3", equipment="Flexible loads"),
    dict(group="lighting", setting="Off", equipment="Guest-room thermostats"),
])
def test_validate_refuses(bad):
    with pytest.raises(ValueError):
        OP.validate([dict(bad, kind="plan", site="GOA", saving_inr=0.0, start="00:00", end="01:00")], META["GOA"]["config"])


# ---- venues -------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("site,typed,venue", [("JAI", "lawns", "Palace Lawns"), ("JAI", "Palace lawn", "Palace Lawns"), ("JAI", "durbar", "Durbar Hall"),
                                              ("JAI", "DURBAR HALL", "Durbar Hall"), ("GOA", "ballroom", "Sunset Deck + Ballroom"),
                                              ("GOA", "Sunset deck", "Sunset Deck + Ballroom")])
def test_venue_aliases(c, site, typed, venue):
    r, j = post(c, {"site": site, "date": TOMORROW, "bookings": [{"hall": typed, "start": "18:00", "end": "22:00", "guests": 100}]})
    assert r.status_code == 200 and j["inputs_used"]["bookings"][0]["hall"] == venue
    assert any(a["group"] == "lighting" and venue in a["equipment"] for a in j["actions"])


@pytest.mark.parametrize("site,typed", [("JAI", "A"), ("JAI", "Hall A+B"), ("GOA", "Palace Lawns"), ("GOA", "Durbar Hall"), ("JAI", "Rooftop")])
def test_unknown_venue_skipped_with_note(c, site, typed):
    r, j = post(c, {"site": site, "date": TOMORROW, "bookings": [{"hall": typed, "start": "18:00", "end": "22:00", "guests": 100}]})
    assert r.status_code == 200 and j["inputs_used"]["bookings"] == []
    assert f"'{typed}' is not a" in joined(j) and not any(a["group"] == "lighting" for a in j["actions"])


def test_lighting_window_30_min(c):
    r, j = post(c, {"site": "JAI", "date": TOMORROW, "bookings": [WEDDING["JAI"]]})
    lt = [a for a in j["actions"] if a["group"] == "lighting"][0]
    assert (lt["start"], lt["end"]) == ("18:30", "00:00 (next day)") and "LAWN-LTG" in lt["equipment"]
    assert lt["saving_inr"] > 0


# ---- six odd inputs (and a few more) for Jaipur / Goa: 200 with a note, never an error -----------------------------------------------
@pytest.mark.parametrize("site", ["JAI", "GOA"])
def test_odd_inputs(c, site):
    venue = WEDDING[site]["hall"]
    cap = META[site]["ranges"]["event_guests"][venue]
    # 1 guests above anything seen at the venue -> capped with a note
    r, j = post(c, {"site": site, "date": TOMORROW, "bookings": [dict(WEDDING[site], guests=5000)]})
    assert r.status_code == 200 and j["inputs_used"]["bookings"][0]["guests"] == cap and "lower bound" in joined(j)
    # 2 end before start -> runs past midnight
    r, j = post(c, {"site": site, "date": TOMORROW, "bookings": [dict(WEDDING[site], start="20:00", end="02:00")]})
    assert r.status_code == 200 and "past midnight" in joined(j)
    # 3 rooms above the hotel's own count -> clamped to it
    r, j = post(c, {"site": site, "date": TOMORROW, "rooms": 999})
    assert r.status_code == 200 and j["inputs_used"]["rooms"] == META[site]["ranges"]["rooms"][1] and "outside what the models saw" in joined(j)
    # 4 text where a number belongs, and temps of the wrong length
    r, j = post(c, {"site": site, "date": TOMORROW, "covers": "lots", "temps": [30, 31]})
    assert r.status_code == 200 and "not a number" in joined(j) and "temps must be 24" in joined(j)
    # 5 unknown field and a booking alias (venue / pax)
    r, j = post(c, {"site": site, "date": TOMORROW, "colour": "red", "bookings": [{"venue": venue, "start": "18:00", "end": "22:00", "pax": 120}]})
    assert r.status_code == 200 and "ignored field: colour" in joined(j) and j["inputs_used"]["bookings"][0]["guests"] == 120
    # 6 two overlapping bookings at one venue -> one event
    r, j = post(c, {"site": site, "date": TOMORROW, "bookings": [dict(WEDDING[site], start="18:00", end="21:00", guests=200),
                                                                dict(WEDDING[site], start="20:00", end="23:00", guests=300)]})
    assert r.status_code == 200 and len(j["inputs_used"]["bookings"]) == 1 and j["inputs_used"]["bookings"][0]["guests"] == 300 and "overlap" in joined(j)
    # 7 bookings not a list, a bad time and zero guests
    r, j = post(c, {"site": site, "date": TOMORROW, "bookings": "wedding"})
    assert r.status_code == 200 and "must be a list" in joined(j)
    r, j = post(c, {"site": site, "date": TOMORROW, "bookings": [dict(WEDDING[site], start="7pm"), dict(WEDDING[site], guests=0)]})
    assert r.status_code == 200 and "times like 14:00" in joined(j) and "positive number" in joined(j)


def test_only_dates_outside_the_live_year_are_422(c):
    assert post(c, {"site": "JAI", "date": "2030-01-01"})[0].status_code == 422
    assert post(c, {"site": "Mumbai"})[0].status_code == 422


# ---- /forecast and /risk ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("site,cd", [("JAI", 700), ("GOA", 600), ("GGN", 1000)])
def test_forecast_and_risk_endpoints(c, site, cd):
    r, f = post(c, {"site": site, "date": TOMORROW}, "/forecast")
    assert r.status_code == 200 and len(f["forecast"]["kva"]) == 24 and "actions" not in f
    r, k = post(c, {"site": site, "date": TOMORROW}, "/risk")
    assert r.status_code == 200 and k["contract_kva"] == cd and k["risk"]["level"] in ("OK", "STACKING WATCH", "WARNING", "BREACH RISK")


# ---- plan vs actual on the Jaipur / Goa sub-meters ------------------------------------------------------------------------------
@pytest.mark.parametrize("site", ["JAI", "GOA"])
def test_check_approved_plan(c, site):
    date = "2026-10-20"
    p = post(c, {"site": site, "date": date, "bookings": [WEDDING[site]]})[1]
    acts = [dict(a, id=f"{a['group']}{i}", decision="approve") for i, a in enumerate(p["actions"])]
    r, j = post(c, {"site": site, "date": date, "as_of": "2026-10-22T10:00", "actions": acts}, "/check")
    assert r.status_code == 200 and j["summary"]["approved"] == len(acts)
    by = {s["group"]: s for s in j["steps"]}
    assert by["chw"]["status"] == "Can't tell (no meter)" and by["chw"]["verified_inr"] == 0
    assert "kW per TR" in by["chillers"]["what_was_checked"] and by["chillers"]["status"] in ("Followed", "Partly", "Not followed")
    assert by["lighting"]["status"] in ("Followed", "Partly", "Not followed")
    if site == "GOA":
        assert by["pool"]["status"] in ("Followed", "Partly", "Not followed") and "filtration ran" in by["pool"]["what_was_checked"]
    for a in j["alerts"]:
        assert a["site"] == site and a["rule"] == "PLAN_DEVIATION"
    r, s = post(c, {"site": site, "month": "2026-10", "as_of": "2026-10-31T23:00"}, "/savings")
    assert r.status_code == 200 and s["site"] == site and s["totals"]["verified_inr"] == 0      # nothing saved: suggested only
