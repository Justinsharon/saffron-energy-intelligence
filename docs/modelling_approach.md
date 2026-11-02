# Modelling approach — discussion notes (PS-12 Energy Optimisation)

Design discussion on which models to use for each component. Constraints come from `CLAUDE.md` / `CONTEXT.md`: about a year of hourly data per hotel (~8.7k rows), explainable alerts with evidence, all numbers from models (LLM only words them), no label leakage (tune on anomalies starting before 1 Apr 2026, report on those from 1 Apr 2026).

Guiding principle: with this little data, prefer interpretable, well-regularised models. Skip deep learning (autoencoders, LSTMs, Transformers): they overfit one year of data and explain themselves poorly.

---

## 1. Model per component

| Component | Recommended model | Why |
|---|---|---|
| Per-hotel baseline | LightGBM on hour, day of week, cooling degree hours, occupancy and event flags, plus a TOWT-style regression (time-of-week × piecewise temperature) as a transparent benchmark | Graded on CV(RMSE)/NMBE on held-out months. The linear model is easy to defend; the GBM captures non-linear weather and occupancy interactions. |
| Load and peak forecast | LightGBM quantile regression (P50/P90); kVA peak as a separate target | Peaks drive demand charges, so an upper quantile is needed. |
| Context-aware anomaly detection | Baseline residuals scored with a robust z-score (MAD), plus CUSUM/EWMA for slow drift | Context-aware by construction. Explained deviations never alert, and the evidence is easy to show. |
| Waste-type classification | Rules on distinct signatures, with a small classifier for the ambiguous remainder | The waste types are physically distinct. |
| Meter-fault suppression (T5) | Rules plus a sub-meter consistency check (`exclude_from_model`, `kw_avg` vs billed kWh) | These are data errors, not anomalies to model. |
| Bill reconciliation | Deterministic arithmetic with tariff and ToD logic. No ML. | Auditable. |
| IPMVP Option C savings | The same baseline as an adjusted baseline, with bootstrapped uncertainty | One baseline for detection and savings keeps the numbers consistent. |
| Alert and explanation text | Claude: Haiku 5.5 for templated alert wording, Sonnet 5.5 for engineer Q&A and the T10 refusal | The model gets structured facts and numbers from the models above. A post-check verifies that every number in the output appears in the input. |

Isolation Forest is acceptable as a secondary signal but should not drive alerts.

---

## 2. Does hyperparameter tuning help?

Modestly, and only if done carefully. With ~8.7k rows per hotel, tuning can hurt more than it helps.

**What matters more than tuning**
- Features: cooling degree hours, occupancy, event flags, hour × day-of-week and ToD-aware features. These can move CV(RMSE) by 5–15 points; tuning typically adds 1–3.
- Honest validation: the data is autocorrelated and covers one seasonal cycle, so use blocked or rolling-origin CV by month, not random K-fold.
- Constraints and exclusions: monotonic constraints on temperature, plus honouring `exclude_from_model` and `is_imputed`.

**Risks:** a wide search overfits the validation months, and any season appears only once.

**Plan**
1. Start from strong regularised defaults: small `num_leaves` (8–16), `min_child_samples` ~50–100, `learning_rate` 0.03–0.05 with early stopping, L2 regularisation, monotonic temperature constraint.
2. Tune only `num_leaves`, `min_child_samples` and `n_estimators`, on a small grid or ~30 Optuna trials, using rolling-origin CV.
3. If tuned beats default by less than the fold-to-fold spread, keep the defaults.
4. Don't tune TOWT. Set the temperature breakpoints and week-bucket structure from physics and the EDA.
5. Don't tune the detector thresholds until the baseline is settled. Tune them only on the pre-April label window.

---

## 3. How LightGBM helps anomaly detection (without being a classifier)

The regressor defines "normal"; the flag comes from comparing actual load to it.

1. Train LightGBM to predict expected kWh (or kVA) per hour from weather, occupancy, events, hour and day of week.
2. Compute the residual (actual minus predicted).
3. Score it relative to normal spread: robust z-score (MAD), or CUSUM/EWMA for slow drift.
4. Flag hours where the score stays high for several hours, and only where weather, occupancy and events don't already explain it.

**Why not a classifier as the main detector**
- Few labels, and the pre-April tuning window is smaller still, so a classifier overfits.
- Heavy class imbalance.
- It only detects patterns it was trained on. Residual scoring catches any deviation, including unlabelled waste types.
- Every alert must show evidence. "38 kWh above the weather- and occupancy-adjusted baseline for 4 hours" is easy to show; a classifier probability is not.

**Where a classifier fits**
- Second stage, on flagged events only, to name the waste type from residual features (size, duration, hour of day, which sub-meter deviated, CHW setpoint, PF).
- Tuning alert thresholds (z-score cut-off and persistence window) on the pre-April anomalies, then reporting precision and recall on those from 1 Apr 2026.

---

## 4. Concrete choices

**Regressor (baseline)**
- Primary: LightGBM regressor, L2 objective (Huber if outliers inflate the residual spread), small trees, strong regularisation, monotonic temperature constraint. One model per hotel, because tariffs, ToD windows and load shapes differ.
- Benchmark: TOWT-style regularised linear regression (`Ridge` or `statsmodels` OLS) on time-of-week dummies and piecewise-linear cooling degree hours with 2–3 breakpoints.
- Peak forecast: LightGBM with `objective="quantile"` at P50 and P90.
- Pick the winner per hotel on rolling-origin CV by month. If LightGBM only ties TOWT, use TOWT for the detector, since its residuals are easier to explain.

**Classifier (waste type, second stage)**
- First, rules for the distinct signatures: CHW setpoint at 5.5 °C, DG running, PF drops, off-hours load.
- For the ambiguous remainder, a small LightGBM classifier with `class_weight="balanced"`, shallow trees (`num_leaves` 4–8) and a high `min_child_samples`. Inputs: residual size, duration, hour of day, sub-meter deviations, setpoints, PF.
- Fallback if labels are very thin: `LogisticRegression` or a shallow `DecisionTreeClassifier`. A decision tree's splits can be shown as evidence.
- Train and tune only on anomalies starting before 1 Apr 2026. Report precision, recall and per-class results on those from 1 Apr 2026.

---

## 5. Suggested next step

Build the TOWT and LightGBM baselines per hotel, compare them on held-out months with CV(RMSE) and NMBE, and pick the winner per site. The forecast, detector and savings calculation all reuse that baseline.
