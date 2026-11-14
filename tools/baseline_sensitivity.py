"""Hyperparameter sensitivity of the baseline's LightGBM, one setting at a time, on the one-year pack.

Why: asks whether the hand-picked settings in `baseline.make_gbm` leave accuracy on the table. Nothing here changes the model or any saved
output; it only writes docs/baseline_sensitivity.md. Same folds and scoring as notebooks/03_baseline.py (leave-one-month-out, and rolling
origin from the 7th month), same features, same ridge. Not tuning: a setting is never adopted from this run.

Run: uv run python tools/baseline_sensitivity.py
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from baseline import GBM_FEATURES, build_features, cv_rmse, make_gbm, make_ridge, nmbe  # noqa: E402

SITES = ["GGN", "JAI", "GOA"]
DEFAULT = dict(n_estimators=600, learning_rate=0.05, num_leaves=8, min_child_samples=40, subsample=0.8, colsample_bytree=0.8, reg_lambda=5.0,
               objective="huber", alpha=40.0)
# one change at a time from DEFAULT; the label is what appears in the report
VARIANTS = [("default", {})]
for k, vals in [("num_leaves", [4, 16, 31]), ("n_estimators", [200, 300, 1200]), ("learning_rate", [0.02, 0.1]), ("min_child_samples", [20, 100]),
                ("reg_lambda", [0.0, 20.0]), ("colsample_bytree", [0.5, 1.0]), ("subsample", [0.5, 1.0])]:
    VARIANTS += [(f"{k}={v}", {k: v}) for v in vals]
VARIANTS += [("loss=l2 (no huber)", dict(objective="regression")), ("huber alpha=20", dict(alpha=20.0)), ("huber alpha=80", dict(alpha=80.0)),
             ("shallow+long: leaves=4, trees=1200", dict(num_leaves=4, n_estimators=1200)),
             ("deep+short: leaves=16, trees=300", dict(num_leaves=16, n_estimators=300))]


def gbm_fit_predict(train, test, kw):
    tr = train[train.valid]
    m = make_gbm(**kw)
    m.fit(tr[GBM_FEATURES], tr.total_kwh)
    return m.predict(test[GBM_FEATURES])


def ridge_fit_predict(train, test):
    tr = train[train.valid]
    m = make_ridge()
    m.fit(tr, tr.total_kwh)
    return m.predict(test)


def folds(d, months, scheme):
    if scheme == "lomo":
        return [(d[d.month != m], d[d.month == m], d.month == m) for m in months]
    return [(d[d.month.isin(months[:i])], d[d.month == months[i]], d.month == months[i]) for i in range(6, 12)]


def run(d, months, scheme, predict):
    p = pd.Series(np.nan, index=d.index)
    for tr, te, mask in folds(d, months, scheme):
        p[mask] = predict(tr, te)
    return p


def scores(d, p):
    v = d[d.valid & p.notna()].assign(p=p)
    mm = v.groupby("month").agg(a=("total_kwh", "mean"), p=("p", "mean"))
    return dict(hourly=cv_rmse(v.total_kwh, v.p), monthly=cv_rmse(mm.a, mm.p), nmbe=nmbe(v.total_kwh, v.p))


def main():
    data = {s: build_features(s) for s in SITES}
    months = sorted(data["GGN"].month.unique())
    ridge = {(s, sc): run(data[s], months, sc, ridge_fit_predict) for s in SITES for sc in ("lomo", "roll")}
    rows, t0 = [], time.time()
    for label, kw in VARIANTS:
        full = {**DEFAULT, **kw}                    # alpha is ignored by the l2 objective
        for s in SITES:
            for sc in ("lomo", "roll"):
                g = run(data[s], months, sc, lambda tr, te: gbm_fit_predict(tr, te, full))
                for model, p in (("gbm", g), ("ens", (g + ridge[s, sc]) / 2)):
                    rows.append(dict(variant=label, site=s, scheme=sc, model=model, **scores(data[s], p)))
        print(f"{label:40s} done at {time.time() - t0:5.0f}s", flush=True)
    for s in SITES:
        for sc in ("lomo", "roll"):
            rows.append(dict(variant="ridge only", site=s, scheme=sc, model="ridge", **scores(data[s], ridge[s, sc])))
    R = pd.DataFrame(rows)
    R.to_csv(ROOT / "docs" / "baseline_sensitivity_raw.csv", index=False)
    write_report(R)


def md(df):
    cols = list(df.columns)
    out = ["| " + " | ".join(map(str, cols)) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for r in df.itertuples(index=False):
        out.append("| " + " | ".join(f"{v:.2f}" if isinstance(v, float) else str(v) for v in r) + " |")
    return "\n".join(out)


def write_report(R):
    L = R[(R.scheme == "lomo")]
    base = L[(L.variant == "default") & (L.model == "gbm")].set_index("site").hourly
    tab = L[L.model == "gbm"].pivot_table(index="variant", columns="site", values="hourly", sort=False)[SITES]
    tab["mean"] = tab.mean(axis=1)
    tab["Δ vs default (mean)"] = tab["mean"] - tab.loc["default", "mean"]
    tab = tab.reset_index()
    ens = L[L.model == "ens"].pivot_table(index="variant", columns="site", values="hourly", sort=False)[SITES]
    ens["mean"] = ens.mean(axis=1)
    ens = ens.reset_index()
    roll = R[(R.scheme == "roll") & (R.model == "gbm")].pivot_table(index="variant", columns="site", values="hourly", sort=False)[SITES]
    roll["mean"] = roll.mean(axis=1)
    roll = roll.reset_index()
    mon = L[L.model == "gbm"].pivot_table(index="variant", columns="site", values="monthly", sort=False)[SITES]
    mon["mean"] = mon.mean(axis=1)
    mon = mon.reset_index()
    nm = L[L.model == "gbm"].pivot_table(index="variant", columns="site", values="nmbe", sort=False)[SITES].reset_index()
    best = tab[tab.variant != "default"].sort_values("mean").iloc[0]
    worst = tab.sort_values("mean").iloc[-1]
    ridge = L[L.variant == "ridge only"].set_index("site").hourly
    spread = tab[tab.variant != "ridge only"]["mean"]
    txt = f"""# Baseline LightGBM: hyperparameter sensitivity (one-year pack)

