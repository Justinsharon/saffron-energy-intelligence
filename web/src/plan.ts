// Gurugram operating plan in the browser: the same rules as src/operating_plan.py, line for line, so the plan updates when bookings
// change. RECOMMEND ONLY: a person approves and carries out every action. tests/test_plan_parity.py checks Python and this file give
// the same actions and ₹ (within 1 %) on sample days. Inputs: web/public/data/plan/<date>.json (tools/export_plan_inputs.py).
// Plan savings are a separate stream from alert savings: never add them together.

export const CH3_MAX = 130, CH1_MAX = 280, PAIR_MAX = 430;   // TR: CH-3 alone, CH-1 alone, CH-1 + CH-3 (CH-2 unavailable)
export const TR_MARGIN = 1.1;
export const CHW_STD = 7.0, CHW_RESET = 8.0, CHW_FLOOR = 6.5;
export const RESET_BELOW_C = 24;
export const SETPOINT_PCT_PER_C = 0.035;
const PEAK: [number, number] = [18, 22], OFFPEAK: [number, number] = [23, 5];
export const DEMAND_WATCH_KVA = 920, CD_KVA = 1000;
const LAUNDRY_KW = 95;
const AHU: Record<Hall, string> = { A: "AHU-BQ-A", B: "AHU-BQ-B", "A+B": "AHU-BQ-A and AHU-BQ-B" };
export const EXCLUDED = ["kitchen exhaust", "exhaust", "make-up air", "thermostat", "guest room", "guest-room", "lift", "elevator", "fire", "life-safety", "life safety"];

const GUARD = {
  chillers: "Recommendation only: the duty engineer stages the chillers. CH-3 leads below 130 TR, CH-1 alone up to 280 TR, both up to 430 TR; CH-2 is out of service. Never two chillers below 130 TR.",
  chw: "Recommendation only. Never below 6.5 °C leaving water. Go back to 7.0 °C at once if a guest area runs warm (guest rooms 22–25 °C).",
  ahu: "Recommendation only: the banquet team switches the AHUs. On 1 h before the event (never more than 2 h), off 1 h after it ends.",
  laundry: "Recommendation only: the laundry supervisor schedules batches. Flexible load; no effect on guests.",
  water: "Recommendation only. The daily ≥ 60 °C storage cycle (Legionella) must complete; if it has not by 05:00 it runs regardless.",
  ev: "Recommendation only. Throttling is allowed above 920 kVA site demand (guide); tell affected guests first.",
};

export type Hall = "A" | "B" | "A+B";
// Jaipur / Goa bookings name the venue (src/operating_plan.plan_site; venues from each hotel's events calendar, served by the plan API)
export interface Booking { hall: Hall | string; start: string; end: string; guests: number }
export type PlanSite = "GGN" | "JAI" | "GOA";
// the two-chiller guardrail line per hotel = its smaller chiller's capacity (equipment register; src/operating_plan.TWO_MIN_TR, checked by
// tests/test_site_plan.py); Gurugram's is CH-3's 130 TR band
export const TWO_MIN_TR: Record<PlanSite, number> = { GGN: CH3_MAX, JAI: 200, GOA: 150 };
export const FILTRATION_MIN_H = 8;
interface Resp { start: number[]; end: number[]; during: number }
export interface Tariff { energy: number; fsa: number; duty: number; peak: number; offpeak: number; penalty: number }
export interface PlanRef { kwtr_ly: (number | null)[]; laundry_peak_kwh: number; water_peak_kwh: number; ev_kw: number[];
  curve: { edges: number[]; values: number[] }; ahu_overrun_kwh: { corporate: number; social: number }; matched_days: string[];
  chw_pct_per_c?: number[] }      // measured chiller power saved per °C of setpoint, per load band (recalibration.fit)
