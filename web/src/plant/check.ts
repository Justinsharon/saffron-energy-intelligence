// Plan vs actual in the browser: the Gurugram rules of src/plan_check.check_day, line for line, run on the Plant Room's simulated meter rows.
// Used ONLY as the fallback when the plan API's /check does not answer within 8 s (or is an older build that ignores `meters`), so the
// Plant Room demo still shows the same alert. tests/test_plant_room.py checks this port gives the same statuses and alerts as Python.
// Recommend only: this checks, it controls nothing. Simulated readings never feed savings or bills.
import { chwPct, kwtrPlan, CHW_STD, type PlanRef, type Tariff } from "../plan";
import type { Alert } from "../data";
import type { MeterRow } from "./model";

const RUN_KW = 5, AHU_IDLE_KW = 10, FLEX_KW = 5, EV_KW = 1, DIGEST_BELOW_INR = 2000, CD_KVA = 1000;
const PEAK: [number, number] = [18, 22];
const EQUIP_COL: Record<string, keyof MeterRow> = { chillers: "chillers_kw", chw: "chw_setpoint_c", ahu: "ahu_banquet_kw", laundry: "laundry_kw",
  water: "water_heating_kw", ev: "ev_chargers_kw" };
const PLANNED: Record<string, string> = { "CH-3": "Chiller 3 only", "CH-1": "Chiller 1 only", "CH-1+CH-3": "Chillers 1 and 3" };
const ACTUAL: Record<string, string> = { "CH-1+CH-3": "both ran", "CH-1": "Chiller 1 ran", "CH-3": "Chiller 3 ran", none: "no chiller ran" };

export interface CheckAction { id?: string; group: string; start: string; end: string; setting: string; equipment?: string; saving_inr?: number;
  setpoint_c?: number; decision?: string; decision_reason?: string }
export interface LocalStep { id: string; group: string; status: string; hours_checked: number; hours_differed: string[]; extra_kwh: number; extra_inr: number }

const hourOf = (t: string) => Number(t.slice(0, 2)) + (t.includes("next day") ? 24 : 0);
const stageOf = (s: string) => (s.includes("together") ? "CH-1+CH-3" : s.startsWith("CH-3") ? "CH-3" : "CH-1");
const actualStage = (a: number, b: number) => { const o1 = a > RUN_KW, o3 = b > RUN_KW; return o1 && o3 ? "CH-1+CH-3" : o1 ? "CH-1" : o3 ? "CH-3" : "none"; };
const hm = (h: number) => `${String(h % 24).padStart(2, "0")}:00${h >= 24 ? " (next day)" : ""}`;
const inWin = (h: number, [a, b]: [number, number]) => (a < b ? a <= h && h < b : h >= a || h < b);
const endTxt = (t: string) => (t === "00:00 (next day)" ? "midnight" : t.replace(" (next day)", ""));
const windowTxt = (a: CheckAction) => (a.start === "00:00" && a.end === "00:00 (next day)" ? "all day" : `${a.start}–${endTxt(a.end)}`);
function allowedHours(setting: string): Set<number> {
  const out = new Set<number>();
  for (const m of setting.matchAll(/(\d\d):00(?: \(next day\))?–(\d\d):00( \(next day\))?/g)) {
    const s = Number(m[1]), e = Number(m[2]) + (m[3] ? 24 : 0);
    for (let h = s; h < (e > s ? e : e + 24); h++) out.add(h);
  }
  return out;
}
const addH = (date: string, h: number) => { const d = new Date(`${date}T00:00:00Z`); d.setUTCHours(d.getUTCHours() + h); return d.toISOString().slice(0, 16); };

