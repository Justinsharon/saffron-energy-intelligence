"""CH-1 inefficiency (STAGING_KWTR, post-hoc): the per-chiller sub-meters show CH-1 alone, so it is not a hidden second chiller; it is
shown with its ₹ but never counted as waste, savings or plan staging ₹. Run: uv run pytest tests
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]
import alert_cards as AC  # noqa: E402
import recalibration as RC  # noqa: E402
import savings  # noqa: E402
from features import APP  # noqa: E402


def test_flagged_hours_are_ch1_alone():
    d = RC._frame()
    F = RC.fit(d)
    k = RC.ch1_summary(d, F)
    assert k["hours"] > 0 and k["ch3_on_h"] == 0                       # CH-3's sub-meter reads 0 in every flagged hour
    assert k["kwtr"] > F["thr"] * k["normal_lo"]


def test_cards_relabelled():
    c = pd.read_parquet(APP / "cards.parquet")
    k = c[c.rule == "STAGING_KWTR"]
    assert len(k) and (k.title == "Chiller 1 running inefficiently (cause to inspect)").all() and (k.equipment == "chiller CH-1").all()
    assert (k.severity == "Medium").all() and k.cause.str.contains("not a second chiller").all() and k.cause.str.contains("Not counted").all()
    assert not k.evidence.str.contains("two chillers at part load").any()
    assert AC.CHART["STAGING_KWTR"] == ["chiller_ch1_kw", "chiller_ch3_kw", "chiller_load_tr", "kw_per_tr"]


def test_not_counted_in_savings():
    c = pd.read_parquet(APP / "cards.parquet").query("site == 'GGN'")
    p = savings.plan()
    act = p[(p.site == "GGN") & p.measure.str.startswith("Act on detected")].inr.sum()
    e = c[~c.rule.isin(["LAUNDRY_IN_PEAK", "DEMAND_NEAR_CONTRACT", "POWER_FACTOR_DROP", "STAGING_KWTR"])]
    assert abs(act - e.cost_inr.sum()) < 1
    line = [x for x in savings.not_sized() if x.startswith("CH-1 running near")]
    assert line and "not claimed" in line[0]


def test_plan_refs_ignore_ch1_alone_hours():
    import export_plan_inputs as EP
    F = RC.fit(RC._frame())
    days = pd.date_range("2026-06-01", periods=10, freq="D")
    ts = pd.DatetimeIndex([d + pd.Timedelta(hours=h) for d in days for h in range(24)])
    orig = pd.DataFrame(dict(timestamp=ts, chiller_load_tr=180.0, weekend=0))
    sub = pd.DataFrame(dict(timestamp=ts, chiller_load_tr=180.0, chiller_ch1_kw=190.0, chiller_ch2_kw=0.0, chiller_ch3_kw=0.0,
                            laundry_kw=0.0, water_heating_kw=0.0, ev_chargers_kw=0.0))       # CH-1 alone at ~1.06 kW/TR
    r = EP.matched_refs(orig, sub, pd.Timestamp("2027-06-08"), 180.0, F["curve"])
    normal = float(pd.cut(pd.Series([180.0]), RC.BANDS).map(F["curve"]).astype(float).iloc[0])
    assert all(abs(v - normal) < 1e-3 for v in r["kwtr_ly"])            # counted at the normal one-chiller kW/TR: no staging ₹
    sub.loc[:, "chiller_ch3_kw"] = 60.0                                # two chillers really ran: the measured kW/TR stays
    r2 = EP.matched_refs(orig, sub, pd.Timestamp("2027-06-08"), 180.0, F["curve"])
    assert all(v > normal + 0.3 for v in r2["kwtr_ly"])
