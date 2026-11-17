// Plant Room simulation model (Gurugram). Pure functions, shared by the Plant Room screen, its tests and the app's fallback check.
// SIMULATION: every curve comes from our models for the chosen day; only the "reading" is simulated.
//   - site kW / kVA / cooling TR: the plan API's forecast for the same inputs the engineer saved on Tomorrow's plan (= how the hotel usually runs);
//   - habit per equipment: the plan's matched days last year (tools/export_plant_profiles.py; chiller kW/TR = ref.kwtr_ly, the plan's own yardstick);
//   - planned per equipment: the approved step (stage, setpoint, AHU times, laundry / water hours), priced with the plan's own kW/TR curve and
//     measured % per °C of setpoint (plan.ts kwtrPlan / chwPct);
//   - reading = curve value for the sim time (interpolated within the hour) x (1 + noise within ±2.5 %).
// An equipment follows habit until a person presses Apply on its approved step; nothing is applied automatically.
import { CHW_STD, CHW_FLOOR, chwPct, kwtrPlan, type Booking, type PlanDay, type PlanRef, type Tariff } from "../plan";
import type { SavedAction } from "../planlog";

export const NOISE = 0.025;
export const PEAK: [number, number] = [18, 22];
export const OFFPEAK: [number, number] = [23, 5];

export interface PlantIndex { ahu_event_kw: Record<string, number>; ahu_idle_kw: number; ch1_share_both: number; chw_supply_offset_c: number;
  laundry_connected_kw: number; water_connected_kw: number; ahu_rated_kw: Record<string, number>; source: string; note: string }
export interface PlantProfile { date: string; matched_days: string[]; habit_stage: string[]; laundry: number[]; water: number[]; ev: number[];
  kitchen_exhaust: number[]; lifts: number[]; rooms: number[]; ahu: number[] }
export interface Forecast { kw: number[]; kva: number[]; tr: number[]; temp: number[] }

/** Everything the sim needs for one day: the approved plan, the API forecast for its inputs, the matched-day profiles and the plan inputs file. */
export interface SimDay { date: string; forecast: Forecast; steps: SavedAction[]; bookings: Booking[]; profile: PlantProfile; index: PlantIndex;
  ref: PlanRef; tariff: Tariff; pf: number }

export type FaultType = "ahu_left_on" | "chw_low" | "peak_creep";
export interface Applied { stepId: string; kind: "apply" | "override"; by: string; at: string; simHour: number; value?: string | number; reason?: string }
export interface ActiveFault { type: FaultType; startedAt: number; by: string; at: string; fixedAt?: number; fixedBy?: string }
export interface SimState { applied: Record<string, Applied>; faults: ActiveFault[] }

export const FAULTS: Record<FaultType, { label: string; what: string; fixGroup: string }> = {
  ahu_left_on: { label: "Banquet AHU left on after event", fixGroup: "ahu",
    what: "The banquet AHU is not switched off at the planned time: it keeps drawing its event kW from the planned off time (event end + 1 h)." },
  chw_low: { label: "CHW set to 5.5 °C after a complaint", fixGroup: "chw",
    what: "Someone drops the chilled-water setpoint to 5.5 °C: chiller kW rises by the measured % per °C at this load." },
  peak_creep: { label: "Peak creep (laundry + AHU in 18–22)", fixGroup: "laundry",
    what: "Laundry (95 kW connected) and the banquet AHUs start inside the 18:00–22:00 peak window: site kVA climbs." },
};

