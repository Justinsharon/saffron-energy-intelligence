"""Run the frozen pipeline on the synthetic live year (data/live/, Oct 2026 - Sep 2027) and score it.

Nothing is refitted on live data. Two processes, because every module binds its data folder at import (src/features.py):
  1. freeze (default folder, data/clean): the detector's normal-behaviour profiles exactly as notebook 05 fits them
     (load_all with the tuning-label mask), the post-hoc recalibration fit (recalibration.fit), and the baseline's
     training frames (every valid hour of Oct 2025 - Sep 2026). Also records the original held-out scores for comparison.
  2. live (SAFFRON_DATA=data/live): baseline ensemble fitted on the original year predicts the live year (saved as
     data/live/baseline_oof.parquet, same columns, so the detector's residual layer reads it); frozen detector, meter-fault
     stream, post-hoc demand/EV rules, recalibration, alert cards and bill reconciliation via build_app_data; then scoring
     with src/evaluation.py's matching, written to data/live/results.md.

Only change to frozen objects: the detector's ₹ rates are re-read from the live tariff sheet (+3 %), because a tariff is an
input, not a fitted parameter; the normal PF (pf_ref) the rate divides by stays frozen. demand_ev_rules keeps its hard-coded
₹580/kVA penalty (the live sheet says ₹597.4), so its ₹ is ~3 % low; left as is because it is part of the rule.

Robustness check on synthetic data, not a clean held-out test: the live anomalies were injected with the type mix and rates
of the full original label set, including labels from 1 Apr 2026.

Run: uv run python tools/run_live_year.py
"""
import os
import pickle
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
LIVE = ROOT / "data" / "live"


def freeze(path):
    import pandas as pd

    import detector as D
    import evaluation as E
    import recalibration as RC
    from baseline import build_features, cv_rmse, nmbe
    from features import CLEAN, DEFAULT_CLEAN

    assert CLEAN == DEFAULT_CLEAN, "freeze stage must run on the original year"
    frames, P = D.load_all(E.tuning_label_mask)                     # as notebook 05
    F = RC.fit(RC._frame())
    train = {s: build_features(s) for s in D.SITES}
    al = pd.read_parquet(CLEAN / "alerts.parquet")
    faults = pd.read_parquet(CLEAN / "meter_faults.parquet")
    flags = {s: {k: pd.Series(f.to_numpy(bool), index=pd.DatetimeIndex(frames[s].timestamp)) for k, (f, _) in D.rule_signals(s, frames[s], P).items()}
             for s in D.SITES}
    orig = dict(summary=E.score_heldout(al, faults)["summary"], onset=E.score_heldout_onset(al, flags))
    oof = pd.read_parquet(CLEAN / "baseline_oof.parquet")
    orig["baseline"] = {s: _bmetrics(g, cv_rmse, nmbe) for s, g in oof.groupby("site")}
    with open(path, "wb") as fh:
        pickle.dump(dict(P=P, F=F, train=train, orig=orig), fh)
    print("frozen: detector profiles, recalibration fit, baseline training frames ->", path)


def _bmetrics(g, cv_rmse, nmbe):
    v = g[g.valid]
    mm = v.groupby(v.timestamp.dt.to_period("M")).agg(a=("total_kwh", "mean"), p=("pred_ens", "mean"))
    return dict(h_cv=cv_rmse(v.total_kwh, v.pred_ens), h_nmbe=nmbe(v.total_kwh, v.pred_ens),
                m_cv=cv_rmse(mm.a, mm.p), m_nmbe=nmbe(mm.a, mm.p), hours=len(v))


