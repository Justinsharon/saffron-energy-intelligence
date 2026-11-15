# Live data year (synthetic) — generation report

Built by `tools/make_live_year.py` from data/clean/ (Oct 2025 – Sep 2026). Period 1 Oct 2026 – 30 Sep 2027, IST, start of interval. **Synthetic**; the anomaly mix comes from the full original label set, so scores on it are a robustness check, not a clean held-out test.

## 1. Tables: rows, date range, gaps, duplicates

| table | rows | from | to | duplicate keys | missing steps |
|---|---:|---|---|---:|---:|
| meter_ggn_15min | 35,040 | 2026-10-01 00:00:00 | 2027-09-30 23:45:00 | 0 | 0 |
| meter_jai_hourly | 8,760 | 2026-10-01 00:00:00 | 2027-09-30 23:00:00 | 0 | 0 |
| meter_goa_hourly | 8,760 | 2026-10-01 00:00:00 | 2027-09-30 23:00:00 | 0 | 0 |
| sub_ggn_hourly | 8,760 | 2026-10-01 00:00:00 | 2027-09-30 23:00:00 | 0 | 0 |
| sub_jai_goa_hourly | 17,520 | 2026-10-01 00:00:00 | 2027-09-30 23:00:00 | 0 | 0 |
| weather_hourly | 26,280 | 2026-10-01 00:00:00 | 2027-09-30 23:00:00 | 0 | 0 |
| occupancy_daily | 1,095 | 2026-10-01 00:00:00 | 2027-09-30 00:00:00 | 0 | 0 |
| events | 322 | 2026-10-01 00:00:00 | 2027-09-30 00:00:00 | 0 | — |
| bms_command_log | 1,345 | 2026-10-01 06:00:00 | 2027-09-30 21:00:00 | — | — |
| bms_alarm_log | 1,809 | 2026-10-01 01:28:00 | 2027-09-30 23:56:00 | 0 | — |
| monthly_bills | 36 | 2026-10 | 2027-09 | 0 | — |
| tariffs | 30 | — | — | 0 | — |
| equipment_register | 24 | — | — | 0 | — |
| meter_faults | 3 | 2027-07-21 23:00:00 | 2027-09-13 18:00:00 | — | — |
| anomaly_labels | 110 | 2026-10-04 18:00:00 | 2027-09-26 23:00:00 | 0 | — |

## 2. Energy and demand per site

| site | original kWh | live kWh | change |
|---|---:|---:|---:|
| GGN | 4,148,023 | 4,267,165 | +2.9% |
| JAI | 2,190,517 | 2,205,792 | +0.7% |
| GOA | 2,120,067 | 2,135,386 | +0.7% |

Monthly peak kVA (original year → live year, same calendar month):

| month | GGN orig | GGN live | JAI orig | JAI live | GOA orig | GOA live |
|---|---:|---:|---:|---:|---:|---:|
| Oct | 790 | 807 | 426 | 438 | 365 | 370 |
| Nov | 734 | 794 | 420 | 438 | 413 | 426 |
| Dec | 715 | 749 | 405 | 464 | 401 | 416 |
| Jan | 852 | 731 | 383 | 411 | 410 | 393 |
| Feb | 698 | 794 | 381 | 406 | 409 | 425 |
| Mar | 705 | 737 | 397 | 403 | 369 | 383 |
| Apr | 878 | 975 | 392 | 391 | 416 | 415 |
| May | 1,086 | 1,090 | 385 | 387 | 367 | 342 |
| Jun | 1,066 | 1,120 | 377 | 389 | 341 | 343 |
| Jul | 867 | 939 | 387 | 396 | 310 | 332 |
| Aug | 869 | 902 | 398 | 392 | 365 | 341 |
| Sep | 826 | 830 | 386 | 436 | 352 | 368 |

Gurugram days above 1,000 kVA: original 3, live 4 (2027-05-31 1,090 kVA, 2027-06-17 1,010 kVA, 2027-06-18 1,078 kVA, 2027-06-29 1,120 kVA).

## 3. Sub-meters vs main meter, power factor

Main ÷ sum of sub-meters, hourly, grid-only hours outside meter faults. Tolerance = the original year's largest deviation.

| site | orig p1–p99 | orig max dev (tol.) | live p1–p99 | live max dev | ok |
|---|---|---:|---|---:|---|
| GGN | 0.958–1.041 | 6.9% | 0.956–1.044 | 6.9% | yes |
| JAI | 0.991–1.010 | 1.6% | 0.990–1.010 | 1.5% | yes |
| GOA | 0.990–1.010 | 1.6% | 0.990–1.010 | 1.6% | yes |

