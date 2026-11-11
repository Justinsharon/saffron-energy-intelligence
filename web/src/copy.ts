// Plain-language wording for everything the hotel team reads. Technical detail (meter readings) stays available one tap away.

export const RULE: Record<string, { title: string; why: string; todo: string }> = {
  AHU_HAND_MODE: {
    title: "Banquet hall cooling left on after the event",
    why: "The hall's air handlers kept running after the guests left. They were most likely switched to manual at the local panel and never switched back.",
    todo: "Put the banquet air handlers back on their automatic schedule at the building control system.",
  },
  HEAT_COOL_FIGHT: {
    title: "Heating and cooling running at the same time",
    why: "The re-heaters inside the air handlers are warming air that the chillers have just cooled, on a day warm enough not to need heat.",
    todo: "Switch the re-heaters off, and have them lock out automatically when it is above 16 °C outside.",
  },
  KITCHEN_EXHAUST_OFF_HOURS: {
    title: "Kitchen extract fans left running after closing",
    why: "The extract and fresh-air fans kept running after the last order was served.",
    todo: "Switch them off once cooking has stopped. Ask the chief engineer to link the fans to kitchen opening hours. They are never switched off automatically, for safety.",
  },
  LIGHTING_LEFT_ON: {
    title: "Event lighting left on",
    why: "Lighting for an event space stayed on well after the event ended.",
    todo: "Switch off the event and facade lighting circuits; add them to the end-of-event checklist.",
  },
  LAUNDRY_IN_PEAK: {
    title: "Laundry running in expensive evening hours",
    why: "A laundry batch ran during the evening hours, when every unit of electricity costs more.",
    todo: "Schedule laundry outside the evening peak (before the afternoon or after 10 pm).",
  },
  POOL_PUMP_OFF_SCHEDULE: {
    title: "Pool pumps running round the clock",
    why: "The pool pumps ran through the night instead of on their daytime schedule. The timer has probably been bypassed.",
    todo: "Restore the pump timer. Filtration still needs at least 8 hours a day.",
  },
  POWER_FACTOR_DROP: {
    title: "Capacitor panel fault is raising the bill",
    why: "A failed capacitor step means the utility is billing the hotel for more electricity than it actually uses (about 10% extra).",
    todo: "Have the electrician inspect the capacitor (power-factor) panel and replace the failed step.",
  },
  CHILLER_STAGING_LOW_LOAD: {
    title: "Two chillers running when one would do",
    why: "A second chiller was left on overnight while the cooling need was low enough for one. Both then run inefficiently.",
    todo: "Run a single chiller at night. Bring the second one on only when one can no longer keep up.",
  },
  STAGING_KWTR: {
    title: "Two chillers likely running when one would do",
    why: "The chiller plant is drawing about twice the power one chiller needs for this much cooling, which is what two half-loaded chillers look like. The building system shows only one running, so its status reading may also be wrong.",
    todo: "Check at the plant room which chillers are actually on; switch off the second if one can carry the load. Report the status mismatch to the controls contractor.",
  },
  CHILLER_PART_LOAD_INEFFICIENCY: {
    title: "Chillers running inefficiently at low load",
    why: "The chillers are using far more power for the cooling they deliver than they normally do, usually because a second unit is on when occupancy is low.",
    todo: "Run one chiller when the hotel is quiet; bring the second on only when needed.",
  },
  CHW_SETPOINT_LOW: {
    title: "Chilled water set colder than needed",
    why: "Someone lowered the chilled-water temperature from the standard 7 °C, often after a single guest complaint, and it was never reset. Every degree colder costs extra chiller power.",
    todo: "Reset the chilled-water temperature to 7 °C (8 °C is fine on cool, quiet days). Never set it below 6.5 °C.",
  },
  DEMAND_NEAR_CONTRACT: {
    title: "Power demand above the contracted limit",
    why: "The hotel drew more power at once than its contract with the utility allows, which triggers a penalty charge for the whole month.",
    todo: "Pause laundry and water heating, slow down EV charging, and stagger banquet pre-cooling until demand falls. Never cut chillers, kitchen, lifts or safety systems.",
  },
  EV_CHARGER_NIGHT_ON: {
    title: "EV charger drawing power overnight",
    why: "A car charger kept drawing power through the night with no session expected — likely a stuck session.",
    todo: "Check the charger and clear or isolate the stuck port.",
  },
  RESIDUAL_UNEXPLAINED: {
    title: "Hotel using more than expected",
    why: "The whole hotel is using more electricity than the weather, guests and events explain, and no single piece of equipment stands out.",
    todo: "Walk the largest loads (plant room, kitchen, laundry) to find what is running that shouldn't be.",
  },
};