// ---- equipment --------------------------------------------------------------------------------------------------------------
export type EquipId = "CH-1" | "CH-3" | "CH-2" | "CHW" | "AHU-BQ-A" | "AHU-BQ-B" | "LAUNDRY" | "HP-DHW" | "EVC";
export type MonitoredId = "KEF" | "ROOMS" | "LIFTS" | "FIRE";
export const CONTROLLED: { id: EquipId; name: string; sub: string }[] = [
  { id: "CH-1", name: "Chiller 1", sub: "300 TR screw" }, { id: "CH-3", name: "Chiller 3", sub: "150 TR scroll" },
  { id: "CH-2", name: "Chiller 2", sub: "300 TR screw" }, { id: "CHW", name: "CHW setpoint", sub: "leaving water" },
  { id: "AHU-BQ-A", name: "Banquet AHU-1", sub: "AHU-BQ-A · Hall A" }, { id: "AHU-BQ-B", name: "Banquet AHU-2", sub: "AHU-BQ-B · Hall B" },
  { id: "LAUNDRY", name: "Laundry", sub: "95 kW connected" }, { id: "HP-DHW", name: "Water heating", sub: "HP-DHW · 4 × 20 kW" },
  { id: "EVC", name: "EV chargers", sub: "EVC-1..4" },
];
/** Never controlled (CLAUDE.md guardrails): shown with readings, never with a button, never in a step. */
export const MONITORED: { id: MonitoredId; name: string; why: string }[] = [
  { id: "KEF", name: "Kitchen exhaust", why: "Must run whenever cooking" }, { id: "ROOMS", name: "Guest-room thermostats", why: "Guest comfort: guests decide" },
  { id: "LIFTS", name: "Lifts", why: "Life safety" }, { id: "FIRE", name: "Fire & life safety", why: "Life safety" },
];
export const isMonitored = (id: string) => MONITORED.some((m) => m.id === id) || /exhaust|thermostat|guest.?room|lift|elevator|fire|life.?safety/i.test(id);

export const hourOf = (t: string) => Number(t.slice(0, 2)) + (t.includes("next day") ? 24 : 0);
export function stepHours(a: { start: string; end: string }): number[] {
  const s = hourOf(a.start); let e = hourOf(a.end); if (e <= s) e += 24;
  const out: number[] = []; for (let h = s; h < e; h++) out.push(h); return out;
}
export const covers = (a: { start: string; end: string }, h: number) => stepHours(a).some((x) => x % 24 === h % 24 && (x < 24 || h < 24));
export function hallOf(a: { equipment: string }): string | null { const m = /Hall (A\+B|A|B)/.exec(a.equipment); return m ? m[1] : null; }
export function equipOf(a: SavedAction): EquipId[] {
  switch (a.group) {
    case "chillers": return ["CH-1", "CH-3"];
    case "chw": return ["CHW"];
    case "ahu": { const h = hallOf(a); return h === "A+B" ? ["AHU-BQ-A", "AHU-BQ-B"] : h === "B" ? ["AHU-BQ-B"] : ["AHU-BQ-A"]; }
    case "laundry": return ["LAUNDRY"];
    case "water": return ["HP-DHW"];
    case "ev": return ["EVC"];
    default: return [];
  }
}
/** src/plan_check.stage_of */
export const stageOf = (setting: string) => (setting.includes("together") ? "CH-1+CH-3" : setting.startsWith("CH-3") ? "CH-3" : "CH-1");

