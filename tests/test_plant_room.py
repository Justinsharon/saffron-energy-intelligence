"""Plant Room (web/plant.html, simulation): unit checks in the TypeScript model and store, and the three demo faults through the REAL
/check code path (api/main.py, additive `meters`) - each must raise a plan-deviation alert, and fixing / clearing must remove it. The
browser fallback (web/src/plant/check.ts, a port of src/plan_check.check_day) must agree with the API on every scenario.
Run: uv run pytest tests
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(ROOT / "tools")]
from fastapi.testclient import TestClient  # noqa: E402

import api.main as A  # noqa: E402
import plant_scenarios as PS  # noqa: E402

pytestmark = pytest.mark.skipif(not PS.available(), reason="needs node and web/node_modules (npm ci in web/)")


@pytest.fixture(scope="module")
def c():
    A._open_meteo = lambda date, notes, site="GGN": [18.0 + 8 * (h > 9 and h < 18) for h in range(24)]
    return TestClient(A.app)


@pytest.fixture(scope="module")
def run(c):
    plan = c.post("/plan", json=dict(date=PS.DATE, bookings=PS.BOOKINGS)).json()
    return plan, PS.run(plan)


def test_unit_checks(run):
    _, out = run
    assert out["unit"] == dict(noise_within_2_5_pct=True, habit_until_apply_then_plan=True, chw_below_6_5_refused=True,
                               monitored_only_no_actions=True, every_action_audited=True, local_check_matches_expectations=True)
    lo, hi = out["creep_kva"]
    assert hi > lo + 50


def test_faults_raise_alerts_and_fixes_clear_them(c, run):
    plan, out = run
    assert len(out["scenarios"]) == 7
    for sc in out["scenarios"]:
        r = c.post("/check", json=PS.check_body(plan, sc))
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["meters_source"] == "simulated" and any("SIMULATED" in n for n in j["notes"])
        assert bool(j["alerts"]) == sc["expect_alert"], (sc["name"], j["alerts"], j["steps"])
        if sc["expect_alert"]:
            assert any(a["rule"] == "PLAN_DEVIATION" and sc["group"] in a["id"] for a in j["alerts"]), sc["name"]
        # the browser fallback says the same thing
        assert [a["id"] for a in j["alerts"]] == [a["id"] for a in sc["local"]["alerts"]], sc["name"]
        assert [a["title"] for a in j["alerts"]] == [a["title"] for a in sc["local"]["alerts"]], sc["name"]
        assert {s["id"]: s["status"] for s in j["steps"]} == {s["id"]: s["status"] for s in sc["local"]["steps"]}, sc["name"]
        for x, y in zip(j["alerts"], sc["local"]["alerts"]):
            assert abs(x["cost"] - y["cost"]) <= max(1.0, 0.01 * abs(x["cost"]))


def test_check_without_meters_is_unchanged(c):
    # additive only: the old request shape still reads the live meters (cut at now) and has no meters_source
    r = c.post("/check", json=dict(date=PS.DATE, site="GGN"))
    assert r.status_code == 200 and "meters_source" not in r.json()


def test_bad_meters_are_a_clear_422(c):
    assert c.post("/check", json=dict(date=PS.DATE, meters=[])).status_code == 422
    assert c.post("/check", json=dict(date=PS.DATE, meters=[dict(timestamp="2025-01-01T00:00")])).status_code == 422
    assert c.post("/check", json=dict(date=PS.DATE, site="JAI", meters=[dict(timestamp=f"{PS.DATE}T00:00")])).status_code == 422
