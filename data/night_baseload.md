# Night base-load audit (00:00–05:00)

Each sub-meter channel's night draw against its own **good nights**: the 10th–20th percentile of the 30 nights with the most similar occupancy and outdoor temperature. The excess is claimed only where it **repeats** (more than half of the nights above the reference by more than the sub-meters' ±1 % accuracy), at its **median** nightly size × the night hours checked, priced at each hotel's off-peak rate. Hours already counted as alert waste, DG and meter-fault hours, the daily plan's levers and everything that must run at night are excluded (see `tools/night_baseload.py`). Recommend only: confirm each item on a night walk-round before acting.

R² is how much of the night-to-night variation occupancy and outdoor temperature explain (linear fit); the excess is what they don't.

## Original year (Oct 2025 – Sep 2026): the savings claim

### Gurugram — ₹0/yr (0.00 % of the year's bill ₹369.9 lakh)

Night price ₹7.28/kWh (off-peak, rebate applied).

| Channel | Typical night kW | Good-night kW | Excess kW (median) | Nights above ref | Night-to-night r | Occ./temp. R² | Excess kWh/yr | ₹/yr | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Unmetered 'other' | 43.9 | 42.9 | 0.00 | 68% | 0.09 | 0.01 | 0 | ₹0 | random night-to-night scatter, not a persistent excess |
| Public-area AHUs | 32.0 | 31.1 | 0.00 | 73% | -0.03 | 0.04 | 0 | ₹0 | random night-to-night scatter, not a persistent excess |
| Chiller CH-1 | 0.0 | 0.0 | 0.00 | 14% | 0.75 | 0.26 | 0 | ₹0 | excluded: chilled water for occupied rooms; staging waste counted by alerts and the daily plan |
| Chiller CH-2 | 0.0 | 0.0 | 0.00 | 0% | 0.00 | 0.00 | 0 | ₹0 | excluded: out of service; chilled water for occupied rooms |
| Chiller CH-3 | 45.5 | 43.6 | 1.76 | 77% | 0.60 | 0.00 | 0 | ₹0 | excluded: chilled water for occupied rooms; staging counted by alerts and the plan |
| CHW pumps | 15.9 | 15.2 | 0.43 | 79% | 0.60 | 0.79 | 0 | ₹0 | excluded: serve occupied rooms; constant-speed pumping is the pump-VFD capital row |
| Condenser pumps / towers | 13.6 | 12.8 | 0.45 | 80% | 0.61 | 0.79 | 0 | ₹0 | excluded: serve occupied rooms; pump-VFD capital row |
| Banquet AHUs | 0.0 | 0.0 | 0.00 | 0% | 0.00 | 0.00 | 0 | ₹0 | excluded: daily plan lever (banquet AHUs) and hand-mode alerts |
| AHU re-heat | 0.0 | 0.0 | 0.00 | 20% | 0.93 | 0.56 | 0 | ₹0 | no repeatable excess |
| Kitchen | 18.0 | 17.9 | 0.00 | 11% | 0.02 | 0.01 | 0 | ₹0 | no repeatable excess |
| Kitchen exhaust / make-up air | 0.0 | 0.0 | 0.00 | 0% | 0.00 | 0.00 | 0 | ₹0 | no repeatable excess |
| Laundry | 0.0 | 0.0 | 0.00 | 0% | 0.00 | 0.00 | 0 | ₹0 | excluded: daily plan lever (laundry timing) |
| Public lighting | 46.0 | 45.8 | 0.00 | 15% | 0.01 | 0.00 | 0 | ₹0 | no repeatable excess |
| Guest rooms (FCU / plugs) | 37.9 | 32.1 | 5.41 | 79% | 0.18 | 0.30 | 0 | ₹0 | excluded: guest rooms (never controlled) |
| Lifts | 5.0 | 5.0 | 0.00 | 12% | -0.05 | 0.01 | 0 | ₹0 | excluded: lifts (life-safety, never controlled) |
| EV chargers | 0.0 | 0.0 | 0.00 | 0% | 0.00 | 0.00 | 0 | ₹0 | excluded: daily plan lever (EV) and EV night rule |
| Water heating | 22.3 | 20.1 | 2.49 | 83% | 0.55 | 0.52 | 0 | ₹0 | excluded: daily ≥ 60 °C cycle (Legionella) and a daily plan lever |
| Pool | 8.0 | 8.0 | 0.00 | 33% | 0.71 | 0.63 | 0 | ₹0 | excluded: pool heating in winter is genuine; filtration minimum |