export interface PlanDay {
  date: string; site: string; template: string; template_tmax: number; pf: number; tariff: Tariff;
  defaults: { rooms: number; guests: number; covers: number; events: Booking[] };
  base: { kw: number[]; kva: number[]; tr: number[]; temp: number[] };
  resp: { kw_per_room: number[]; kw_per_guest: number[]; kw_per_cover: number[]; kw_per_c: number[]; tr_per_c: number[]; tr_per_room: number[]; tr_per_guest: number[] };
  banquet: Record<Hall, { kw: Resp; tr: Resp; reference: string; style: string }>;
  ref: PlanRef;
}
export interface Action {
  kind: "plan"; group: "chillers" | "chw" | "ahu" | "laundry" | "water" | "ev" | "lighting" | "pool" | "demand"; start: string; end: string; equipment: string; setting: string;
  reason: string; saving_inr: number; guardrail: string; min_tr?: number; max_tr?: number; setpoint_c?: number; on_h?: number; start_h?: number;
  site?: PlanSite; estimate_inr?: number; counted?: boolean; verifiable?: string; run_hours?: number; venue?: string;
}

const f0 = (x: number) => x.toFixed(0);
export const hh = (h: number) => `${String(h % 24).padStart(2, "0")}:00${h >= 24 ? " (next day)" : ""}`;
export const stage = (tr: number) => { const t = tr * TR_MARGIN; return t <= CH3_MAX ? "CH-3" : t <= CH1_MAX ? "CH-1" : "CH-1+CH-3"; };
export function kwtrPlan(tr: number, curve: PlanRef["curve"]): number | null {
  if (tr * TR_MARGIN > CH1_MAX) return null;
  for (let i = 1; i < curve.edges.length; i++) if (tr <= curve.edges[i]) return curve.values[i - 1];
  return curve.values[curve.values.length - 1];
}
/** Chiller power saved per °C of warmer chilled water at this load: measured per band, else the guide's 3.5 %. */
export function chwPct(tr: number, ref: PlanRef): number {
  const p = ref.chw_pct_per_c;
  if (!p || !p.length) return SETPOINT_PCT_PER_C;
  for (let i = 1; i < ref.curve.edges.length; i++) if (tr <= ref.curve.edges[i]) return p[i - 1];
  return p[p.length - 1];
}
const inWin = (h: number, [a, b]: [number, number]) => (a < b ? a <= h && h < b : h >= a || h < b);
export function windows<T>(keys: T[]): [number, number, T][] {
  const out: [number, number, T][] = []; let s = 0;
  for (let h = 1; h <= keys.length; h++) if (h === keys.length || keys[h] !== keys[s]) { out.push([s, h, keys[s]]); s = h; }
  return out;
}
export function parseBooking(b: Booking): [number, number] {
  const sh = Number(b.start.slice(0, 2)), eh = Number(b.end.slice(0, 2)), em = Number(b.end.slice(3, 5));
  let e = b.end === "23:59" ? 25 : eh + (em > 0 ? 1 : 0);
  if (e <= sh) e += 24;
  return [sh, e];
}

// ---- forecast for the day with the user's inputs ----
export function banquetDelta(h: number, s: number, e: number, r: Resp): number {
  const de = h - e, ds = h - s;
  if (de >= -3 && de <= 2) return r.end[de + 3];
  if (ds >= -3 && ds <= 2) return r.start[ds + 3];
  return s < h && h < e ? r.during : 0;
}
/** Temperature: an hourly forecast (temps, 24 values, e.g. Open-Meteo) or a shift to a daily max (tmax). */
export interface Inputs { rooms?: number; guests?: number; covers?: number; tmax?: number; temps?: number[] | null; bookings?: Booking[] }
export const MAX_DT = 15;     // °C: responses are local slopes; further than this from the template is clamped
export function composeDay(day: PlanDay, inp: Inputs = {}) {
  const b = day.base, r = day.resp, pf = day.pf, bookings = inp.bookings ?? [], dfl = day.defaults;
  const dr = (inp.rooms ?? dfl.rooms) - dfl.rooms;
  const dg = (inp.guests ?? dfl.guests ?? 0) - (dfl.guests ?? 0);
  const dc = (inp.covers ?? dfl.covers) - dfl.covers;
  const shift = (inp.tmax ?? day.template_tmax) - day.template_tmax;
  const kw: number[] = [], tr: number[] = [], kva: number[] = [], temp: number[] = [];
  for (let h = 0; h < 24; h++) {
    const dt = Math.max(-MAX_DT, Math.min(MAX_DT, inp.temps ? inp.temps[h] - b.temp[h] : shift));
    let k = b.kw[h] + r.kw_per_room[h] * dr + r.kw_per_guest[h] * dg + r.kw_per_cover[h] * dc + r.kw_per_c[h] * dt;
    let t = b.tr[h] + r.tr_per_room[h] * dr + r.tr_per_guest[h] * dg + r.tr_per_c[h] * dt;
    for (const bk of bookings) {
      const [s, e] = parseBooking(bk); const q = day.banquet[bk.hall as Hall];
      k += (bk.guests / 100) * banquetDelta(h, s, e, q.kw);
      t += (bk.guests / 100) * banquetDelta(h, s, e, q.tr);
    }
    kw.push(k); tr.push(Math.max(t, 0)); kva.push(b.kva[h] + (k - b.kw[h]) / pf); temp.push(b.temp[h] + dt);
  }
  return { kw, tr, kva, temp };
}

