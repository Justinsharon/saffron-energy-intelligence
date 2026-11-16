"""Night base-load audit (tools/night_baseload.py): a persistent excess is claimed, random scatter is not, must-run channels never are, and the
savings rows (src/savings.py) carry exactly the audit's claim. Run: uv run pytest tests
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]
import night_baseload as NB  # noqa: E402


def _nights(values, seed=0):
    rng = np.random.default_rng(seed)
    n = len(values)
    return pd.DataFrame(dict(kw=values, occupancy_pct=rng.uniform(0.5, 0.9, n), temp=rng.uniform(10, 30, n)),
                        index=pd.date_range("2025-10-01", periods=n))


def _judge(x):
    """The audit's rule on one channel's nightly series: (claimed?, median excess)."""
    x = x.assign(ref=NB.good_night(x, "kw"))
    ex = x.kw - x.ref
    share = (ex > NB.METER_TOL * x.ref).mean()
    ac1 = ex.autocorr(1)
    return bool(share > 0.5 and ex.median() > 0 and ac1 > 2 / np.sqrt(len(x))), float(ex.median())


def test_random_scatter_is_not_claimed():
    rng = np.random.default_rng(1)
    claimed, med = _judge(_nights(40 + rng.normal(0, 1.0, 365)))
    assert not claimed and med > 0                           # the median sits above the 15th percentile, but it does not persist


def test_persistent_excess_is_claimed():
    rng = np.random.default_rng(2)
    v = 40 + rng.normal(0, 0.3, 365)
    v[60:300] += 3.0                                         # e.g. an AHU left on day speed for eight months
    claimed, med = _judge(_nights(v))
    assert claimed and 1.0 < med < 3.5


def test_must_run_channels_never_claimed_and_original_year_result():
    a = NB.audit(NB.ORIG)
    for s, x in a.items():
        t = x["table"]
        for c in ("rooms_fcu_plug_kw", "lifts_kw", "water_heating_kw", "rooms_kw", "chillers_kw", "chw_pumps_kw"):
            if c in set(t.channel):
                r = t[t.channel == c].iloc[0]
                assert r.inr == 0 and r.status.startswith("excluded")
        assert (t.inr >= 0).all() and x["rate"] > 0
        assert (t.loose_inr >= t.inr).all()                  # the persistence test only ever removes ₹


def test_savings_rows_match_the_audit():
    import savings
    p = savings.plan()
    night = p[p.category == savings.NIGHT]
    for s, x in savings.night_audit()["orig"].items():
        t = x["table"]
        claimed = t[t.kwh > 0]
        assert len(night[night.site == s]) <= len(claimed)  # lighting may be netted against the night-lighting row
        assert night[night.site == s].inr.sum() <= claimed.inr.sum() + 1e-6
    assert (night.confidence == "Medium (needs a night walk-round to confirm)").all()