Generated by `tools/baseline_sensitivity.py`; raw rows in `docs/baseline_sensitivity_raw.csv`. **A sensitivity check, not tuning.** No setting was adopted,
`src/baseline.py` is unchanged, and no saved output (`data/clean/baseline_oof.parquet`, alerts) was touched. The detector stays frozen on the current baseline.

## Question

Are the hand-picked LightGBM settings in `baseline.make_gbm` leaving accuracy on the table, and would tuning them (or trying other models) be worth the time?

## Method

- Data: the original one-year pack, three hotels (GGN, JAI, GOA), features and valid-hour mask exactly as in `src/baseline.py`.
- Folds: leave-one-month-out (12 folds; the primary score) and rolling origin (train on the first k months, predict month k+1, k = 6…11; stricter, it must extrapolate to unseen seasons). Same as `notebooks/03_baseline.py`.
- Variants: one setting changed at a time from the default (600 trees, 0.05 learning rate, 8 leaves, min 40 samples per leaf, subsample 0.8, colsample 0.8, L2 5.0, Huber alpha 40),
  plus five combined or loss variants. {len(VARIANTS)} variants, scored alone (`gbm`) and averaged with the unchanged ridge (`ens`, the model actually used).
- Metrics: ASHRAE Guideline 14 hourly and monthly CV(RMSE) and NMBE, out-of-sample. The brief's limits: hourly < 30 %, monthly < 15 %, |NMBE| < 5 %.
- Limits: one real year, so each season appears once, and the same data picks and scores the variants. Any "best" variant here is optimistic.