// ---- the plan ----
export function planDay(hourlyTr: number[], hourlyKva: number[], tempC: number[], bookings: Booking[], pf: number, ref: PlanRef, tariff: Tariff): Action[] {
  const rate = (tariff.energy + tariff.fsa + tariff.duty) / pf;
  const acts: Action[] = [];
  const st = hourlyTr.map(stage);
  for (const [s, e, key] of windows(st)) {
    const trs = hourlyTr.slice(s, e);
    let sav = 0;
    for (let h = s; h < e; h++) {
      const p = kwtrPlan(hourlyTr[h], ref.curve), ly = ref.kwtr_ly[h];
      if (p != null && ly != null) sav += hourlyTr[h] * Math.max(0, ly - p) * rate;
    }
    const lo = Math.min(...trs), hi = Math.max(...trs);
    const cap = hi * TR_MARGIN > PAIR_MAX ? " Forecast load is above what CH-1 + CH-3 can carry (430 TR): expect warm spaces; plan comfort messaging." : "";
    const setting = ({ "CH-3": "CH-3 alone (150 TR scroll chiller)", "CH-1": "CH-1 alone (300 TR screw chiller)", "CH-1+CH-3": "CH-1 + CH-3 together" } as Record<string, string>)[key];
    const why = ({ "CH-3": `Cooling load ${f0(lo)}–${f0(hi)} TR stays under 130 TR with a 10 % margin, so the small chiller carries it alone at its best efficiency.`,
      "CH-1": `Cooling load ${f0(lo)}–${f0(hi)} TR is too much for CH-3 (130 TR with margin) but within CH-1 alone (280 TR); one chiller at good part load beats two lightly loaded.`,
      "CH-1+CH-3": `Cooling load ${f0(lo)}–${f0(hi)} TR needs more than one chiller (280 TR with margin).` } as Record<string, string>)[key] + cap;
    acts.push({ kind: "plan", group: "chillers", start: hh(s), end: hh(e), equipment: "Chillers (CH-1, CH-3)", setting, reason: why, saving_inr: sav, guardrail: GUARD.chillers, min_tr: lo, max_tr: hi });
  }

  const sp = Array.from({ length: 24 }, (_, h) => (tempC[h] < RESET_BELOW_C && stage(hourlyTr[h]) !== "CH-1+CH-3" ? CHW_RESET : CHW_STD));
  for (const [s, e, v] of windows(sp)) {
    let sav = 0;
    const pcts = hourlyTr.slice(s, e).map((x) => chwPct(x, ref));
    if (v > CHW_STD) for (let h = s; h < e; h++) sav += hourlyTr[h] * (kwtrPlan(hourlyTr[h], ref.curve) ?? 0) * pcts[h - s] * (v - CHW_STD) * rate;
    const t = tempC.slice(s, e);
    const lo = Math.min(...pcts) * 100, hi = Math.max(...pcts) * 100;
    const span = hi - lo < 0.05 ? `${lo.toFixed(1)} %` : `${lo.toFixed(1)}–${hi.toFixed(1)} %`;
    const src = ref.chw_pct_per_c?.length ? "measured on these chillers" : "engineering guide";
    const why = v > CHW_STD ? `Outdoor ${f0(Math.min(...t))}–${f0(Math.max(...t))} °C and one chiller running: warmer chilled water still holds comfort and saves about ${span} of chiller power per °C at this load (${src}).`
      : "Standard setting: outdoor 24 °C or warmer, or two chillers needed.";
    acts.push({ kind: "plan", group: "chw", start: hh(s), end: hh(e), equipment: "Chilled-water supply setpoint", setting: `${v.toFixed(1)} °C`, reason: why, saving_inr: sav, guardrail: GUARD.chw, setpoint_c: v });
  }

  for (const bk of bookings) {
    const [s, e] = parseBooking(bk);
    const on = Math.max(s - 1, s - 2, 0), off = e + 1;
    const ly = ref.ahu_overrun_kwh[bk.hall === "A+B" ? "social" : "corporate"];
    acts.push({ kind: "plan", group: "ahu", start: hh(on), end: hh(off), equipment: `Banquet AHUs, Hall ${bk.hall} (${AHU[bk.hall as Hall]})`, setting: `On at ${hh(on)}, off at ${hh(off)}`,
      reason: `Event in Hall ${bk.hall} ${bk.start}–${bk.end} (${bk.guests} guests): pre-cool 1 h before, stop 1 h after. Last year the AHUs ran on about ${f0(ly)} kWh after similar events ended (left in hand mode).`,
      saving_inr: ly * rate, guardrail: GUARD.ahu, on_h: on, start_h: s });
  }

  const blocked = Array.from({ length: 24 }, (_, h) => inWin(h, PEAK) || hourlyKva[h] + LAUNDRY_KW / pf > DEMAND_WATCH_KVA);
  const ok = windows(blocked).filter(([, , v]) => !v).map(([s, e]) => [s, e] as [number, number]);
  const byDemand = blocked.map((b, h) => b && !inWin(h, PEAK)).filter(Boolean).length;
  if (ok.length) {
    const txt = ok.map(([s, e]) => `${hh(s)}–${hh(e)}`).join(", ");
    acts.push({ kind: "plan", group: "laundry", start: hh(ok[0][0]), end: hh(ok[ok.length - 1][1]), equipment: "Laundry (washer-extractors, dryers)", setting: `Run batches only ${txt}`,
      reason: `Keep laundry out of the 18:00–22:00 peak tariff${byDemand ? ` and out of ${byDemand} hour(s) where site demand plus laundry would pass 920 kVA` : ""}. Last year on similar days about ${f0(ref.laundry_peak_kwh)} kWh of laundry ran in the peak window.`,
      saving_inr: (ref.laundry_peak_kwh / pf) * tariff.peak, guardrail: GUARD.laundry });
  }

  acts.push({ kind: "plan", group: "water", start: hh(OFFPEAK[0]), end: hh(OFFPEAK[1] + 24), equipment: "Heat-pump water heaters (HP-DHW)",
    setting: "Heat storage 23:00–05:00 (off-peak); finish the ≥ 60 °C cycle by 05:00",
    reason: `Overnight heating is cheaper (off-peak rebate) and keeps the evening peak clear. Last year on similar days about ${f0(ref.water_peak_kwh)} kWh of boost heating ran in the 18:00–22:00 peak.`,
    saving_inr: (ref.water_peak_kwh / pf) * (tariff.peak - tariff.offpeak), guardrail: GUARD.water });

  for (const [s, e, v] of windows(hourlyKva.map((k) => k > DEMAND_WATCH_KVA))) {
    if (!v) continue;
    const pk = Math.max(...hourlyKva.slice(s, e));
    const relief = Math.min(Math.max(0, pk - CD_KVA), Math.max(...ref.ev_kw.slice(s, e)) / pf);
    acts.push({ kind: "plan", group: "ev", start: hh(s), end: hh(e), equipment: "EV chargers (EVC-1..4)", setting: "Limit charging while site demand is above 920 kVA",
      reason: `Site demand forecast up to ${f0(pk)} kVA (contract 1,000 kVA).${relief > 0 ? " Holding EV charging back keeps the month's maximum demand down." : ""}`,
      saving_inr: relief * tariff.penalty, guardrail: GUARD.ev });
  }
  validate(acts);
  return acts;
}

