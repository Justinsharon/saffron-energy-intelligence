"""Waste-type catalogue: what each kind of avoidable waste looks like in the data, how it is costed, what we recommend.

Why a static module: the detector, the alert text and the UI must all describe a waste type in exactly the same words, and the text may only
state facts the data supports (CLAUDE.md: numbers come from models, not from the LLM). Signatures here come from the brief's section 12, the
engineering guide, and the tuning window (anomalies starting before 1 Apr 2026) - never from later labels.

`guardrail` follows the automation table of the brief:
  recommend  - the product only recommends; a person acts (default for everything)
  auto-ok    - the guide allows automation within limits, but this product still only recommends (no control in scope)
  never      - safety / comfort item: no automatic action may ever be proposed (T10)
"""

WASTE_TYPES = {
    "AHU_HAND_MODE": dict(
        label="Banquet AHUs running with no event", sites=["GGN"], equipment="ahu_banquet_kw",
        signature="Banquet AHU kW stays near rated (~45 kW per unit) after the event end + 1 h buffer, with no other event in the calendar.",
        context_suppressor="Any event active in the hour (start - 1 h to end + 1 h; past-midnight events assumed to end 01:00).",
        cost="excess_kW x hours x grid marginal rate (energy + FSA + duty) / PF",
        action="Return banquet AHUs to schedule at the BMS (they were left in hand mode at the local panel); schedule from the events calendar, start 1 h before, stop 1 h after.",
        guardrail="auto-ok", severity="Medium", maps_to_labels=["AHU_SCHEDULE_OVERRIDE"]),
    "HEAT_COOL_FIGHT": dict(
        label="AHU re-heat on while cooling / outdoor air warm", sites=["GGN"], equipment="ahu_heaters_kw",
        signature="AHU electric re-heat kW far above what is normal for that hour and outdoor temperature (the guide allows re-heat only below 16 degC).",
        context_suppressor="Normal winter re-heat for the same hour and outdoor-temperature band is learned from the tuning window and is not flagged.",
        cost="excess_kW x hours x grid marginal rate; plus the chiller kWh spent cooling the same air (not added - conservative)",
        action="Disable AHU re-heat banks above 16 degC outdoor or while the zone's chilled-water valve is open (interlock).",
        guardrail="auto-ok", severity="High", maps_to_labels=["SIMULTANEOUS_HEAT_COOL"]),
    "KITCHEN_EXHAUST_OFF_HOURS": dict(
        label="Kitchen exhaust / make-up air running after the kitchen closed", sites=["GGN"], equipment="kitchen_exhaust_mua_kw",
        signature="Exhaust + make-up-air kW (22 kW) during hours when the profile is zero (kitchen closed).",
        context_suppressor="Hours where the learned profile already shows running (service hours) are never flagged.",
        cost="excess_kW x hours x grid marginal rate (small: 22 kW)",
        action="Recommend an interlock to the kitchen's last-order time with a 30-minute run-on. Never switch exhaust off automatically during service (T10).",
        guardrail="never", severity="Low", maps_to_labels=["KITCHEN_EXHAUST_LEFT_ON"]),
    "LIGHTING_LEFT_ON": dict(
        label="Event / facade lighting left on", sites=["GGN", "JAI", "GOA"], equipment="lighting_kw",
        signature="Lighting kW well above the learned level for that hour and whether an event is on (e.g. ~89 kW vs 34 kW at night at Jaipur).",
        context_suppressor="Event hours (start - 1 h to end + 1 h) use the event-night lighting level.",
        cost="excess_kW x hours x grid marginal rate",
        action="Put event lighting circuits on a timer linked to the events calendar.",
        guardrail="auto-ok", severity="Medium", maps_to_labels=["EVENT_LIGHTING_LEFT_ON"]),
    "LAUNDRY_IN_PEAK": dict(
        label="Laundry running in the peak tariff window", sites=["GGN", "JAI", "GOA"], equipment="laundry_kw",
        signature="Laundry kW > 10 inside the hotel's own peak ToD window (GGN/GOA 18-22, JAI 17-23).",
        context_suppressor="None needed: laundry is a flexible load and does not run in the peak window on a normal day.",
        cost="kVAh in the window x peak ToD surcharge (the energy itself is only shifted, not saved)",
        action="Move the batch to before the peak window starts. Recommend only: laundry is a flexible load (brief section 9).",
        guardrail="recommend", severity="Low", maps_to_labels=["LAUNDRY_PEAK_TARIFF"]),
    "POOL_PUMP_OFF_SCHEDULE": dict(
        label="Pool pumps running outside their schedule", sites=["JAI", "GOA"], equipment="pumps_pool_kw",
        signature="Pump kW at the daytime level during the night hours when the profile is at the low standby level (07:00-17:00 schedule).",
        context_suppressor="Learned per-hour level; daytime pumping is never flagged.",
        cost="excess_kW x hours x grid marginal rate (small load: 14 kW on a ~240 kW site)",
        action="Restore the 07:00-17:00 pump schedule. Pool filtration must still run at least 8 h a day, so do not shorten the schedule below that.",
        guardrail="recommend", severity="Low", maps_to_labels=["POOL_PUMPS_24H"]),
    "POWER_FACTOR_DROP": dict(
        label="Power factor drop (failed APFC capacitor step)", sites=["GGN", "JAI", "GOA"], equipment="main meter (APFC panel)",
        signature="Hourly PF = kWh / kVAh below 0.95 while kWh is normal; the target is >= 0.97.",
        context_suppressor="Diesel hours (PF undefined) are skipped.",
        cost="kWh x (1/PF - 1/PF_normal) x (energy + FSA + duty) rates; each 0.01 PF drop is about +1% kVAh",
        action="Inspect the APFC panel and replace the failed capacitor step; alarm when PF stays below 0.95.",
        guardrail="recommend", severity="High", maps_to_labels=["POWER_FACTOR_DROP"]),
    "CHILLER_STAGING_LOW_LOAD": dict(
        label="Two chillers running at low load", sites=["GGN"], equipment="chillers CH-1 + CH-3",
        signature="Two chillers running while plant load is below 130 TR (CH-3 alone can carry up to 130 TR); kW/TR about double (1.2-1.6 vs 0.6-0.68).",
        context_suppressor="Plant load above 130 TR legitimately needs CH-1; not flagged. CH-2 is treated as unavailable (owner-confirmed default).",
        cost="(chiller kW - 0.65 kW/TR x plant TR) x hours x grid marginal rate",
        action="Enforce night staging: CH-3 alone below 130 TR; alarm if two chillers run below 35% combined load.",
        guardrail="auto-ok", severity="High", maps_to_labels=["CHILLER_ON_LOW_LOAD"]),
    "CHILLER_PART_LOAD_INEFFICIENCY": dict(
        label="Chiller plant kW/TR far above normal for the load", sites=["JAI", "GOA"], equipment="chillers",
        signature="Chiller kW per TR above the learned curve for that plant load by more than a noise margin, sustained >= 2 h (typical of a second chiller running at low occupancy).",
        context_suppressor="Compared against the same plant load, so weather and occupancy that raise load are already accounted for.",
        cost="(chiller kW - expected kW/TR x plant TR) x hours x grid marginal rate",
        action="Check the chiller staging sequence; run one chiller at night when occupancy is low.",
        guardrail="auto-ok", severity="High", maps_to_labels=["CHILLER_ON_LOW_LOAD"]),
    "CHW_SETPOINT_LOW": dict(
        label="Chilled-water setpoint below standard", sites=["GGN"], equipment="chw_setpoint_c",
        signature="CHW supply setpoint below 7.0 degC (standard); each degC lower adds ~3-4% chiller power. Below 6.5 degC breaches the operating limit.",
        context_suppressor="None: a lowered setpoint is a choice, not a weather effect. Evidence cites the BMS command log entry.",
        cost="chiller kW x ~3.5% per degC below 7.0 x hours x grid marginal rate",
        action="Reset to 7.0 degC (8 degC allowed when outdoor < 24 degC and load is light). Never recommend below 6.5 degC.",
        guardrail="auto-ok", severity="Medium", maps_to_labels=["CHW_SETPOINT_LOWERED"]),   # type name from the brief (T6); no tuning-window example
    "METER_DATA_FAULT": dict(
        label="Meter data fault (flat line / zeros / gap)", sites=["GGN", "JAI"], equipment="main meter (AMR link)",
        signature="Billed energy columns repeat the same value (or read 0) for several intervals while kW and power factor stay live; or the meter returns nothing.",
        context_suppressor="This IS the suppressor: hours inside a fault are excluded from baselines, never raised as waste, never counted as savings (T5).",
        cost="none - a data fault is never a saving",
        action="Raise a ticket with the meter vendor; keep the bill as issued and show the corrected figure beside it.",
        guardrail="recommend", severity="Data quality", maps_to_labels=["METER_DATA_FAULT"]),
}

# Things the brief lists that this product deliberately does not detect or size (state in the UI).
NOT_DETECTED = [
    "Waste smaller than the sub-meter noise (a few kW on a 600 kW site hidden in 'other' or unmetered load).",
    "Hand-mode overrides on equipment other than banquet AHUs: the BMS log records entering hand mode but never leaving it.",
    "Waste in equipment with no sub-meter (unmetered 'other' load is 8-14% of site energy).",
    "Comfort breaches (guest-room temperatures are not in the data), so 'too hot' is never judged.",
]
