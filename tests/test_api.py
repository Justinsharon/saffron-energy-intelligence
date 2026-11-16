"""Plan API (api/main.py): ambiguous inputs give 200 with a plain-English note, or a clear 422 - never a silent drop or a crash.

Weather is stubbed (no network in tests). Run: uv run pytest tests
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from fastapi.testclient import TestClient  # noqa: E402

import api.main as A  # noqa: E402

TODAY = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
TOMORROW = (TODAY + timedelta(days=1)).isoformat()


@pytest.fixture(scope="module")
def c():
    A._open_meteo = lambda date, notes, site="GGN": [18.0 + 8 * (h > 9 and h < 18) for h in range(24)]     # fixed forecast, no network
    return TestClient(A.app)


def post(c, body):
    r = c.post("/plan", json=body)
    return r, r.json()


def joined(j):
    return " | ".join(j.get("notes", []))


def test_normal_booking(c):
    r, j = post(c, {"date": TOMORROW, "bookings": [{"hall": "A", "start": "14:00", "end": "18:00", "guests": 300}]})
    assert r.status_code == 200 and j["site"] == "GGN"
    assert j["inputs_used"]["bookings"] == [dict(hall="A", start="14:00", end="18:00", guests=300)]
    ahu = [a for a in j["actions"] if a["group"] == "ahu"]
    assert [(a["start"], a["end"]) for a in ahu] == [("13:00", "19:00")]


def test_aliases_are_used_and_unknown_fields_noted(c):
    r, j = post(c, {"date": TOMORROW, "rooms_occupied": 170, "guests_in_house": 300, "restaurant_covers": 400, "colour": "blue",
                    "bookings": [{"hall": "B", "start": "09:00", "end": "17:00", "guests": 120, "caterer": "X"}]})
    assert r.status_code == 200
    u = j["inputs_used"]
    assert (u["rooms"], u["guests"], u["covers"]) == (170, 300, 400)
    assert "ignored field: colour" in joined(j) and "Booking 1: ignored field: caterer" in joined(j)


def test_alias_conflict_is_noted(c):
    r, j = post(c, {"date": TOMORROW, "rooms": 150, "rooms_occupied": 160})
    assert r.status_code == 200 and "both 'rooms' and an alias" in joined(j)


@pytest.mark.parametrize("site,code", [("JAI", "JAI"), ("Jaipur", "JAI"), ("goa", "GOA")])
def test_other_sites_planned(c, site, code):
    r, j = post(c, {"site": site, "date": TOMORROW})
    assert r.status_code == 200 and j["site"] == code and j["actions"]


def test_unknown_site_422_and_gurugram_names_ok(c):
    assert post(c, {"site": "Mumbai"})[0].status_code == 422
    assert post(c, {"site": "Gurugram", "date": TOMORROW})[0].status_code == 200


def test_overlapping_bookings_same_hall_combined(c):
    r, j = post(c, {"date": TOMORROW, "bookings": [{"hall": "A", "start": "09:00", "end": "13:00", "guests": 150},
                                                    {"hall": "A", "start": "12:00", "end": "18:00", "guests": 300},
                                                    {"hall": "B", "start": "10:00", "end": "12:00", "guests": 80}]})
    assert r.status_code == 200
    assert "overlap in the same hall" in joined(j) and "1 (Hall A 09:00–13:00" in joined(j) and "2 (Hall A 12:00–18:00" in joined(j)
    assert dict(hall="A", start="09:00", end="18:00", guests=300) in j["inputs_used"]["bookings"]
    assert len(j["inputs_used"]["bookings"]) == 2                     # Hall B does not overlap Hall A


def test_hall_ab_overlaps_a(c):
    r, j = post(c, {"date": TOMORROW, "bookings": [{"hall": "A", "start": "17:00", "end": "20:00", "guests": 100},
                                                    {"hall": "A+B", "start": "19:00", "end": "23:59", "guests": 400}]})
    assert r.status_code == 200 and [b["hall"] for b in j["inputs_used"]["bookings"]] == ["A+B"]


def test_end_before_start(c):
    r, j = post(c, {"date": TOMORROW, "bookings": [{"hall": "A", "start": "22:00", "end": "02:00", "guests": 100}]})
    assert r.status_code == 200
    assert "Booking 1 ends before it starts (22:00 to 02:00); treated as running past midnight to 02:00 next day." in j["notes"]
    ahu = [a for a in j["actions"] if a["group"] == "ahu"][0]
    assert ahu["end"] == "03:00 (next day)"


def test_far_future_and_past_dates(c):
    far = (TODAY + timedelta(days=30)).isoformat()
    r, j = post(c, {"date": far})
    assert r.status_code == 200 and "No weather forecast that far ahead; typical temperatures for the date are used." in j["notes"]
    assert j["inputs_used"]["weather"] == "typical temperatures for this date"
    past = (TODAY - timedelta(days=10)).isoformat()
    if past >= A.META["dates"][0]:
        r, j = post(c, {"date": past})
        assert r.status_code == 200 and "look-back forecast" in joined(j)


def test_empty_request_lists_usual_pattern(c):
    r, j = post(c, {})
    assert r.status_code == 200 and j["date"] == TOMORROW
    n = joined(j)
    assert "No date given" in n and "From the usual pattern for a" in n and "rooms occupied" in n and "No banquet bookings" in n


def test_no_body_and_non_object(c):
    r = c.post("/plan", content=b"not json", headers={"content-type": "application/json"})
    assert r.status_code == 200 and "no readable JSON" in " ".join(r.json()["notes"])
    r, j = post(c, ["a", "list"])
    assert r.status_code == 200 and "must be a JSON object" in joined(j)


def test_bad_date_and_uncovered_date_422(c):
    assert post(c, {"date": "16/11/2026"})[0].status_code == 422
    assert post(c, {"date": "2030-01-01"})[0].status_code == 422


def test_chw_reason_uses_measured_penalty(c):
    r, j = post(c, {"date": TOMORROW})
    eight = [a for a in j["actions"] if a["group"] == "chw" and a["setting"] == "8.0 °C"]
    assert eight, "expected an 8.0 °C window on a mild day"
    for a in eight:
        assert "measured on these chillers" in a["reason"] and "3.5 %" not in a["reason"]
    lo, hi = min(A.META["chw_pct_per_c"]) * 100, max(A.META["chw_pct_per_c"]) * 100
    assert 4.0 <= lo <= hi <= 7.5


def test_bad_values_are_noted_not_errors(c):
    r, j = post(c, {"date": TOMORROW, "rooms": "lots", "guests": 9999, "temps": [1, 2],
                    "bookings": [{"hall": "C", "start": "x", "end": "y", "guests": 5}, "oops", {"hall": "A", "start": "02:00", "end": "06:00", "guests": 1200}]})
    assert r.status_code == 200
    n = joined(j)
    for s in ("not a number", "outside what the models saw", "temps must be 24", "is not A, B or A+B", "is not an object", "more than any conference", "extrapolation"):
        assert s in n, s
