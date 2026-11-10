"""Duty-engineer alert cards: one row per alert with everything the UI and the assistant show (brief §13 format).

Why a separate layer: the detector (frozen) produces flags, ₹ and evidence; this module only *presents* them - title, severity, equipment,
likely cause, action, guardrail wording, and which signals to chart as evidence. It adds no numbers of its own except unit conversions.
Detector alerts and the post-hoc demand/EV rules are merged here; post-hoc rows are labelled so.
"""
import pandas as pd

from features import CLEAN, SITES
from waste_types import WASTE_TYPES

EXTRA_TYPES = {     # post-hoc rules (src/demand_ev_rules.py) and the residual layer
    "DEMAND_NEAR_CONTRACT": dict(label="Site demand near / above contract demand", equipment="main incomer (15-min kVA)", severity="High",
                                 guardrail="recommend",
                                 action="Hold laundry and heat-pump water heating, throttle EV charging (allowed above 920 kVA), stagger banquet AHU pre-cooling. Never shed chillers, kitchen, lifts or life-safety."),
    "EV_CHARGER_NIGHT_ON": dict(label="EV charger drawing power overnight", equipment="EV chargers", severity="Low", guardrail="recommend",
                                action="Inspect the charger at the panel (likely a stuck session); clear the session or isolate the faulty port."),
    "RESIDUAL_UNEXPLAINED": dict(label="Site load above the weather/occupancy/event baseline", equipment="main meter", severity="Medium",
                                 guardrail="recommend", action="Walk the largest sub-metered loads for the period; no named waste type matches."),
}
CAUSE = {
    "AHU_HAND_MODE": "AHUs left in hand mode at the local panel after the event (the BMS logs entering hand mode, never leaving it).",
    "HEAT_COOL_FIGHT": "Re-heat and cooling running together: no interlock between re-heat banks and outdoor temperature / CHW valve.",
    "KITCHEN_EXHAUST_OFF_HOURS": "Exhaust and make-up air left running after the last order.",
    "LIGHTING_LEFT_ON": "Event or facade lighting circuits not switched off after the event.",
    "LAUNDRY_IN_PEAK": "Laundry batch scheduled inside the peak tariff window.",
    "POOL_PUMP_OFF_SCHEDULE": "Pump timer bypassed: pumps running round the clock instead of the 07:00–17:00 schedule.",
    "POWER_FACTOR_DROP": "A capacitor step in the APFC panel has failed or tripped, so reactive power is drawn from the grid.",
    "CHILLER_STAGING_LOW_LOAD": "Second chiller left on at night when one chiller can carry the load (staging sequence not followed).",
    "CHILLER_PART_LOAD_INEFFICIENCY": "Second chiller running at low occupancy, so both run at poor part-load efficiency.",
    "CHW_SETPOINT_LOW": "Setpoint lowered (often after a single comfort complaint) and never reset.",
    "DEMAND_NEAR_CONTRACT": "Shiftable loads (laundry, water heating, banquet AHUs) stacked on a hot afternoon peak.",
    "EV_CHARGER_NIGHT_ON": "Charger session stuck on.",
    "RESIDUAL_UNEXPLAINED": "Not identified: the extra load is outside every named waste signature.",
}
# Columns plotted as evidence for each rule (from detector.site_frame); the main-meter actual vs baseline is always shown too.
CHART = {
    "AHU_HAND_MODE": ["ahu_banquet_kw", "ev_guests"], "HEAT_COOL_FIGHT": ["ahu_heaters_kw", "temp_c"], "KITCHEN_EXHAUST_OFF_HOURS": ["kitchen_exhaust_kw"],
    "LIGHTING_LEFT_ON": ["lighting_kw", "ev_guests"], "LAUNDRY_IN_PEAK": ["laundry_kw"], "POOL_PUMP_OFF_SCHEDULE": ["pool_pump_kw"],
    "POWER_FACTOR_DROP": ["pf"], "CHILLER_STAGING_LOW_LOAD": ["chillers_kw", "chiller_load_tr", "n_chillers"],
    "CHILLER_PART_LOAD_INEFFICIENCY": ["chillers_kw", "chiller_load_tr", "kw_per_tr"], "CHW_SETPOINT_LOW": ["chw_setpoint_c", "chillers_kw"],
    "DEMAND_NEAR_CONTRACT": ["kva_max_in_hour"], "EV_CHARGER_NIGHT_ON": ["ev_chargers_kw"], "RESIDUAL_UNEXPLAINED": [],
}
ONE_OFF = {"LAUNDRY_IN_PEAK", "DEMAND_NEAR_CONTRACT"}        # a batch or a peak, not a condition that runs all day
DIGEST = {"LAUNDRY_IN_PEAK", "EV_CHARGER_NIGHT_ON"}          # route to the daily digest, not the duty engineer's pager
LOWER_BOUND = {"CHILLER_STAGING_LOW_LOAD", "CHW_SETPOINT_LOW", "AHU_HAND_MODE"}     # notebook 06: our ₹ is 0.4–0.8x the key's


def _meta(rule: str) -> dict:
    return WASTE_TYPES.get(rule) or EXTRA_TYPES[rule]


