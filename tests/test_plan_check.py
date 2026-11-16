"""Plan vs actual (src/plan_check.py) and the API's /check and /savings. Run: uv run pytest tests

The rules that matter most: nothing after the as-of hour is ever read; a skipped step is a decision, not a deviation; a step not followed
for 2+ hours (and at least half the hours checked) becomes a PLAN_DEVIATION alert, a Daily digest item unless it costs more than ₹2,000;
followed hours are reported as covered so alert ₹ for them is not counted again.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
import plan_check as PC  # noqa: E402

TARIFF = dict(energy=7.313, fsa=0.484, duty=0.103, peak=1.03, offpeak=-0.772, penalty=597.4)
REF = dict(curve=dict(edges=[20, 80, 130, 200, 280], values=[0.67, 0.61, 0.65, 0.62]), kwtr_ly=[0.7] * 24, chw_pct_per_c=[0.043, 0.051, 0.068, 0.069],
           ahu_overrun_kwh=dict(corporate=78, social=63), laundry_peak_kwh=40, water_peak_kwh=2, ev_kw=[0] * 24)
DATE = "2026-11-10"


def meters(**over):
    t = pd.date_range(DATE, periods=48, freq="h")
    d = pd.DataFrame(dict(timestamp=t, chiller_ch1_kw=0.0, chiller_ch3_kw=60.0, chillers_kw=60.0, chiller_load_tr=100.0, chw_setpoint_c=8.0,
                          ahu_banquet_kw=0.0, laundry_kw=0.0, water_heating_kw=20.0, ev_chargers_kw=0.0, kva=500.0, total_kwh=450.0))
    for col, (hours, val) in over.items():
        d.loc[d.timestamp.dt.hour.isin(hours) & (d.timestamp.dt.date == pd.Timestamp(DATE).date()), col] = val
    return d


def act(group, start, end, setting, **kw):
    kw.setdefault("decision", "approve")                      # only approved steps of a saved plan are checked
    return dict(group=group, start=start, end=end, setting=setting, equipment=group, saving_inr=100.0, **kw)


def test_followed_and_not_yet_due():
    a = [act("chillers", "00:00", "12:00", "CH-3 alone (150 TR scroll chiller)"), act("chw", "13:00", "20:00", "8.0 °C", setpoint_c=8.0)]
    r = PC.check_day(DATE, a, meters(), f"{DATE}T09:30", REF, TARIFF, 0.97)
    s = {x["group"]: x for x in r["steps"]}
    assert s["chillers"]["status"] == "Followed" and s["chillers"]["hours_checked"] == 10     # 00:00..09:00 only
    assert s["chw"]["status"] == "Not yet due"
    assert r["as_of"] == f"{DATE}T09:00" and not r["alerts"]
    assert r["covered"]["chillers"] == list(range(10))


def test_never_reads_after_as_of():
    # both chillers run from 11:00, after the as-of hour: must not count
    r = PC.check_day(DATE, [act("chillers", "00:00", "20:00", "CH-3 alone (150 TR scroll chiller)")],
                     meters(chiller_ch1_kw=(range(11, 20), 80.0), chillers_kw=(range(11, 20), 140.0)), f"{DATE}T10:15", REF, TARIFF, 0.97)
    assert r["steps"][0]["status"] == "Followed" and r["steps"][0]["hours_checked"] == 11


def test_not_followed_raises_deviation_alert():
    r = PC.check_day(DATE, [act("chillers", "00:00", "12:00", "CH-3 alone (150 TR scroll chiller)")],
                     meters(chiller_ch1_kw=(range(7, 12), 80.0), chillers_kw=(range(7, 12), 140.0)), f"{DATE}T13:00", REF, TARIFF, 0.97)
    st = r["steps"][0]
    assert st["status"] == "Partly" and st["hours_differed"][0] == "07:00"         # 5 of 12 hours: less than half
    r = PC.check_day(DATE, [act("chillers", "05:00", "12:00", "CH-3 alone (150 TR scroll chiller)")],
                     meters(chiller_ch1_kw=(range(7, 12), 80.0), chillers_kw=(range(7, 12), 140.0)), f"{DATE}T13:00", REF, TARIFF, 0.97)
    st, al = r["steps"][0], r["alerts"]
    assert st["status"] == "Not followed" and st["extra_inr"] > 0 and len(al) == 1
    a = al[0]
    assert a["rule"] == "PLAN_DEVIATION" and a["title"] == "Plan said Chiller 3 only until 12:00; both ran from 07:00"
    assert a["alert_time"] == f"{DATE}T09:00" and a["cost_basis"] == "per_occurrence"
    assert a["channel"] == ("Alert" if a["cost"] > PC.DIGEST_BELOW_INR else "Daily digest")
    assert all(t <= f"{DATE}T13" for t in a["chart"]["t"])                        # evidence chart cut at the as-of hour too


def test_setpoint_colder_than_planned_is_a_deviation():
    r = PC.check_day(DATE, [act("chw", "00:00", "10:00", "8.0 °C", setpoint_c=8.0)], meters(chw_setpoint_c=(range(0, 10), 7.0)),
                     f"{DATE}T12:00", REF, TARIFF, 0.97)
    assert r["steps"][0]["status"] == "Not followed" and "set colder" in r["alerts"][0]["title"]


def test_ahu_run_on_and_laundry_in_peak():
    a = [act("ahu", "08:00", "19:00", "On at 08:00, off at 19:00", on_h=8, start_h=9),
         act("laundry", "00:00", "00:00 (next day)", "Run batches only 00:00–18:00, 22:00–00:00 (next day)")]
    r = PC.check_day(DATE, a, meters(ahu_banquet_kw=(range(9, 23), 90.0), laundry_kw=(range(18, 20), 70.0)), f"{DATE}T23:00", REF, TARIFF, 0.97)
    s = {x["group"]: x for x in r["steps"]}
    assert s["ahu"]["hours_differed"] == ["19:00", "20:00", "21:00", "22:00"]
    assert s["laundry"]["hours_differed"] == ["18:00", "19:00"] and s["laundry"]["extra_inr"] == pytest.approx(140 / 0.97 * 1.03, rel=1e-3)


def test_skipped_step_is_not_a_deviation():
    a = [act("chillers", "05:00", "12:00", "CH-3 alone (150 TR scroll chiller)", decision="skip", decision_reason="CH-3 under maintenance")]
    r = PC.check_day(DATE, a, meters(chiller_ch1_kw=(range(5, 12), 80.0)), f"{DATE}T13:00", REF, TARIFF, 0.97)
    assert r["steps"][0]["status"] == "Skipped" and not r["alerts"] and r["summary"]["skipped"] == 1


def test_unapproved_and_suggested_steps_are_never_counted():
    bad = meters(chiller_ch1_kw=(range(5, 12), 80.0), chillers_kw=(range(5, 12), 140.0))
    a = [act("chillers", "05:00", "12:00", "CH-3 alone (150 TR scroll chiller)", decision=None)]
    r = PC.check_day(DATE, a, bad, f"{DATE}T13:00", REF, TARIFF, 0.97)
    st = r["steps"][0]
    assert st["status"] == "Not approved" and not r["alerts"] and st["extra_inr"] == 0 and st["would_have_saved_inr"] == 100.0
    assert r["summary"]["verified_inr"] == 0 and r["summary"]["missed_inr"] == 0 and r["summary"]["planned_inr"] == 0
    r = PC.check_day(DATE, [act("chillers", "05:00", "12:00", "CH-3 alone (150 TR scroll chiller)")], bad, f"{DATE}T13:00", REF, TARIFF, 0.97, suggested=True)
    st = r["steps"][0]
    assert st["status"] == "Suggested, not approved" and not r["alerts"] and r["summary"]["would_have_saved_inr"] == 100.0
    assert r["summary"]["verified_inr"] == 0 and r["covered"] == {}


def test_only_approved_followed_steps_are_covered():
    a = [act("chillers", "00:00", "12:00", "CH-3 alone (150 TR scroll chiller)"),
         act("chw", "00:00", "12:00", "8.0 °C", setpoint_c=8.0, decision=None)]
    r = PC.check_day(DATE, a, meters(), f"{DATE}T13:00", REF, TARIFF, 0.97)
    assert set(r["covered"]) == {"chillers"} and r["summary"]["approved"] == 1 and r["summary"]["not_approved"] == 1


# ---- API ------------------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def c():
    from fastapi.testclient import TestClient
    import api.main as A
    A._open_meteo = lambda date, notes, site="GGN": None
    return TestClient(A.app), A


def test_check_endpoint_cuts_at_now(c):
    client, A = c
    today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date().isoformat()
    j = client.post("/check", json={"date": today}).json()
    now_h = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%dT%H")
    assert j["as_of"][:13] <= now_h and "simulated" in j["honesty"] and "suggested plan" in j["source"]
    assert not j["alerts"] and j["summary"]["verified_inr"] == 0 and j["summary"]["missed_inr"] == 0           # no saved plan: nothing counted
    assert all(x["status"] == "Suggested, not approved" for x in j["steps"])
    for a in j["alerts"]:
        assert a["alert_time"][:13] <= now_h and all(t <= now_h for t in a["chart"]["t"])
    future = client.post("/check", json={"date": today, "as_of": "2099-01-01T00:00"}).json()       # asking ahead is clamped to now
    assert future["as_of"][:13] <= now_h


def test_savings_endpoint_month(c):
    client, A = c
    j = client.post("/savings", json={"month": "2026-10"}).json()
    t = j["totals"]
    assert t["days"] == 30 and "never added to alert savings" in j["method"]
    assert t["verified_inr"] == 0 and t["planned_inr"] == 0 and t["would_have_saved_inr"] > 0          # no saved plans: suggested only
    approved = [dict(a, decision="approve") for a in client.post("/plan", json={"date": "2026-10-10"}).json()["actions"]]
    j = client.post("/savings", json={"month": "2026-10", "saved": {"2026-10-10": approved}}).json()
    day = [d for d in j["days"] if d["date"] == "2026-10-10"][0]
    assert day["source"] == "saved" and day["approved"] == len(approved) and j["totals"]["verified_inr"] == day["verified_inr"]
    assert client.post("/savings", json={"month": "2030-01"}).status_code == 422