export const PRIORITY: Record<string, string> = { High: "High priority", Medium: "Medium priority", Low: "Low priority" };

export const SAFETY: Record<string, string> = {
  never: "A recommendation only. This equipment is never switched automatically, for safety reasons.",
  "auto-ok": "A recommendation only. Someone on the team decides and makes the change.",
  recommend: "A recommendation only. Someone on the team decides and makes the change.",
};

export const BILL_STATUS: Record<string, { label: string; tone: "ok" | "dq" | "high" | "med" }> = {
  Reconciled: { label: "Matches meter", tone: "ok" },
  "Meter fault": { label: "Billed on faulty readings", tone: "dq" },
  Provisional: { label: "Estimated bill", tone: "high" },
  Check: { label: "Check", tone: "med" },
};

export const DRIVER: Record<string, string> = {
  Weather: "Weather", Occupancy: "Guests in house", Events: "Events", Calendar: "Days in the month", Anomalies: "Waste and faults",
  Demand: "Peak-demand charges", Diesel: "Diesel generator", "Tariff mix": "Time-of-day pricing", Unexplained: "Not explained",
};

/** Savings measures grouped and named for a hotel manager. */
export function measureName(m: string): string {
  if (m.startsWith("Act on detected")) return "Fix the waste the alerts find";
  if (m.startsWith("Hold PF")) return "Upgrade the capacitor panel so the bill stops charging for wasted power";
  if (m.startsWith("Keep PF")) return "Repair capacitor faults within hours";
  if (m.startsWith("Right-size")) return m.replace(/Right-size contract demand (\d[\d,]*) → (\d[\d,]*) kVA.*/, "Lower the contracted power limit from $1 to $2 kVA");
  if (m.startsWith("Dim")) return "Dim corridor and outdoor lighting after midnight";
  if (m.startsWith("Avoid contract")) return "Stay under the contracted power limit on hot afternoons";
  if (m.startsWith("Shift flexible")) return m.includes("water heating") ? "Move laundry, water heating and EV charging out of the evening peak" : "Move laundry out of the evening peak";
  if (m.startsWith("CHW reset")) return "Run chilled water at 8 °C on cool, quiet days";
  if (m.startsWith("VFDs")) return "Fit speed controls to the chilled-water pumps (investment)";
  return m;
}
export function measureGroup(m: string): string {
  if (m.startsWith("Act on detected")) return "Fix the waste alerts find";
  if (m.startsWith("Hold PF") || m.startsWith("Keep PF")) return "Capacitor panel";
  if (m.startsWith("Right-size")) return "Lower contracted power limit";
  if (m.startsWith("Dim")) return "Night lighting";
  if (m.startsWith("Avoid contract")) return "Avoid peak penalties";
  if (m.startsWith("Shift flexible")) return "Move loads off evening peak";
  if (m.startsWith("CHW reset")) return "Warmer chilled water on cool days";
  if (m.startsWith("VFDs")) return "Pump speed controls (investment)";
  return m;
}
export const CATEGORY: Record<string, string> = { Energy: "Use less", ToD: "Use at cheaper times", Demand: "Lower peak charges", "Capital (note)": "Needs investment" };
export const CONFIDENCE = (c: string) => (c.startsWith("High") ? "Measured" : c.startsWith("Medium") ? "Estimated" : "Rough estimate");

export const LOAD: Record<string, string> = {
  Laundry: "Laundry", "Water heating": "Water heating", "Banquet AHUs": "Banquet hall cooling", "EV chargers": "EV charging",
};

/** Equipment names as the engineers say them. */
export const EQUIPMENT: Record<string, string> = {
  "EV chargers": "EV chargers", ahu_banquet_kw: "Banquet hall air handlers", ahu_heaters_kw: "Air-handler heaters", "chiller plant (CH-1 / CH-3)": "Chillers 1 and 3",
  chillers: "Chillers", "chillers CH-1 + CH-3": "Chillers 1 and 3", chw_setpoint_c: "Chilled-water temperature setting", kitchen_exhaust_mua_kw: "Kitchen extract and fresh-air fans",
  laundry_kw: "Laundry", lighting_kw: "Lighting", pumps_pool_kw: "Pool pumps", "main incomer (15-min kVA)": "Main power supply", "main meter": "Main meter",
  "main meter (APFC panel)": "Main meter (capacitor panel)",
};