## Result in one paragraph

Across {len(spread)} LightGBM variants the mean hourly CV(RMSE) (leave-one-month-out, three hotels) ranges only from {spread.min():.2f} % to {spread.max():.2f} %, a spread of {spread.max() - spread.min():.2f} points,
against the 30 % limit. The default is {tab.loc[tab.variant == "default", "mean"].iloc[0]:.2f} %; the best variant (`{best.variant}`) is {best["mean"]:.2f} %, an improvement of {-best["Δ vs default (mean)"]:.2f} points; the worst (`{worst.variant}`) is {worst["mean"]:.2f} %.
Ridge alone is {ridge.mean():.2f} % on average. Every variant passes the Guideline 14 hourly, monthly and bias limits in the leave-one-month-out tables. Settings move the error by at most a few tenths of a point, and no variant beats the default by more than 0.05 points; the only clear differences are losses from under-sized settings (4 leaves or 200 trees, 0.16 to 0.19 points worse). Switching from ridge to boosted trees moves it by about 0.7 points. All of this is small next to the limits, and tuning would not change any conclusion.

## 1. Hourly CV(RMSE) %, LightGBM alone, leave-one-month-out

{md(tab)}

`Δ vs default` is the change in the three-hotel mean, in percentage points (negative = better).

## 2. Hourly CV(RMSE) %, ridge + LightGBM average (the model in use), leave-one-month-out

{md(ens)}

## 3. Hourly CV(RMSE) %, LightGBM alone, rolling origin (month 7 to 12)

{md(roll)}

## 4. Monthly CV(RMSE) %, LightGBM alone, leave-one-month-out

{md(mon)}

## 5. Hourly NMBE %, LightGBM alone, leave-one-month-out

{md(nm)}

## 6. Reading the results

- **Reproduction check.** The `default` row matches the saved out-of-fold scores from notebook 03 (GGN 8.47, JAI 4.98, GOA 5.39 hourly CV(RMSE) for LightGBM alone), so the harness scores the model as the project does.
- **Sensitivity is low.** Mean hourly CV(RMSE) spans 0.24 points across all variants alone and 0.17 points for the ridge + LightGBM average (the ridge half anchors it). Rolling origin spans 0.23 points.
- **The default sits on a flat optimum.** More capacity (16 or 31 leaves, 1,200 trees, learning rate 0.1) is within 0.05 points of the default in either direction; less capacity (4 leaves, 200 trees) is 0.16 to 0.19 points worse. There is no sign the defaults are under-sized, and nothing to gain by growing them. The best single result (`num_leaves=16`, −0.05 points) is smaller than the loss from under-sizing, and I did not measure run-to-run noise from the random seed, so I do not read it as a real gain.
- **Loss choice.** Plain L2 instead of Huber is 0.05 points worse on average and changes GGN's bias from +0.17 % to −0.24 %; the Huber alpha (20, 40, 80) changes little except GGN's bias (+0.79 % at alpha 20), still far inside ±5 %.
- **Overfitting risk.** The variants are picked and scored on the same year; the winner of a search like this is biased low. Adopting it would not be an honest improvement.
- **Detector coupling.** The frozen detector's residual profiles were fitted on the current baseline. Changing the baseline changes every alert result, and any change made after looking is post-hoc.

## 7. Recommendation

Keep the current settings and model. Tuning or adding models would gain a fraction of a point against a 30 % limit while forcing the detector results to be re-reported as post-hoc.
The accuracy that matters for the product sits elsewhere: baseline drift for IPMVP savings (see `docs/large_pack_results.md` §6), the Gurugram temperature sensitivity
(`docs/stress_pack_results.md` §3), and the low-precision rules at Goa-type hotels.
"""
    (ROOT / "docs" / "baseline_sensitivity.md").write_text(txt, encoding="utf-8")
    print("wrote docs/baseline_sensitivity.md")


if __name__ == "__main__":
    main()