Without the persistence test (b) the method would have claimed ₹23,208/yr here; that difference is random night-to-night scatter around the good-night level, not waste, so it is not counted.

### Jaipur — ₹0/yr (0.00 % of the year's bill ₹214.2 lakh)

Night price ₹7.91/kWh (off-peak, rebate applied).

| Channel | Typical night kW | Good-night kW | Excess kW (median) | Nights above ref | Night-to-night r | Occ./temp. R² | Excess kWh/yr | ₹/yr | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Unmetered 'other' | 34.0 | 33.0 | 0.00 | 75% | 0.01 | 0.02 | 0 | ₹0 | random night-to-night scatter, not a persistent excess |
| Chillers | 43.4 | 41.7 | 1.32 | 77% | 0.68 | 0.71 | 0 | ₹0 | excluded: chilled water for occupied rooms; staging counted by alerts and the daily plan |
| AHUs | 20.0 | 19.9 | 0.00 | 18% | -0.05 | 0.00 | 0 | ₹0 | no repeatable excess |
| Kitchen | 14.0 | 13.9 | 0.00 | 15% | -0.02 | 0.00 | 0 | ₹0 | no repeatable excess |
| Laundry | 0.0 | 0.0 | 0.00 | 0% | 0.00 | 0.00 | 0 | ₹0 | excluded: daily plan lever (laundry timing) |
| Lighting | 34.0 | 33.9 | 0.00 | 7% | -0.08 | 0.00 | 0 | ₹0 | no repeatable excess |
| Pumps and pool | 10.0 | 10.0 | 0.00 | 14% | 0.05 | 0.01 | 0 | ₹0 | no repeatable excess |
| Guest rooms | 24.1 | 22.6 | 1.98 | 81% | 0.22 | 0.79 | 0 | ₹0 | excluded: guest rooms (never controlled) |

Without the persistence test (b) the method would have claimed ₹13,789/yr here; that difference is random night-to-night scatter around the good-night level, not waste, so it is not counted.

### Goa — ₹0/yr (0.00 % of the year's bill ₹155.9 lakh)

Night price ₹6.07/kWh (off-peak, rebate applied).

| Channel | Typical night kW | Good-night kW | Excess kW (median) | Nights above ref | Night-to-night r | Occ./temp. R² | Excess kWh/yr | ₹/yr | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Unmetered 'other' | 30.0 | 29.1 | 0.00 | 73% | -0.07 | 0.01 | 0 | ₹0 | random night-to-night scatter, not a persistent excess |
| Chillers | 47.3 | 43.9 | 2.68 | 83% | 0.56 | 0.76 | 0 | ₹0 | excluded: chilled water for occupied rooms; staging counted by alerts and the daily plan |
| AHUs | 20.0 | 19.9 | 0.00 | 12% | -0.02 | 0.02 | 0 | ₹0 | no repeatable excess |
| Kitchen | 14.0 | 13.9 | 0.00 | 12% | -0.08 | 0.01 | 0 | ₹0 | no repeatable excess |
| Laundry | 0.0 | 0.0 | 0.00 | 0% | 0.00 | 0.00 | 0 | ₹0 | excluded: daily plan lever (laundry timing) |
| Lighting | 34.0 | 33.8 | 0.00 | 11% | 0.00 | 0.02 | 0 | ₹0 | no repeatable excess |
| Pumps and pool | 10.0 | 10.0 | 0.00 | 17% | -0.06 | 0.00 | 0 | ₹0 | no repeatable excess |
| Guest rooms | 22.0 | 20.1 | 0.00 | 85% | 0.04 | 0.81 | 0 | ₹0 | excluded: guest rooms (never controlled) |

