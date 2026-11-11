# UI handoff — Saffron Suites Energy Intelligence (PS-12, Team 12)

Written 11 Nov 2026 to start a dedicated UI chat. Read with `CLAUDE.md` (working rules) and `CONTEXT.md` (brief, tests, findings).

## 1. Where things stand

- **Live app:** https://saffron-energy-intelligence-kuzpz2jw5we8g56ypzm3hx.streamlit.app (Streamlit Community Cloud, public, no login).
- **Repo:** https://github.com/Justinsharon/saffron-energy-intelligence (`main`). Local clone on Justin's PC: `C:\Users\justi\Downloads\Applied-AI-Challenge\saffron-energy-intelligence`.
- **Push route:** GitHub is not linked to Claude on claude.ai, so cloud sessions hand over a git bundle and Justin cherry-picks and pushes from his PC (or his local Claude Code). Linking GitHub in claude.ai settings would let a session push directly.
- **Secrets on Streamlit Cloud:** `ANTHROPIC_API_KEY`, `GITHUB_TOKEN` (gist scope), `RATINGS_GIST_ID`.
- **Deadlines:** Check-in 2 (MVP online + one-page note) **12 Nov**; internal auction **16 Nov**; final auction **18 Nov**.
- **Check-in 2 note:** a Claude doc, "PS-12 Check-in 2 — Saffron Suites Energy Intelligence", plus a PDF in the project folder.

### Results to show in the UI (all verified 10–11 Nov)
| Item | Value |
|---|---|
| Acceptance tests T1–T10 | 10/10 pass. T1 is at its limit (2.0 h, target ≤ 2 h); T7 passes through a post-hoc risk layer |
| Precision (held-out, frozen detector) | 98.1% (strict type match 96.2%); BMS today 26% |
| Recall, High + Medium | 95.7% (44/46); BMS today 40% |
| Time to detect, High | 1.0 h median from first appearance in the data |
| Baseline CV(RMSE) hourly / monthly | GGN 8.3 / 3.4%, JAI 5.0 / 1.1%, GOA 5.4 / 2.8%; NMBE within ±0.1% |
| Day-ahead peak (GGN) | MAPE 5.4%, 59% of days within ±5% |
| Identified savings | ₹43.8 L/yr = 5.9% of the ₹7.40 cr bill; 7.1% with the pump-VFD capital note; target 8–12% |
| Engineer trust | AI dry run 3.73/5 (labelled as AI, round 1); real raters still needed |

## 2. Who we are building for (from the brief)
| User | Moment of use | What they need to see first | Must not see |
|---|---|---|---|
| **Duty engineer** (on shift, often night) | An alert arrives; 2 a.m. | What, where, since when, ₹/day, one action, evidence; acknowledge / snooze with reason | Noise: small items go to the daily digest |
| **Chief engineer** | Weekly review | Recurring faults, kW/TR, setpoint changes, which rules fire most, baseline vs actual | — |
| **General manager** | Monthly | Cost drivers: why the bill moved (weather vs occupancy vs events vs waste vs demand), ₹ at stake | Engineering detail by default |
| **Group finance controller** | Monthly / quarterly | Bill reconciliation by line, provisional and meter-fault months, savings against an adjusted baseline (IPMVP Option C) with uncertainty | Savings claimed against last year's bill |

## 3. Must-have / should-have → where it lives in the UI today
| Requirement (brief) | Status | Current screen | Gap for the UI work |
|---|---|---|---|
| M1 Per-hotel baseline with CV(RMSE)/NMBE | Built | Savings (Option C panel), Method | No per-hotel "health" view; numbers buried |
| M2 Context-aware detection | Built | Alerts | List + radio picker; no timeline/heatmap of the year |
| M3 Root cause with evidence | Built | Alert card + 2 Plotly charts | Evidence charts plain; no annotation of the event or BMS change on the chart |
| M4 Duty-engineer alerts (what/where/since/₹/action) | Built | Alerts, Overview "Open now" | Not phone-friendly; no shift view; ack/snooze log is session-only |
| M5 Meter faults suppressed | Built | Alerts → Data faults tab | Fine as a tab; could be a badge on the hotel card |
| M6 Bill reconciliation + provisional flag | Built | Bills | Wide table; needs status chips and a per-month drill-down |
| M7 Public URL | Built | Streamlit Cloud | Cold start ~30 s |
| S1 Next-day load + peak forecast, 1,000 kVA warning | Built | Forecast | Good content; layout is metric row + chart + table |
| S2 Flexible-load shifting | Built | Forecast shift plan | Plan table only; no "before/after" peak picture |
| S3 IPMVP Option C savings (kWh and ₹) | Partly | Savings | Measures table is long and wide; needs a bridge/waterfall to the target |
| S4 Conversational assistant | Built (Claude + tools + number check) | Assistant | Works; style is default chat |
| Stretch: control simulation, benchmarking, auto GM report | Not built | — | Candidates if time allows |