def live(path):
    import numpy as np
    import pandas as pd

    import attribution
    import build_app_data
    import demand_ev_rules
    import detector as D
    import evaluation as E
    from baseline import GBM_FEATURES, build_features, cv_rmse, make_gbm, make_ridge, nmbe
    from features import CLEAN

    assert CLEAN == LIVE.resolve(), f"live stage must run with SAFFRON_DATA=data/live (got {CLEAN})"
    with open(path, "rb") as fh:
        Z = pickle.load(fh)
    P, F, train, orig = Z["P"], Z["F"], Z["train"], Z["orig"]

    # 1. baseline: fit on the original year's valid hours (as baseline.fit_predict), predict the live year
    rows = []
    for s, tr in train.items():
        tr = tr[tr.valid]
        r = make_ridge().fit(tr, tr.total_kwh)
        g = make_gbm().fit(tr[GBM_FEATURES], tr.total_kwh)
        attribution._MODELS[s] = (r, g)                             # production_baseline() reuses these: no live refit
        d = build_features(s)
        pr, pg = r.predict(d), g.predict(d[GBM_FEATURES])
        rows.append(pd.DataFrame({"site": s, "timestamp": d.timestamp, "total_kwh": d.total_kwh, "valid": d.valid,
                                  "pred_ridge": pr, "pred_gbm": pg, "pred_ens": (pr + pg) / 2}))
    oof = pd.concat(rows, ignore_index=True)
    oof.to_parquet(CLEAN / "baseline_oof.parquet", index=False)

    # 2. frozen detector (tariff rates re-read from the live sheet; profiles, thresholds, pf_ref, sigma frozen)
    for s in D.SITES:
        t = D._tariff(s)
        P.rate_kvah[s] = t["energy"] + t["fsa"] + t["duty"]
        P.rate_kwh[s] = P.rate_kvah[s] / P.pf_ref[s]
        P.peak_surcharge[s] = t["peak"]
    frames = {s: D.site_frame(s) for s in D.SITES}
    al = D.detect_all(frames, P)
    al.assign(text=[D.alert_text(a) for a in al.itertuples()]).to_parquet(CLEAN / "alerts.parquet", index=False)
    faults = pd.concat([D.detect_meter_faults(s) for s in D.SITES], ignore_index=True)
    faults.to_parquet(CLEAN / "meter_faults.parquet", index=False)      # detected faults, as notebook 05 writes them
    demand_ev_rules.all_additions().to_parquet(CLEAN / "alerts_demand_ev.parquet", index=False)
    build_app_data.main(recal=F)                                     # cards (incl. recalibration), faults, bills -> data/live/app
    print("alerts", len(al), "| faults", len(faults))

    # 3. score with src/evaluation.py's matching; every live label starts after the cut, so window "report" is the whole year
    lab = pd.read_parquet(CLEAN / "anomaly_labels.parquet")
    S = E.score(al, lab, faults, "report")
    flags = {s: {k: pd.Series(f.to_numpy(bool), index=pd.DatetimeIndex(frames[s].timestamp)) for k, (f, _) in D.rule_signals(s, frames[s], P).items()}
             for s in D.SITES}
    O = E.onset_ttd(al, lab, flags, "report")
    cards = pd.read_parquet(CLEAN / "app" / "cards.parquet")
    SC = E.score(cards, lab, faults, "report")
    inside = sum(int(((cards.site == r.site) & (cards.start < r.end) & (cards.end > r.start)).sum()) for r in faults.itertuples())
    B = {s: _bmetrics(g, cv_rmse, nmbe) for s, g in oof.groupby("site")}
    write_results(S, O, SC, B, orig, faults, lab, inside, cards)


