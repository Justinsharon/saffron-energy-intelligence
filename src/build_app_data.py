"""Precompute everything the web app reads, so the hosted app starts in seconds and never refits the detector.

Writes data/app/*.parquet. Run after any change to the cleaned data, detector or bills:  uv run python src/build_app_data.py
"""
import pandas as pd

from alert_cards import build_cards, card_text, fault_cards
from attribution import production_baseline
from bills import reconcile_all
from detector import site_frame
from features import CLEAN

APP = CLEAN.parent / "app"


def main():
    APP.mkdir(exist_ok=True)
    for s in ["GGN", "JAI", "GOA"]:
        d = site_frame(s)
        p, _ = production_baseline(s)
        d["pred_full"] = p.pred.to_numpy()          # full-year fit (savings / attribution); pred_ens = out-of-fold (detector)
        d["pf"] = (d.grid_kwh / d.grid_kvah).where((d.grid_kvah > 0) & ~d.is_dg)
        d["kw_per_tr"] = (d.chillers_kw / d.chiller_load_tr).where(d.chiller_load_tr > 5)
        if s == "GGN":
            sub = pd.read_parquet(CLEAN / "sub_ggn_hourly.parquet")[["timestamp", "ev_chargers_kw", "water_heating_kw", "pool_kw"]]
            d = d.merge(sub, on="timestamp", how="left")
        d.drop(columns=["date"]).to_parquet(APP / f"frame_{s}.parquet", index=False)
        print(s, d.shape)
    c = build_cards()
    c["text"] = [card_text(r) for r in c.itertuples()]
    c.to_parquet(APP / "cards.parquet", index=False)
    fault_cards().to_parquet(APP / "faults.parquet", index=False)
    reconcile_all().to_parquet(APP / "bills_recon.parquet", index=False)
    print("cards", len(c))


if __name__ == "__main__":
    main()