Without the persistence test (b) the method would have claimed ₹9,243/yr here; that difference is random night-to-night scatter around the good-night level, not waste, so it is not counted.

**Group: ₹0/yr, 0.00 % of the group bill (₹7.40 cr)** (without the persistence test: ₹46,240). Public-lighting kWh is added to the savings plan only beyond the existing night-lighting row (src/savings.py), so it is never counted twice.

**What it means.** No channel shows a persistent excess over its own good nights: the night base load is already as low as these hotels' best similar nights. Any further cut means a level lower than any night the meters have seen (switching areas or equipment off), which data cannot size; that is what the night walk-round below is for.

### Night walk-round checklist (02:00, all hotels)

| Area | What to check |
|---|---|
| Public-area AHUs | Check each public AHU's speed and BMS time schedule at 02:00; are back-of-house and closed outlets still served? |
| AHU re-heat | Check re-heat valve positions and AHU discharge setpoints at 02:00; is re-heat on with chilled water flowing? |
| Kitchen | Walk the kitchens after closing: hot-holding, ovens, salamanders, cold-room doors and defrost cycles |
| Kitchen exhaust / make-up air | Confirm no cooking, then check the exhaust and MUA fan status and the hood interlock |
| Public lighting | Walk the back-of-house, car park, façade and landscape at 02:00; note any area at full level |
| Unmetered 'other' | Read the unmetered distribution boards at 02:00 vs 15:00; list what draws power with nobody using it |
| Pumps and pool | Check which pumps run at 02:00 against the filtration and transfer schedules (filtration ≥ 8 h a day stays) |

### Night kW by month (all audited channels, before exclusions)

| Hotel | Month | Night kW | Occupancy | Night temp °C |
|---|---|---:|---:|---:|
| Gurugram | 2025-10 | 293 | 76% | 20.6 |
| Gurugram | 2025-11 | 285 | 75% | 15.3 |
| Gurugram | 2025-12 | 314 | 67% | 9.7 |
| Gurugram | 2026-01 | 322 | 72% | 8.5 |
| Gurugram | 2026-02 | 319 | 76% | 10.7 |
| Gurugram | 2026-03 | 283 | 73% | 17.5 |
| Gurugram | 2026-04 | 298 | 71% | 23.3 |
| Gurugram | 2026-05 | 339 | 64% | 28.9 |
| Gurugram | 2026-06 | 338 | 63% | 28.8 |
| Gurugram | 2026-07 | 348 | 70% | 28.7 |
| Gurugram | 2026-08 | 334 | 65% | 28.9 |
| Gurugram | 2026-09 | 323 | 73% | 25.7 |
| Jaipur | 2025-10 | 182 | 77% | 20.0 |
| Jaipur | 2025-11 | 182 | 90% | 16.5 |
| Jaipur | 2025-12 | 184 | 96% | 10.7 |
| Jaipur | 2026-01 | 182 | 92% | 9.0 |
| Jaipur | 2026-02 | 182 | 90% | 12.3 |
| Jaipur | 2026-03 | 179 | 82% | 15.6 |
| Jaipur | 2026-04 | 178 | 56% | 22.4 |
| Jaipur | 2026-05 | 184 | 47% | 27.5 |
| Jaipur | 2026-06 | 184 | 44% | 28.3 |
| Jaipur | 2026-07 | 190 | 48% | 27.1 |
| Jaipur | 2026-08 | 193 | 52% | 27.0 |
| Jaipur | 2026-09 | 192 | 61% | 25.0 |
| Goa | 2025-10 | 179 | 64% | 24.3 |
| Goa | 2025-11 | 187 | 82% | 24.7 |
| Goa | 2025-12 | 186 | 96% | 22.9 |
| Goa | 2026-01 | 174 | 92% | 20.7 |
| Goa | 2026-02 | 179 | 87% | 23.3 |
| Goa | 2026-03 | 173 | 78% | 22.5 |
| Goa | 2026-04 | 178 | 71% | 25.4 |
| Goa | 2026-05 | 183 | 65% | 28.3 |
| Goa | 2026-06 | 169 | 41% | 25.8 |
| Goa | 2026-07 | 167 | 38% | 25.1 |
| Goa | 2026-08 | 169 | 43% | 25.0 |
| Goa | 2026-09 | 173 | 53% | 24.1 |