def write_results(S, O, SC, B, orig, faults, lab, inside, cards):
    import pandas as pd

    s, o, so, oo = S["summary"], O, orig["summary"], orig["onset"]
    pct = lambda x: "—" if pd.isna(x) else f"{x:.0%}"
    hr = lambda x: "—" if pd.isna(x) else f"{x:.1f} h"
    out = []
    P = out.append
    P("# Live year (Oct 2026 – Sep 2027): pipeline results\n")
    P("> **Robustness check on synthetic data, not a clean held-out test.** The live year is generated (`tools/make_live_year.py`) and its "
      "anomalies were injected with the type mix and rates of the *full* original label set, including labels from 1 Apr 2026. The models are "
      "not refitted: detector profiles and thresholds, the recalibration fit and the baseline were all fitted on Oct 2025 – Sep 2026 "
      "(`tools/run_live_year.py`). The only refreshed input is the tariff sheet (₹ rates +3 %).\n")
    P("## Detector (frozen), scored with `evaluation.score`\n")
    P("| metric | original held-out (Apr–Sep 2026) | live year | target |")
    P("|---|---:|---:|---|")
    P(f"| Precision (alert overlaps a labelled waste anomaly, same site) | {pct(so['precision_any'])} | {pct(s['precision_any'])} | ≥ 70 % |")
    P(f"| Precision, type-matched | {pct(so['precision_typed'])} | {pct(s['precision_typed'])} | |")
    P(f"| Recall, High + Medium | {pct(so['recall_HM'])} ({so['n_HM']}) | {pct(s['recall_HM'])} ({s['n_HM']}) | ≥ 80 % |")
    P(f"| Recall, all severities | {pct(so['recall_all'])} | {pct(s['recall_all'])} | |")
    P(f"| Time to detect, High, median, from first appearance in the data | {hr(oo['ttd_onset_median_h'])} ({oo['n_scored']} scored) | "
      f"{hr(o['ttd_onset_median_h'])} ({o['n_scored']} scored, max {hr(o['ttd_onset_max_h'])}, {pct(o['ttd_onset_under_2h'])} ≤ 2 h) | < 2 h |")
    P(f"| Time to detect, High, median, from label start (secondary) | {hr(so['ttd_high_median_h'])} | {hr(s['ttd_high_median_h'])} | |")
    P(f"| Alerts / waste labels | {so['n_alerts']} / {so['n_labels']} | {s['n_alerts']} / {s['n_labels']} | |")
    P(f"| Labelled ₹ found (share of excess cost on detected labels) | {pct(so['cost_found_share'])} | {pct(s['cost_found_share'])} | |")
    P(f"| Meter-data-fault labels found by the fault stream | {so['faults_detected']} / {so['fault_labels']} | {s['faults_detected']} / {s['fault_labels']} | all |")
    P(f"\nHigh labels: {o['n_high']}; onset found {o['n_onset_found']}, pre-alerted {o['n_pre_alerted']}, no scoreable onset or no alert "
      f"{o['n_no_onset_or_no_alert']}. Label start → onset median {hr(o['label_to_onset_median_h'])}.\n")
    P("### Recall by label type (live)\n")
    P("| type | labels | detected | pre-alerted | median TTD from label start |")
    P("|---|---:|---:|---:|---:|")
    for r in S["by_type"].itertuples():
        P(f"| {r.typ} | {r.n} | {int(r.detected)} | {int(r.pre_alerted)} | {hr(r.median_ttd_h)} |")
    P("\n### Precision by rule (live)\n")
    P("| rule | alerts | overlap a label | type-matched |")
    P("|---|---:|---:|---:|")
    for r in S["by_rule"].itertuples():
        P(f"| {r.rule} | {r.alerts} | {pct(r.precise)} | {pct(r.typed)} |")

    sc = SC["summary"]
    ph = cards[cards.post_hoc]
    P("\n## With the post-hoc rules (alert cards: detector + demand/EV + kW/TR staging)\n")
    P(f"Precision {pct(sc['precision_any'])} over {sc['n_alerts']} alerts; recall High+Medium {pct(sc['recall_HM'])}, all {pct(sc['recall_all'])}; "
      f"labelled ₹ found {pct(sc['cost_found_share'])}. Post-hoc alerts: {ph.rule.value_counts().to_dict()}. These rules were written after the "
      "original held-out window was seen, so they are post-hoc there too.\n")
    P("## Meter faults (T5)\n")
    for r in faults.itertuples():
        P(f"- {r.site} {r.start:%d %b %Y %H:%M} – {r.end:%H:%M}: {r.kind}, detected {r.detected_at:%H:%M}; {r.evidence}")
    P(f"\nAlert cards overlapping a detected fault window: {inside} (must be 0).\n")
    P("## Baseline (fitted on Oct 2025 – Sep 2026, predicting the live year)\n")
    P("ASHRAE Guideline 14 targets: hourly CV(RMSE) < 30 %, monthly < 15 %, NMBE within ±5 %. Original = leave-one-month-out on its own year.\n")
    P("| hotel | hourly CV(RMSE) orig → live | monthly CV(RMSE) orig → live | NMBE (hourly) orig → live | monthly NMBE live | valid hours | pass |")
    P("|---|---:|---:|---:|---:|---:|---|")
    for st, b in B.items():
        a = orig["baseline"][st]
        ok = b["h_cv"] < 30 and b["m_cv"] < 15 and abs(b["h_nmbe"]) <= 5 and abs(b["m_nmbe"]) <= 5
        P(f"| {st} | {a['h_cv']:.1f} % → {b['h_cv']:.1f} % | {a['m_cv']:.1f} % → {b['m_cv']:.1f} % | {a['h_nmbe']:+.2f} % → {b['h_nmbe']:+.2f} % | "
          f"{b['m_nmbe']:+.2f} % | {b['hours']:,} | {'yes' if ok else 'no'} |")
    P("\nThe live load includes +1.2 % growth and the injected waste, which the baseline (fitted a year earlier) does not know about; "
      "a positive NMBE (actual above prediction) is the expected direction.\n")
    txt = "\n".join(out)
    (LIVE / "results.md").write_text(txt, encoding="utf-8")
    print(txt)


def main():
    path = Path(tempfile.gettempdir()) / "saffron_frozen_for_live.pkl"
    py = [sys.executable, str(Path(__file__).resolve())]
    env = {k: v for k, v in os.environ.items() if k != "SAFFRON_DATA"}
    subprocess.run(py + ["freeze", str(path)], env=env, check=True)
    subprocess.run(py + ["live", str(path)], env={**env, "SAFFRON_DATA": str(LIVE)}, check=True)
    path.unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) == 3:
        {"freeze": freeze, "live": live}[sys.argv[1]](sys.argv[2])
    else:
        main()