/** Guardrails: excluded equipment, setpoint below 6.5 °C, two chillers below 130 TR, AHU on more than 2 h early. Throws on a breach. */
export function validate(acts: Action[]): void {
  for (const a of acts) {
    const text = `${a.equipment} ${a.setting}`.toLowerCase();
    const bad = EXCLUDED.find((w) => text.includes(w));
    if (bad) throw new Error(`plan touches excluded equipment (${bad}): ${a.equipment}`);
    if (a.group === "chw" && (a.setpoint_c ?? CHW_STD) < CHW_FLOOR) throw new Error("setpoint below 6.5 °C");
    const two = TWO_MIN_TR[a.site ?? "GGN"] ?? CH3_MAX;
    if (a.group === "chillers" && a.setting.includes("together") && (a.min_tr ?? 0) < two) throw new Error(`two chillers planned below ${two} TR`);
    if (a.group === "pool" && (a.run_hours ?? 99) < FILTRATION_MIN_H) throw new Error(`pool filtration under ${FILTRATION_MIN_H} h a day`);
    if (a.group === "ahu" && (a.start_h ?? 0) - (a.on_h ?? 0) > 2) throw new Error("banquet AHU on more than 2 h before the event");
    if (!Number.isFinite(a.saving_inr)) throw new Error("saving is not a number");
  }
}

