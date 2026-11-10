# %% [markdown]
# # 08 · Contract-demand and EV-charger rules (post-hoc additions)
# Notebook 06 found two held-out label types with no rule. This notebook adds a rule for each **after the detector freeze**, in a separate module (`src/demand_ev_rules.py`);
# `src/detector.py` and the frozen alerts are untouched. Both rules are defined without labels: the demand thresholds are the engineering guide's (920 kVA EV-throttle level, 1,000 kVA
# contract demand), and the EV rule is "any draw above 1 kW between 01:00 and 05:00", where the pre-April data show exactly 0 kW on every night (there is no EV label before April).
# **Because the gaps were seen before the rules were written, the results below are post-hoc, not clean held-out.** The demand alert is reactive (it fires once 15-min demand has crossed
# 920 kVA); the predictive side is the day-ahead warning in notebook 07.

# %%
import sys
from pathlib import Path
import pandas as pd

ROOT = Path.cwd() if (Path.cwd() / "data").exists() else Path.cwd().parent
sys.path.insert(0, str(ROOT / "src"))
import demand_ev_rules as R, evaluation as E
pd.set_option("display.width", 220, "display.max_colwidth", 150)

# %%
A = R.all_additions()
display(A[["rule", "start", "end", "alert_time", "flagged_h", "cost_inr", "evidence"]])
A.to_parquet(ROOT / "data/clean/alerts_demand_ev.parquet", index=False)

# %% [markdown]
# ## Check against the answer key (diagnostic, post-hoc)
# Labels read through `E.heldout_labels_for_diagnostics()`; nothing here changes a rule.

# %%
L = E.heldout_labels_for_diagnostics()
L = L[L.anomaly_type.isin(["CONTRACT_DEMAND_BREACH", "EV_CHARGER_FAULT"])]
rows = [dict(label=r.anomaly_type, start=r.start, alerts=int(((A.site == r.site) & E._overlap(A.start, A.end, r.start, r.end)).sum())) for r in L.itertuples()]
display(pd.DataFrame(rows))
fp = sum(not E._overlap(a.start, a.end, L.start, L.end).any() for a in A.itertuples())
print(f"{len(A)} alerts over the whole year; {fp} do not overlap a label of these two types. Labels covered: {sum(r['alerts'] > 0 for r in rows)} of {len(rows)}.")

# %% [markdown]
# **Limits.** Three demand events and two EV episodes are too few to call this validated: it shows the rules are consistent with the key, with no false alerts in the year.
# The demand alert comes ~15 min after the threshold is crossed, so it informs but cannot prevent that interval's peak; prevention is the forecast's job. The ₹ shown is the tariff's
# excess-demand charge if that peak stands as the month's MD (see OPEN_QUESTIONS item 2 on whether the penalty is charged on top).