function title(a: CheckAction, dev: number[], r: MeterRow): string {
  const g = a.group, first = hm(dev[0]), last = hm(dev[dev.length - 1] + 1);
  const until = a.start === "00:00" && a.end === "00:00 (next day)" ? "all day" : `until ${endTxt(a.end)}`;
  if (g === "chillers") return `Plan said ${PLANNED[stageOf(a.setting)]} ${until}; ${ACTUAL[actualStage(r.chiller_ch1_kw, r.chiller_ch3_kw)].replace(" ran", "")} ran from ${first}`;
  if (g === "chw") return `Plan said chilled water ${a.setting} ${until}; it was set colder from ${first}`;
  if (g === "ahu") return `Plan said banquet AHUs off at ${endTxt(a.end)}; they ran ${first}–${last}`;
  if (g === "laundry") return "Plan said no laundry in the 18:00–22:00 peak; it ran from " + first;
  if (g === "water") return "Plan said water heating overnight; it boosted in the evening peak from " + first;
  return `Plan said limit EV charging ${a.start}–${a.end}; the chargers drew power from ${first}`;
}

/** src/plan_check.check_day for Gurugram on the given rows (only rows at or before asOf count). Returns the steps and PLAN_DEVIATION alerts. */
export function checkDay(date: string, actions: CheckAction[], rows: MeterRow[], asOf: string, ref: PlanRef, tariff: Tariff, pf: number) {
  const cut = asOf.slice(0, 13) + ":00";
  const byT = new Map(rows.map((r) => [r.timestamp.slice(0, 16), r]));
  const rate = (tariff.energy + tariff.fsa + tariff.duty) / pf;
  const row = (h: number) => { const t = addH(date, h); return t <= cut ? byT.get(t) ?? null : null; };
  const steps: LocalStep[] = [], alerts: Alert[] = [];
  for (const a of actions) {
    const g = a.group, s = hourOf(a.start); let e = hourOf(a.end); if (e <= s) e += 24;
    const sid = a.id ?? `${g}|${a.start}|${a.equipment ?? ""}`;
    if (a.decision !== "approve") { steps.push({ id: sid, group: g, status: a.decision === "skip" ? "Skipped" : "Not approved", hours_checked: 0, hours_differed: [], extra_kwh: 0, extra_inr: 0 }); continue; }
    let span: number[] = [], okH = new Set<number>();
    const rng = (x: number, y: number) => Array.from({ length: Math.max(0, y - x) }, (_, i) => x + i);
    if (g === "laundry") { okH = allowedHours(a.setting); span = rng(0, 24); }
    else if (g === "water") span = rng(PEAK[0], PEAK[1]);
    else if (g === "ahu") span = rng(Math.max(0, s - 3), e + 12);
    else span = rng(s, e);
    let boostFloor: number | null = null;
    if (g === "water") { const v = rng(0, 24).map(row).filter((r): r is MeterRow => !!r).map((r) => r.water_heating_kw); boostFloor = v.length ? Math.min(...v) : null; }
    const dev: number[] = [], hrs: number[] = [], perHour: Record<number, number> = {};
    let extraKwh = 0, extraInr = 0;
    for (const h of span) {
      const r = row(h);
      if (!r) continue;
      const v = r[EQUIP_COL[g]];
      if (v === null || v === undefined || Number.isNaN(v)) continue;
      hrs.push(h);
      let bad = false, kwh = 0, inr = 0;
      if (g === "chillers") {
        const want = stageOf(a.setting), got = actualStage(r.chiller_ch1_kw, r.chiller_ch3_kw), tr = r.chiller_load_tr;
        const normal = kwtrPlan(tr, ref.curve);
        if (got !== want && got !== "none" && want !== "CH-1+CH-3") { bad = true; kwh = Math.max(0, r.chillers_kw - tr * (normal ?? r.chillers_kw / Math.max(tr, 1))); inr = kwh * rate; }
      } else if (g === "chw") {
        const want = a.setpoint_c ?? CHW_STD, got = r.chw_setpoint_c;
        if (got < want - 0.05) { bad = true; kwh = r.chillers_kw * chwPct(r.chiller_load_tr, ref) * (want - got); inr = kwh * rate; }
      } else if (g === "ahu") {
        if (!(s - 1 <= h && h < e) && r.ahu_banquet_kw > AHU_IDLE_KW) { bad = true; kwh = r.ahu_banquet_kw; inr = kwh * rate; }
      } else if (g === "laundry") {
        if (!okH.has(h) && r.laundry_kw > FLEX_KW) { bad = true; kwh = r.laundry_kw; inr = inWin(h % 24, PEAK) ? (kwh / pf) * tariff.peak : 0; }
      } else if (g === "water") {
        const boost = r.water_heating_kw - (boostFloor ?? 0);
        if (boost > FLEX_KW) { bad = true; kwh = boost; inr = (boost / pf) * (tariff.peak - tariff.offpeak); }
      } else if (g === "ev") {
        if (r.ev_chargers_kw > EV_KW) { bad = true; kwh = r.ev_chargers_kw; inr = Math.min(kwh / pf, Math.max(0, r.kva - CD_KVA)) * tariff.penalty; }
      }
      if (bad) { dev.push(h); extraKwh += kwh; extraInr += inr; perHour[h] = kwh; }
    }
    const n = hrs.length, d = dev.length;
    const status = n === 0 ? "Not yet due" : d === 0 ? "Followed" : d >= 2 && d >= n / 2 ? "Not followed" : "Partly";
    steps.push({ id: sid, group: g, status, hours_checked: n, hours_differed: dev.map(hm), extra_kwh: Math.round(extraKwh * 10) / 10, extra_inr: Math.round(extraInr * 10) / 10 });
    if (status === "Not followed") {
      const t0 = addH(date, dev[0]), t1 = addH(date, dev[d - 1] + 1), alertAt = addH(date, dev[1] + 1);
      const ev = `Planned: ${a.setting} (${windowTxt(a)}). The meters differ in ${d} of ${n} hours checked (${dev.slice(0, 8).map(hm).join(", ")}${d > 8 ? "…" : ""}): about ${Math.round(extraKwh).toLocaleString("en-IN")} kWh more than the plan`;
      const ttl = title(a, dev, row(dev[0])!);
      const win = rows.filter((r) => r.timestamp.slice(0, 16) <= cut);
      alerts.push({ id: `PD-${date}-${g}-${a.start.slice(0, 2)}`, site: "GGN", hotel: "Gurugram", rule: "PLAN_DEVIATION", title: ttl, severity: "Medium",
        equipment: a.equipment ?? "", start: t0, end: t1, alert_time: alertAt, flagged_h: d, duration_h: d, detect_lag_h: dev[1] + 1 - dev[0],
        excess_kwh: Math.round(extraKwh * 10) / 10, cost: Math.round(extraInr * 10) / 10, per_hour: Math.round((extraInr / Math.max(d, 1)) * 10) / 10,
        per_day: Math.round(extraInr * 10) / 10, cost_basis: "per_occurrence", cost_note: "", channel: extraInr > DIGEST_BELOW_INR ? "Alert" : "Daily digest",
        repeat_30d: 0, inferred_note: "", evidence: ev, cause: "An approved plan step was not carried out on the floor (or the plan changed without being updated).",
        action: "Ask the duty team why; either carry out the step or record a reason with Skip on Tomorrow's plan.", guardrail: "recommend",
        guard_text: "Recommendation only. A person approves.", post_hoc: false, text: `Gurugram · ${ttl}. ${ev}.`,
        chart: { t: win.map((r) => r.timestamp.slice(0, 13)), actual: win.map((r) => r.total_kwh),
                 baseline: win.map((r) => Math.round((r.total_kwh - (perHour[Number(r.timestamp.slice(11, 13))] ?? 0)) * 10) / 10),
                 signals: { [EQUIP_COL[g]]: win.map((r) => r[EQUIP_COL[g]] as number) } } });
    }
  }
  return { steps, alerts };
}