## 4. Current UI: honest assessment
`app.py` is default Streamlit: sidebar radio of 8 pages, metric rows, `st.dataframe` tables, Plotly charts with basic styling, no brand, no hierarchy by role, weak on mobile (sidebar collapses; wide tables scroll). It proves the product works but does not look like a product an engineer or GM would open daily.

## 5. Goals for the UI work
1. **Role-first navigation:** the start screen depends on who you are (Shift / Engineering / GM / Finance), each a short page with its top 3 answers.
2. **The alert card is the hero:** brief §13 format, severity colour, ₹, one action, evidence chart annotated (event end, BMS change, fault window), ack/snooze/rate inline, readable on a phone.
3. **Portfolio at a glance:** three hotel cards (status, open alerts, ₹ at stake, this month vs baseline), then drill-down.
4. **Money views that finance trusts:** bill by component, reconciliation chips (Reconciled / Meter fault / Provisional), "why did the bill change" waterfall, savings bridge from today to the 8–12% target, with confidence labels.
5. **Forecast as a decision:** tomorrow's risk badge, the peak curve against 920 / 1,000 kVA, and the shift plan shown as before/after.
6. **Trust built in:** every number traceable (tooltip / "data used"), post-hoc items labelled, guardrails visible.

## 6. Constraints the UI must keep
- Recommend, never control; guardrail text on every action; kitchen exhaust, guest-room thermostats, lifts, life-safety never automated.
- Every alert shows evidence; meter faults never appear as waste or savings; bills never altered.
- LLM text only states numbers from the models (the assistant's number check stays).
- Data comes from `data/app/*.parquet` (built by `src/build_app_data.py`) and `data/clean/`; no new numbers invented in the UI.
- Synthetic data, fictional company, illustrative tariffs — say so in the footer.
- Hosting: free tier, cold start; keep first paint fast (precomputed data, cached loaders).

## 7. Decision to make first in the UI chat
- **A. Stay on Streamlit, redesign:** custom theme, CSS, `st.navigation` with role pages, styled HTML cards, better Plotly templates. Lowest risk for 12 Nov; limited polish.
- **B. Rebuild the front end** (e.g. React/Next.js or a static app reading exported JSON, with the Python models behind a small API or pre-exported data). Best polish; more hosting and time risk before 16/18 Nov.
- Suggested: A for Check-in 2 (12 Nov) if anything ships that soon; decide on B for the 16/18 Nov auctions after a mock-up review.

## 8. Other open items (not UI)
- T1 margin: an events-calendar AHU rule (post-hoc) would fire before 2.0 h.
- Real engineer ratings (round 2) on the **Rate alerts** page; delete the `TEST-Claude` row in the gist.
- Savings: 5.9% → 7.1% with pump VFDs (capital note); 8% needs a base-load audit and capital items.
- Pitch deck and value case for 16 and 18 Nov.

## 9. Code map (UI-relevant)
| File | What it gives the UI |
|---|---|
| `app.py` | Current Streamlit app (all pages) |
| `src/build_app_data.py` | Precomputes `data/app/*.parquet` (frames per hotel, cards, faults, bill reconciliation) |
| `src/alert_cards.py` | Card fields: title, severity, equipment, cause, action, guardrail, cost basis, channel, repeats, chart columns |
| `src/bills.py`, `src/attribution.py` | Bill lines, reconciliation status, bill-change waterfall |
| `src/forecast_app.py`, `src/peak_risk.py` | Day view, what-if, risk level, P(>1,000), stacking scenario, shift plan |
| `src/savings.py` | Measures table (category, ₹, basis, safety, confidence), Option C stats |
| `src/assistant.py` | Claude tool-use assistant with guard + number check |
| `src/feedback.py` | Frozen 20-alert rating set, Gist storage, summaries by round |
| `tools/acceptance.py` | T1–T10 check (run after any change) |