/** One call for the page: the day's forecast with the team's inputs, and the plan on it. */
export function planFor(day: PlanDay, inp: Inputs = {}) {
  const f = composeDay(day, inp);
  const actions = planDay(f.tr, f.kva, f.temp, inp.bookings ?? [], day.pf, day.ref, day.tariff);
  return { forecast: f, actions, total_inr: actions.reduce((s, a) => s + a.saving_inr, 0) };
}

// ---- peak risk on the plan's own forecast: src/peak_risk.assess with the calibration exported in plan/index.json ----
export interface RiskCal { bias: number; upper_factor: number; ratios: number[]; stack_increment: number; stack_basis: string;
  stack_table: { load: string; actual_kw: number; typical_kw: number; extra_kw: number }[]; cd: number; warn: number; watch_frac: number }
export type Level = "OK" | "STACKING WATCH" | "WARNING" | "BREACH RISK";
export function riskFor(kva: number[], cal: RiskCal) {
  const raw = Math.max(...kva), hour = kva.indexOf(raw);
  const peak = raw * cal.bias, upper = peak * cal.upper_factor, stack = peak + cal.stack_increment;
  const p = cal.ratios.length >= 10 ? cal.ratios.filter((r) => r >= cal.cd / peak).length / cal.ratios.length : null;
  const level: Level = upper >= cal.cd || stack >= cal.cd ? "BREACH RISK" : upper >= cal.warn ? "WARNING" : stack >= cal.watch_frac * cal.cd ? "STACKING WATCH" : "OK";
  return { raw, hour, peak, upper, stack, p_exceed: p, level };
}

/** Stable id for an action within a day's plan (decisions are stored against it). */
export const actionId = (a: Action) => `${a.group}|${a.start}|${a.equipment}`;
const ORDER = ["chillers", "chw", "ahu", "lighting", "pool", "laundry", "ev", "water", "demand"];
/** Timeline order: by start time (next-day starts last), then by kind. */
export function byTime(acts: Action[]): Action[] {
  const h = (a: Action) => Number(a.start.slice(0, 2)) + (a.start.includes("next day") ? 24 : 0);
  return [...acts].sort((x, y) => h(x) - h(y) || ORDER.indexOf(x.group) - ORDER.indexOf(y.group));
}
export const TAG: Record<Action["group"], string> = { chillers: "CH", chw: "CHW", ahu: "AHU-BQ", laundry: "LDY", water: "DHW", ev: "EVC", lighting: "LTG", pool: "POOL", demand: "kVA" };