## Live year (Oct 2026 – Sep 2027, synthetic): a check, not a claim

Same method on the live year: ₹105,849/yr, 0.14 % of its bill (₹7.72 cr). The live year is built from copied weeks of the original year with a steady load-growth factor (tools/make_live_year.py), which makes neighbouring nights alike: that is where most of its night-to-night persistence comes from, so a live-year excess is a property of the generator, not evidence of waste.

### Gurugram — ₹51,649/yr (0.13 % of the year's bill ₹391.7 lakh)

Night price ₹7.50/kWh (off-peak, rebate applied).

| Channel | Typical night kW | Good-night kW | Excess kW (median) | Nights above ref | Night-to-night r | Occ./temp. R² | Excess kWh/yr | ₹/yr | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Unmetered 'other' | 44.6 | 43.0 | 1.42 | 76% | 0.32 | 0.00 | 2,398 | ₹17,984 | clear repeatable excess |
| Public-area AHUs | 32.5 | 31.3 | 1.23 | 78% | 0.17 | 0.01 | 1,877 | ₹14,076 | clear repeatable excess |
| Public lighting | 46.7 | 45.6 | 1.11 | 72% | 0.58 | 0.01 | 1,869 | ₹14,016 | clear repeatable excess |
| Kitchen | 18.3 | 17.8 | 0.44 | 74% | 0.60 | 0.01 | 743 | ₹5,573 | clear repeatable excess |
| Chiller CH-1 | 0.0 | 0.0 | 0.00 | 24% | 0.51 | 0.24 | 0 | ₹0 | excluded: chilled water for occupied rooms; staging waste counted by alerts and the daily plan |
| Chiller CH-2 | 0.0 | 0.0 | 0.00 | 0% | 0.00 | 0.00 | 0 | ₹0 | excluded: out of service; chilled water for occupied rooms |
| Chiller CH-3 | 46.2 | 41.1 | 4.37 | 86% | 0.67 | 0.05 | 0 | ₹0 | excluded: chilled water for occupied rooms; staging counted by alerts and the plan |
| CHW pumps | 17.1 | 16.3 | 0.73 | 80% | 0.70 | 0.77 | 0 | ₹0 | excluded: serve occupied rooms; constant-speed pumping is the pump-VFD capital row |
| Condenser pumps / towers | 14.8 | 14.3 | 0.73 | 80% | 0.72 | 0.78 | 0 | ₹0 | excluded: serve occupied rooms; pump-VFD capital row |
| Banquet AHUs | 0.0 | 0.0 | 0.00 | 1% | 0.70 | 0.02 | 0 | ₹0 | excluded: daily plan lever (banquet AHUs) and hand-mode alerts |
| AHU re-heat | 0.0 | 0.0 | 0.00 | 12% | 0.85 | 0.39 | 0 | ₹0 | no repeatable excess |
| Kitchen exhaust / make-up air | 0.0 | 0.0 | 0.00 | 0% | 0.00 | 0.00 | 0 | ₹0 | no repeatable excess |
| Laundry | 0.0 | 0.0 | 0.00 | 0% | 0.00 | 0.00 | 0 | ₹0 | excluded: daily plan lever (laundry timing) |
| Guest rooms (FCU / plugs) | 39.1 | 33.2 | 5.16 | 80% | 0.29 | 0.29 | 0 | ₹0 | excluded: guest rooms (never controlled) |
| Lifts | 5.1 | 4.9 | 0.13 | 76% | 0.59 | 0.01 | 0 | ₹0 | excluded: lifts (life-safety, never controlled) |
| EV chargers | 0.0 | 0.0 | 0.00 | 0% | 0.00 | 0.01 | 0 | ₹0 | excluded: daily plan lever (EV) and EV night rule |
| Water heating | 22.4 | 19.7 | 2.50 | 83% | 0.64 | 0.43 | 0 | ₹0 | excluded: daily ≥ 60 °C cycle (Legionella) and a daily plan lever |
| Pool | 8.2 | 7.9 | 0.25 | 77% | 0.98 | 0.46 | 0 | ₹0 | excluded: pool heating in winter is genuine; filtration minimum |