// ---- noise: deterministic, so a reading can be reproduced (tests) ----
function hash(s: string): number { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
/** Uniform in [-NOISE, +NOISE] for one equipment at one sim minute. */
export const noise = (key: string, date: string, minute: number) => ((hash(`${key}|${date}|${minute}`) / 4294967295) * 2 - 1) * NOISE;

const at = (xs: number[], t: number) => { const h = Math.min(23, Math.max(0, Math.floor(t))); const f = t - h; const b = xs[Math.min(23, h + 1)] ?? xs[h]; return xs[h] + (b - xs[h]) * (h >= 23 ? 0 : f); };
const inWin = (h: number, [a, b]: [number, number]) => (a < b ? a <= h && h < b : h >= a || h < b);

/** The step (approved) covering hour h for a group, with its application if a person applied it by sim time t. */
export function stepAt(day: SimDay, st: SimState, group: string, h: number, t: number, pick?: (a: SavedAction) => boolean) {
  const a = day.steps.find((x) => x.group === group && covers(x, h) && (!pick || pick(x)));
  const ap = a ? st.applied[a.id] : undefined;
  // an override to "habit" = the engineer decided not to carry the step out (reason logged): the equipment keeps running as usual
  return { step: a, applied: ap && ap.simHour <= t && !(ap.kind === "override" && ap.value === "habit") ? ap : undefined };
}
/** The fault of this type in effect at t. from(f): when its effect starts (default: when it was injected). */
const faultOn = (st: SimState, type: FaultType, t: number, from: (f: ActiveFault) => number = (f) => f.startedAt) =>
  st.faults.find((f) => f.type === type && t >= from(f) && (f.fixedAt === undefined || t < f.fixedAt));
// AHU left on: modelled as never switched off at the planned time, so it runs from the planned off time even when injected later.
// Peak creep: only inside the 18-22 window, and not before it was injected.
const creepFrom = (f: ActiveFault) => Math.max(PEAK[0], f.startedAt);

// ---- chillers and setpoint ----
export function setpointAt(day: SimDay, st: SimState, t: number): { value: number; source: string } {
  if (faultOn(st, "chw_low", t)) return { value: 5.5, source: "fault (demo): set to 5.5 °C after a complaint" };
  const { step, applied } = stepAt(day, st, "chw", Math.floor(t), t);
  if (step && applied) {
    const v = applied.kind === "override" ? Number(applied.value) : step.setpoint_c ?? CHW_STD;
    return { value: v, source: applied.kind === "override" ? `override by ${applied.by}` : `plan, applied by ${applied.by}` };
  }
  return { value: CHW_STD, source: "habit: standard 7.0 °C" };
}
export function chillersAt(day: SimDay, st: SimState, t: number, habitOnly = false) {
  const h = Math.min(23, Math.floor(t));
  const tr = at(day.forecast.tr, t);
  const { step, applied } = habitOnly ? { step: undefined, applied: undefined } : stepAt(day, st, "chillers", h, t);
  const habitStage = day.profile.habit_stage[h] === "none" ? "CH-3" : day.profile.habit_stage[h];
  let stage = habitStage, kwtr = day.ref.kwtr_ly[h] ?? kwtrPlan(tr, day.ref.curve) ?? day.ref.curve.values.at(-1)!;
  if (step && applied) {
    stage = applied.kind === "override" ? String(applied.value) : stageOf(step.setting);
    kwtr = (stage !== "CH-1+CH-3" ? kwtrPlan(tr, day.ref.curve) : null) ?? day.ref.kwtr_ly[h] ?? kwtr;
  }
  const sp = habitOnly ? CHW_STD : setpointAt(day, st, t).value;
  const total = tr * kwtr * (1 - chwPct(tr, day.ref) * (sp - CHW_STD));
  const share = day.index.ch1_share_both;
  const ch1 = stage === "CH-1" ? total : stage === "CH-3" ? 0 : total * share;
  return { tr, stage, kwtr, total, ch1, ch3: total - ch1, setpoint: sp, following: step && applied ? "plan" : "habit" };
}

// ---- banquet AHUs ----
function ahuUnit(day: SimDay, st: SimState, unit: "A" | "B", t: number, habitOnly = false): { kw: number; following: string; on: boolean } {
  let kw = 0, following = "habit", on = false;
  for (const b of day.bookings) {
    if (!(b.hall === unit || b.hall === "A+B")) continue;
    const share = b.hall === "A+B" ? 2 : 1;
    const ev = (day.index.ahu_event_kw[b.hall] ?? day.index.ahu_rated_kw[b.hall]) / share;
    const step = day.steps.find((a) => a.group === "ahu" && hallOf(a) === b.hall);
    const sh = Number(b.start.slice(0, 2)), eh = b.end === "23:59" ? 25 : Number(b.end.slice(0, 2)) + (Number(b.end.slice(3, 5)) > 0 ? 1 : 0);
    const onH = step ? hourOf(step.start) : Math.max(0, sh - 1);
    let off = step ? hourOf(step.end) : (eh <= sh ? eh + 24 : eh) + 1;
    const ap = step && !habitOnly ? st.applied[step.id] : undefined;
    const applied = ap && ap.simHour <= t;
    if (applied && ap!.kind === "override") off = hourOf(String(ap!.value));
    const style = b.hall === "A+B" ? "social" : "corporate";
    const overrun = (day.ref as PlanRef & { ahu_overrun_kwh: Record<string, number> }).ahu_overrun_kwh?.[style] ?? 0;
    const habitOff = off + overrun / (ev * share);                                  // last year: run on after the planned stop (hand mode)
    const left = !habitOnly && step && faultOn(st, "ahu_left_on", t, () => off);
    const end = left ? 48 : applied ? off : habitOff;
    if (t >= onH && t < end) { kw += ev; on = true; }
    if (applied) following = left ? "fault" : "plan";
    else if (left) following = "fault";
  }
  const creep = !habitOnly && faultOn(st, "peak_creep", t, creepFrom);
  if (creep && inWin(Math.floor(t), PEAK) && !on) {
    const hall = day.bookings.find((b) => b.hall === unit || b.hall === "A+B")?.hall;
    kw += hall ? (day.index.ahu_event_kw[hall] ?? 45) / (hall === "A+B" ? 2 : 1) : day.index.ahu_rated_kw[unit];
    on = true; following = "fault";
  }
  return { kw, following, on };
}

// ---- flexible loads ----
/** Laundry hours the approved step allows ("Run batches only 00:00–18:00, 22:00–00:00 (next day)"), src/plan_check.allowed_hours. */
export function allowedHours(setting: string): Set<number> {
  const out = new Set<number>();
  for (const m of setting.matchAll(/(\d\d):00(?: \(next day\))?–(\d\d):00( \(next day\))?/g)) {
    const s = Number(m[1]); const e = Number(m[2]) + (m[3] ? 24 : 0);
    for (let h = s; h < (e > s ? e : e + 24); h++) out.add(h);
  }
  return out;
}
/** Planned laundry: the habit profile with the batches that fell in blocked hours moved to the first allowed hours after them. */
export function plannedLaundry(habit: number[], setting: string): number[] {
  const ok = allowedHours(setting), out = [...habit];
  for (let h = 0; h < 24; h++) {
    if (ok.has(h) || out[h] <= 0) continue;
    let k = h + 1; while (k < 24 && !ok.has(k)) k++;
    if (k < 24) out[k] += out[h];
    out[h] = 0;
  }
  return out;
}
/** Planned water heating: boost above the day's floor in the 18–22 peak moved into the overnight 23:00 off-peak hour. */
export function plannedWater(habit: number[]): number[] {
  const floor = Math.min(...habit), out = [...habit];
  for (let h = PEAK[0]; h < PEAK[1]; h++) { const boost = out[h] - floor; if (boost > 0) { out[h] = floor; out[23] += boost; } }
  return out;
}
function flexAt(day: SimDay, st: SimState, group: "laundry" | "water" | "ev", t: number, habitOnly = false) {
  const h = Math.min(23, Math.floor(t));
  const habit = group === "laundry" ? day.profile.laundry : group === "water" ? day.profile.water : day.profile.ev;
  const { step, applied } = habitOnly ? { step: undefined, applied: undefined } : stepAt(day, st, group, h, t);
  let kw = at(habit, t), following = "habit";
  if (step && applied) {
    following = "plan";
    if (group === "laundry") kw = at(plannedLaundry(habit, step.setting), t);
    else if (group === "water") kw = at(plannedWater(habit), t);
    else kw = 0;                                                                       // EV: charging held back while the step runs
  }
  if (!habitOnly && group === "laundry" && faultOn(st, "peak_creep", t, creepFrom) && inWin(h, PEAK)) {
    kw = Math.max(kw, day.index.laundry_connected_kw); following = "fault";
  }
  return { kw, following };
}

// ---- one instant: every tile, and the main meter ----
export interface Snapshot {
  t: number; tr: number; setpoint: number; setpointSource: string; supply_c: number;
  equip: Record<EquipId, { kw: number; status: "ON" | "OFF" | "STAGED" | "OUT OF SERVICE"; following: string; setting: string }>;
  monitored: Record<MonitoredId, number>;
  kw: number; kva: number; habit_kw: number; habit_kva: number;
}
function rawAt(day: SimDay, st: SimState, t: number, habitOnly = false) {
  const c = chillersAt(day, st, t, habitOnly);
  const a = ahuUnit(day, st, "A", t, habitOnly), b = ahuUnit(day, st, "B", t, habitOnly);
  const l = flexAt(day, st, "laundry", t, habitOnly), w = flexAt(day, st, "water", t, habitOnly), e = flexAt(day, st, "ev", t, habitOnly);
  return { c, a, b, l, w, e, sum: c.total + a.kw + b.kw + l.kw + w.kw + e.kw };
}
/** Readings at sim time t (hours from midnight, 0..24). withNoise=false gives the underlying curve. */
export function snapshot(day: SimDay, st: SimState, t: number, withNoise = true): Snapshot {
  const m = Math.round(t * 60);
  const nz = (k: string) => (withNoise ? 1 + noise(k, day.date, m) : 1);
  const x = rawAt(day, st, t), hb = rawAt(day, st, t, true);
  const fkw = at(day.forecast.kw, t), fkva = at(day.forecast.kva, t);
  const kw = (fkw + x.sum - hb.sum) * nz("main");
  const kva = (fkva + (x.sum - hb.sum) / day.pf) * nz("main");          // kVA moves with kW at the site PF (plan.ts composeDay)
  const sp = setpointAt(day, st, t);
  const on = (v: number) => (v > 5 ? "ON" : "OFF") as "ON" | "OFF";
  const both = x.c.stage === "CH-1+CH-3";
  const prof = (xs: number[]) => at(xs, t);
  return {
    t, tr: x.c.tr * nz("tr"), setpoint: sp.value, setpointSource: sp.source, supply_c: sp.value + day.index.chw_supply_offset_c,
    equip: {
      "CH-1": { kw: x.c.ch1 * nz("CH-1"), status: x.c.ch1 > 0 ? (both ? "STAGED" : "ON") : "OFF", following: x.c.following, setting: x.c.stage },
      "CH-3": { kw: x.c.ch3 * nz("CH-3"), status: x.c.ch3 > 0 ? (both ? "STAGED" : "ON") : "OFF", following: x.c.following, setting: x.c.stage },
      "CH-2": { kw: 0, status: "OUT OF SERVICE", following: "—", setting: "Out of service (register)" },
      CHW: { kw: 0, status: "ON", following: sp.source.startsWith("fault") ? "fault" : sp.source.startsWith("habit") ? "habit" : "plan", setting: `${sp.value.toFixed(1)} °C` },
      "AHU-BQ-A": { kw: x.a.kw * nz("AHU-A"), status: x.a.on ? "ON" : "OFF", following: x.a.following, setting: x.a.on ? "Running" : "Off" },
      "AHU-BQ-B": { kw: x.b.kw * nz("AHU-B"), status: x.b.on ? "ON" : "OFF", following: x.b.following, setting: x.b.on ? "Running" : "Off" },
      LAUNDRY: { kw: x.l.kw * nz("LDY"), status: on(x.l.kw), following: x.l.following, setting: x.l.kw > 5 ? "Batches running" : "Idle" },
      "HP-DHW": { kw: x.w.kw * nz("DHW"), status: on(x.w.kw), following: x.w.following, setting: "Storage ≥ 60 °C daily" },
      EVC: { kw: x.e.kw * nz("EVC"), status: on(x.e.kw), following: x.e.following, setting: x.e.following === "plan" ? "Limited" : "Normal" },
    },
    monitored: { KEF: prof(day.profile.kitchen_exhaust) * nz("KEF"), ROOMS: prof(day.profile.rooms) * nz("ROOMS"), LIFTS: prof(day.profile.lifts) * nz("LIFTS"), FIRE: 0 },
    kw, kva, habit_kw: fkw, habit_kva: fkva,
  };
}

// ---- hourly meter rows (what /check reads; src/plan_check.check_day columns) ----
export interface MeterRow { timestamp: string; chiller_ch1_kw: number; chiller_ch3_kw: number; chillers_kw: number; chiller_load_tr: number; chw_setpoint_c: number;
  ahu_banquet_kw: number; laundry_kw: number; water_heating_kw: number; ev_chargers_kw: number; kva: number; total_kwh: number }
const r2 = (x: number) => Math.round(x * 100) / 100;
/** Hour h as metered at sim time `now`: a finished hour is read at its middle; the current hour at `now` (readings so far). */
export function hourRow(day: SimDay, st: SimState, h: number, now: number): MeterRow {
  const t = h < Math.floor(now) ? h + 0.5 : now;
  const s = snapshot(day, st, t);
  const e = s.equip;
  return { timestamp: `${day.date}T${String(h).padStart(2, "0")}:00`, chiller_ch1_kw: r2(e["CH-1"].kw), chiller_ch3_kw: r2(e["CH-3"].kw),
    chillers_kw: r2(e["CH-1"].kw + e["CH-3"].kw), chiller_load_tr: r2(s.tr), chw_setpoint_c: s.setpoint, ahu_banquet_kw: r2(e["AHU-BQ-A"].kw + e["AHU-BQ-B"].kw),
    laundry_kw: r2(e.LAUNDRY.kw), water_heating_kw: r2(e["HP-DHW"].kw), ev_chargers_kw: r2(e.EVC.kw), kva: r2(s.kva), total_kwh: r2(s.kw) };
}
export const CHECK_WINDOW_H = 3;
/** The hours sent to the plan check: the last CHECK_WINDOW_H simulated hours, but none before the last fix (an Apply or Clear fault), so a fix shows at once. */
export function checkWindow(now: number, lastFix: number | null): number[] {
  const h = Math.min(23, Math.floor(now));
  const from = Math.max(0, h - CHECK_WINDOW_H + 1, lastFix === null ? 0 : Math.min(h, Math.floor(lastFix)));
  const out: number[] = []; for (let k = from; k <= h; k++) out.push(k); return out;
}

// ---- cost so far: the plan's own pricing (plan.ts: (energy + FSA + duty) / PF per kWh, ToD peak surcharge and off-peak rebate per kVAh) ----
export function hourCost(kwh: number, h: number, tariff: Tariff, pf: number): number {
  const tod = inWin(h, PEAK) ? tariff.peak : inWin(h, OFFPEAK) ? tariff.offpeak : 0;
  return (kwh * (tariff.energy + tariff.fsa + tariff.duty)) / pf + (kwh / pf) * tod;
}
export function soFar(day: SimDay, st: SimState, now: number) {
  let kwh = 0, habitKwh = 0, inr = 0, habitInr = 0;
  for (let h = 0; h <= Math.min(23, Math.floor(now)); h++) {
    const frac = h < Math.floor(now) ? 1 : now - h;
    if (frac <= 0) continue;
    const row = hourRow(day, st, h, now);
    const hk = day.forecast.kw[h] * frac, ak = row.total_kwh * frac;
    kwh += ak; habitKwh += hk; inr += hourCost(ak, h, day.tariff, day.pf); habitInr += hourCost(hk, h, day.tariff, day.pf);
  }
  return { kwh, habitKwh, inr, habitInr };
}

// ---- guardrails for overrides (the store re-checks them: web/src/plant/store.ts) ----
export function overrideError(step: SavedAction | undefined, value: unknown): string | null {
  if (!step) return "That step is not in the approved plan.";
  if (step.group === "chw") {
    const v = Number(value);
    if (!Number.isFinite(v)) return "Enter a setpoint in °C, e.g. 7.0.";
    if (v < CHW_FLOOR) return `Refused: never below ${CHW_FLOOR} °C leaving water (guardrail). ${v} °C was not applied.`;
    if (v > 10) return "Refused: above 10 °C the guest areas run warm; keep 7.0–8.0 °C.";
  }
  if (step.group === "chillers" && !["CH-3", "CH-1", "CH-1+CH-3"].includes(String(value))) return "Pick CH-3, CH-1 or CH-1+CH-3 (CH-2 is out of service).";
  if (step.group === "ahu") {
    if (!/^\d{2}:00( \(next day\))?$/.test(String(value))) return "Enter the AHU off time as a whole hour, e.g. 19:00.";
    if (hourOf(String(value)) <= hourOf(step.start)) return "The off time must be after the on time.";
  }
  if (["laundry", "water", "ev"].includes(step.group) && value !== "habit") return "For this step an override can only keep the equipment running as usual (habit), with a reason.";
  return null;
}