| site | PF min | PF max | rows outside 0.85–1.0 |
|---|---:|---:|---:|
| GGN | 0.863 | 0.993 | 0 |
| JAI | 0.864 | 0.990 | 0 |
| GOA | 0.963 | 0.990 | 0 |

## 4. Bills rebuild from the meter

36 bills ({'GGN': 12, 'GOA': 12, 'JAI': 12}), 2026-10 – 2027-09, issued on the 5th of the next month. Largest gap between a bill's total and the rebuild from its meter readings: ₹0; largest tariff-line gap in `bills.reconcile_all()`: ₹14. Reconcile status: {'Reconciled': 35, 'Meter fault': 1} (the Gurugram comms-fault month is billed on the frozen readings, as in the original data). Live tariffs: every ₹ rate ×1.03, effective 1 Oct 2026.

| site | months | annual bill ₹ | max MD kVA | months with excess-demand penalty |
|---|---:|---:|---:|---:|
| GGN | 12 | 39,167,948 | 1,120 | 2 |
| GOA | 12 | 15,922,258 | 426 | 0 |
| JAI | 12 | 22,136,403 | 464 | 0 |

## 5. Injected anomalies vs original yearly rates

| site | type | injected | original rate / yr | excess kWh | excess ₹ |
|---|---|---:|---:|---:|---:|
| GGN | AHU_SCHEDULE_OVERRIDE | 16 | 16 | 23,958 | 193,940 |
| GGN | CHILLER_ON_LOW_LOAD | 13 | 13 | 43,149 | 349,248 |
| GGN | CHW_SETPOINT_LOWERED | 8 | 8 | 32,544 | 263,417 |
| GGN | CONTRACT_DEMAND_BREACH | 3 | 3 | 2,318 | 190,713 |
| GGN | EV_CHARGER_FAULT | 2 | 2 | 1,074 | 8,693 |
| GGN | KITCHEN_EXHAUST_LEFT_ON | 10 | 10 | 3,345 | 27,078 |
| GGN | LAUNDRY_PEAK_TARIFF | 12 | 12 | 0 | 3,744 |
| GGN | METER_DATA_FAULT | 1 | 3 | 0 | 0 |
| GGN | POWER_FACTOR_DROP | 2 | 2 | 0 | 208,667 |
| GGN | SIMULTANEOUS_HEAT_COOL | 9 | 9 | 21,277 | 172,220 |
| JAI | CHILLER_ON_LOW_LOAD | 6 | 6 | 5,250 | 45,988 |
| JAI | EVENT_LIGHTING_LEFT_ON | 9 | 9 | 4,730 | 41,432 |
| JAI | LAUNDRY_PEAK_TARIFF | 4 | 4 | 0 | 952 |
| JAI | METER_DATA_FAULT | 1 | 1 | 0 | 0 |
| JAI | POWER_FACTOR_DROP | 1 | 1 | 0 | 54,476 |
| GOA | CHILLER_ON_LOW_LOAD | 6 | 6 | 8,964 | 59,122 |
| GOA | LAUNDRY_PEAK_TARIFF | 3 | 3 | 0 | 474 |
| GOA | POOL_PUMPS_24H | 3 | 3 | 12,544 | 82,731 |
| GOA | METER_DATA_FAULT | 1 | 1 | 0 | 0 |

Total 110 labels (original year: 111). METER_DATA_FAULT is fixed at one per site (listed in meter_faults.parquet); every other type is injected at exactly its original yearly count, at random times (fewer only where no valid slot exists). Alarms: 1,809 (original 1,829).

- Comms fault GGN: 2027-08-13 11:00:00 – 2027-08-13 15:45:00; billed kWh frozen at 131.45 for 20 intervals while kW stays live (mean 509 kW).
- Comms fault JAI: 2027-07-21 23:00:00 – 2027-07-22 09:00:00; billed kWh frozen at 238.50 for 11 h while kW stays live (mean 223 kW).
- Comms fault GOA: 2027-09-13 18:00:00 – 2027-09-14 05:00:00; billed kWh frozen at 222.00 for 12 h while kW stays live (mean 209 kW).

## Result

Annual kWh within +0–4 %: yes; sub-meters within tolerance: yes; PF in 0.85–1.0: yes; bills within ₹200: yes. **ALL CHECKS PASS.** Files: 2.4 MB in data/live/.