### Jaipur — ₹37,519/yr (0.17 % of the year's bill ₹221.4 lakh)

Night price ₹8.15/kWh (off-peak, rebate applied).

| Channel | Typical night kW | Good-night kW | Excess kW (median) | Nights above ref | Night-to-night r | Occ./temp. R² | Excess kWh/yr | ₹/yr | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Unmetered 'other' | 34.3 | 33.2 | 1.12 | 77% | 0.15 | 0.03 | 1,963 | ₹16,000 | clear repeatable excess |
| Lighting | 34.3 | 33.6 | 0.77 | 70% | 0.36 | 0.00 | 1,007 | ₹8,210 | clear repeatable excess |
| AHUs | 20.2 | 19.8 | 0.42 | 69% | 0.45 | 0.01 | 736 | ₹6,000 | clear repeatable excess |
| Kitchen | 14.1 | 13.9 | 0.31 | 70% | 0.41 | 0.00 | 535 | ₹4,357 | clear repeatable excess |
| Pumps and pool | 10.1 | 9.9 | 0.21 | 67% | 0.49 | 0.01 | 362 | ₹2,952 | clear repeatable excess |
| Chillers | 47.5 | 43.9 | 3.43 | 81% | 0.68 | 0.69 | 0 | ₹0 | excluded: chilled water for occupied rooms; staging counted by alerts and the daily plan |
| Laundry | 0.0 | 0.0 | 0.00 | 0% | 0.00 | 0.00 | 0 | ₹0 | excluded: daily plan lever (laundry timing) |
| Guest rooms | 24.0 | 20.6 | 2.14 | 82% | 0.23 | 0.74 | 0 | ₹0 | excluded: guest rooms (never controlled) |

### Goa — ₹16,681/yr (0.10 % of the year's bill ₹159.2 lakh)

Night price ₹6.19/kWh (off-peak, rebate applied).

| Channel | Typical night kW | Good-night kW | Excess kW (median) | Nights above ref | Night-to-night r | Occ./temp. R² | Excess kWh/yr | ₹/yr | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Lighting | 34.4 | 33.7 | 0.75 | 71% | 0.40 | 0.02 | 1,136 | ₹7,035 | clear repeatable excess |
| AHUs | 20.2 | 19.8 | 0.40 | 71% | 0.42 | 0.00 | 719 | ₹4,450 | clear repeatable excess |
| Kitchen | 14.2 | 13.9 | 0.30 | 72% | 0.45 | 0.02 | 539 | ₹3,337 | clear repeatable excess |
| Pumps and pool | 10.1 | 9.9 | 0.20 | 73% | 0.46 | 0.04 | 300 | ₹1,859 | clear repeatable excess |
| Unmetered 'other' | 30.4 | 29.2 | 0.00 | 76% | -0.03 | 0.02 | 0 | ₹0 | random night-to-night scatter, not a persistent excess |
| Chillers | 48.0 | 43.9 | 3.48 | 79% | 0.53 | 0.71 | 0 | ₹0 | excluded: chilled water for occupied rooms; staging counted by alerts and the daily plan |
| Laundry | 0.0 | 0.0 | 0.00 | 0% | 0.00 | 0.00 | 0 | ₹0 | excluded: daily plan lever (laundry timing) |
| Guest rooms | 22.7 | 20.5 | 0.00 | 85% | 0.09 | 0.77 | 0 | ₹0 | excluded: guest rooms (never controlled) |

Without the persistence test (b) the method would have claimed ₹28,584/yr here; that difference is random night-to-night scatter around the good-night level, not waste, so it is not counted.