def build_cards() -> pd.DataFrame:
    a = pd.read_parquet(CLEAN / "alerts.parquet").assign(post_hoc=False)
    x = pd.read_parquet(CLEAN / "alerts_demand_ev.parquet").assign(post_hoc=True)
    x["excess_kwh"] = 0.0
    x["inr_per_hour"] = x.cost_inr / x.flagged_h
    x["inr_per_day"] = x.inr_per_hour * 24
    x["alert_id"] = [f"PH-{i + 1:03d}" for i in range(len(x))]
    c = pd.concat([a.drop(columns=["text"], errors="ignore"), x], ignore_index=True)
    m = c.rule.map(_meta)
    c["hotel"] = c.site.map(SITES)
    c["title"] = m.map(lambda v: v["label"])
    c["severity"] = m.map(lambda v: v["severity"])
    c["equipment"] = m.map(lambda v: v["equipment"])
    c["action"] = m.map(lambda v: v["action"])
    c["guardrail"] = m.map(lambda v: v["guardrail"])
    c["cause"] = c.rule.map(CAUSE)
    c["duration_h"] = (c.end - c.start).dt.total_seconds() / 3600
    c["detect_lag_h"] = (c.alert_time - c.start).dt.total_seconds() / 3600
    c["cost_inr"] = c.cost_inr.fillna(0.0)
    c["cost_note"] = c.rule.map(lambda r: "lower-bound estimate" if r in LOWER_BOUND else "")
    c.loc[c.rule == "LAUNDRY_IN_PEAK", "cost_note"] = "peak surcharge only (energy is shifted, not saved)"
    c.loc[c.rule == "DEMAND_NEAR_CONTRACT", "cost_note"] = "excess-demand penalty if this peak stands as the month's MD"
    c["guard_text"] = c.guardrail.map({"never": "Recommendation only. Never switched off automatically (safety / kitchen-hours item).",
                                       "auto-ok": "Recommendation only. A person approves; the guide would allow automation within limits.",
                                       "recommend": "Recommendation only. A person approves."})
    for col in ["evidence", "action", "title"]:
        c[col] = c[col].str.replace(" degC", " °C").str.replace("degC", "°C")
    c["status"] = "Open"
    c = c.sort_values("alert_time").reset_index(drop=True)
    # --- presentation fixes from the alert-rating dry run (10 Nov; detector untouched) ---
    # 1. ₹/day only where the condition continues day after day; one-off events show ₹ per occurrence
    c["cost_basis"] = "per_day"
    c.loc[c.rule.isin(ONE_OFF), "cost_basis"] = "per_occurrence"
    # 2. small or schedule-only items go to a daily digest instead of interrupting the shift
    c["channel"] = "Alert"
    c.loc[c.rule.isin(DIGEST) | ((c.cost_inr < 500) & (c.severity != "High")), "channel"] = "Daily digest"
    # 3. repeats: how many alerts of the same type at the same hotel in the 30 days before this one
    c["repeat_30d"] = [int(((c.site == r.site) & (c.rule == r.rule) & (c.alert_time < r.alert_time)
                            & (c.alert_time >= r.alert_time - pd.Timedelta(days=30))).sum()) for r in c.itertuples()]
    # 4. sites without a chiller-count point: the staging cause is inferred from kW/TR
    c["inferred_note"] = ""
    c.loc[(c.rule == "CHILLER_PART_LOAD_INEFFICIENCY"), "inferred_note"] = (
        "This site does not meter how many chillers run; the staging cause is inferred from kW/TR at this load.")
    return c


def card_text(r) -> str:
    """The one-paragraph alert in the brief's format. Every number comes from the row."""
    if r.cost_inr <= 0:
        cost = "₹ impact not material"
    elif r.cost_basis == "per_occurrence":
        cost = f"₹{r.cost_inr:,.0f} for this occurrence"
    else:
        cost = f"~₹{r.inr_per_hour:,.0f}/h (₹{r.inr_per_day:,.0f}/day while it continues; ₹{r.cost_inr:,.0f} over the episode)"
    note = f" [{r.cost_note}]" if r.cost_note else ""
    span = (f"{r.flagged_h:.0f} h flagged within a {r.duration_h:.0f} h episode" if r.flagged_h < r.duration_h - 0.5
            else f"{r.duration_h:.0f} h")
    rep = f" Repeat: {r.repeat_30d + 1}{'nd' if r.repeat_30d == 1 else 'rd' if r.repeat_30d == 2 else 'th'} time in 30 days at this hotel — escalate to the chief engineer." if r.repeat_30d else ""
    inf = f" {r.inferred_note}" if r.inferred_note else ""
    return (f"{r.hotel} · {r.title} — since {r.start:%a %d %b %H:%M}, {span}. {r.evidence}. {cost}{note}.{inf} "
            f"Likely cause: {r.cause} Action: {r.action}{rep}")


def fault_cards() -> pd.DataFrame:
    f = pd.read_parquet(CLEAN / "meter_faults.parquet")
    f["hotel"] = f.site.map(SITES)
    f["duration_h"] = (f.end - f.start).dt.total_seconds() / 3600
    f["handling"] = "Data fault: excluded from baseline, alerts and savings. Bill left as issued; corrected figure shown in Bills."
    return f


if __name__ == "__main__":
    c = build_cards()
    print(len(c), c.groupby(["site", "severity"]).size())
    print(card_text(c[c.rule == "AHU_HAND_MODE"].iloc[0]))
    print(fault_cards())
