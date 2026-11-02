"""Feature engineering shared by notebooks and (later) the product.

gurugram_hourly(): collapse the 15-minute Gurugram incomer into the same hourly schema that
Jaipur and Goa use, so all three hotels can be compared and modelled on one grid.
"""
from pathlib import Path

import numpy as np
import pandas as pd

CLEAN = Path(__file__).resolve().parents[1] / "data" / "clean"
SITES = {"GGN": "Gurugram", "JAI": "Jaipur", "GOA": "Goa"}
ROOMS = {"GGN": 220, "JAI": 160, "GOA": 140}
CONTRACT_KVA = {"GGN": 1000, "JAI": 700, "GOA": 600}


def gurugram_hourly(g15: pd.DataFrame) -> pd.DataFrame:
    """15-min cleaned Gurugram meter -> hourly frame with the Jaipur/Goa column set.

    Energy columns are summed; kva_max_in_hour is the max 15-min kVA in the hour (same definition as the other
    two hotels, and the quantity the utility bills as MD); power_factor is kWh/kVAh for the hour (NaN if all-DG).
    Extra flags carry data-quality info into the hourly grain.
    """
    d = g15.set_index("timestamp")
    h = pd.DataFrame({
        "grid_kwh": d["grid_kwh"].resample("h").sum(),
        "grid_kvah": d["grid_kvah"].resample("h").sum(),
        "dg_kwh": d["dg_kwh"].resample("h").sum(),
        "kva_max_in_hour": d["kva_demand"].resample("h").max(),
        "dg_intervals": d["is_dg"].resample("h").sum(),
        "fault_intervals": d["is_meter_fault"].resample("h").sum(),
        "n_intervals": d["grid_kwh"].resample("h").count(),
    })
    h["kw_avg"] = h["grid_kwh"] + h["dg_kwh"]                      # kWh in 1 h == mean kW, incl. DG (as Jaipur/Goa)
    h["power_factor"] = (h["grid_kwh"] / h["grid_kvah"]).where(h["grid_kvah"] > 0)
    h["total_kwh"] = h["kw_avg"]
    h["is_dg"] = h["dg_intervals"] > 0
    h["has_meter_fault"] = h["fault_intervals"] > 0
    h["exclude_from_model"] = h["has_meter_fault"]
    return h.reset_index()


def unified_hourly() -> pd.DataFrame:
    """One long hourly table for the three hotels with the shared columns."""
    ggn = gurugram_hourly(pd.read_parquet(CLEAN / "meter_ggn_15min.parquet"))
    jai = pd.read_parquet(CLEAN / "meter_jai_hourly.parquet")
    goa = pd.read_parquet(CLEAN / "meter_goa_hourly.parquet")
    for df, flag in ((jai, "is_imputed"), (goa, None)):
        df["has_meter_fault"] = df[flag] if flag else False
    cols = ["timestamp", "grid_kwh", "grid_kvah", "dg_kwh", "kw_avg", "kva_max_in_hour", "power_factor",
            "total_kwh", "is_dg", "has_meter_fault", "exclude_from_model"]
    out = pd.concat([ggn[cols].assign(site="GGN"), jai[cols].assign(site="JAI"), goa[cols].assign(site="GOA")],
                    ignore_index=True)
    return out.sort_values(["site", "timestamp"]).reset_index(drop=True)


def cooling_degree_hours(temp: pd.Series, base: float) -> pd.Series:
    return (temp - base).clip(lower=0)


if __name__ == "__main__":
    u = unified_hourly()
    u.to_parquet(CLEAN / "meter_hourly_all.parquet", index=False)
    print(u.groupby("site").size())
