# Savings: original year and live year

The live year (Oct 2026 – Sep 2027) is **synthetic** (tools/make_live_year.py); its figures are a robustness check, not a measured result.

| Year | Operations | With one capital item (pump VFDs) | Headline |
|---|---:|---:|---|
| Original (Oct 2025 – Sep 2026) | ₹4,381,462 (5.9%) | ₹5,248,062 (7.1%) | 5.9% from operations · 7.1% with one capital item (pump VFDs) |
| Live (Oct 2026 – Sep 2027, synthetic) | ₹4,652,793 (6.0%) | ₹5,577,016 (7.2%) | 6.0% from operations · 7.2% with one capital item (pump VFDs) |

## Daily operating plan, simulated on the live year (Gurugram)

| Lever | kWh | ₹ | Category | Already counted as |
|---|---:|---:|---|---|
| Chiller sequencing to the forecast load | 43,662 | ₹362,819 | Energy | staging alerts |
| Chilled water back to 7.0 °C | 13,721 | ₹114,019 | Energy | setpoint alerts |
| Chilled water 8.0 °C on cool hours | 6,297 | ₹52,326 | Energy | CHW reset measure |
| Banquet AHUs on 1 h before / off 1 h after | 23,742 | ₹197,294 | Energy | hand-mode AHU alerts |
| Laundry out of the 18–22 peak | 0 | ₹3,848 | ToD | flexible-load shift |
| Water heating moved to 23–05 | 0 | ₹41,802 | ToD | flexible-load shift |
| Lower monthly maximum demand | 0 | ₹100,487 | Demand | breach measure (penalty months only) |
| **Plan total** | | **₹872,596** | | |

Only ₹33,564 is added to the live-year savings (the lower-demand saving in months with no excess-demand penalty billed); the rest is the same waste the alert and breach rows already count. Verified plan ₹ from approved steps (Plan vs actual) stays on the plan pages and the monthly report and is never added to this headline.
