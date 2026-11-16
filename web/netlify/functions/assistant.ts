// Energy assistant (port of src/assistant.py). Rules, in order:
// 1. A fixed guard refuses unsafe control requests before any model call (T10).
// 2. Claude answers only through tools that return numbers our models exported (data/*.json).
// 3. Every number in the reply must appear in the tool results or the question; otherwise one rewrite, then a template answer.
// 4. Without ANTHROPIC_API_KEY the same tools are routed by keywords.
// 5. Live: the live feed (Oct 2026 - Sep 2027, simulated meters) is cut at the current IST hour with the feed's own code (src/feedcore.ts);
//    alerts not yet raised and bills not yet issued are invisible to every tool.
import Anthropic from "@anthropic-ai/sdk";
import origAlerts from "./data/alerts_lite.json";
import origBills from "./data/bills.json";
import origChanges from "./data/bill_changes.json";
import liveAlertsFull from "./data/live_feed/alerts.json";
import liveAlerts from "./data/live_feed/alerts_lite.json";
import liveFaults from "./data/live_feed/faults.json";
import liveBills from "./data/live_feed/bills.json";
import liveChanges from "./data/live_feed/bill_changes.json";
import hGGN from "./data/live_feed/hourly_GGN.json";
import hJAI from "./data/live_feed/hourly_JAI.json";
import hGOA from "./data/live_feed/hourly_GOA.json";
import { feedFor, istNow as istNowFull, issued } from "../../src/feedcore";
import { byTime, planFor, type PlanDay } from "../../src/plan";
import { checkActions, planKey, view, type Entry } from "../../src/planlog";
import { configured as gistReady, readJSON } from "../lib/gist";
import days from "./data/forecast_days.json";
import whatif from "./data/forecast_whatif.json";
import savings from "./data/savings.json";

type J = Record<string, any>;
const HOURLY: J = { GGN: hGGN, JAI: hJAI, GOA: hGOA };
const RECON: J[] = [...(origBills as J).recon, ...(liveBills as J).recon];
// What the tools may see at this moment: bills issued and alerts raised by now; a running alert is cut to the hours so far.
const billsNow = () => RECON.filter((r) => issued(r, istNowFull()));
const changesNow = (): J => {
  const ok = new Set(billsNow().map((r) => `${r.site}|${r.month}`)); const out: J = { ...(origChanges as J) };
  for (const [k, v] of Object.entries(liveChanges as J)) if (ok.has(`${v.site}|${v.a}`) && ok.has(`${v.site}|${v.b}`)) out[k] = v;
  return out;
};
const alertsNow = (): J[] => {
  const now = istNowFull();
  return [...(origAlerts as J[]), ...(liveAlerts as J[])].filter((a) => a.alert_time <= now).map((a) => {
    if (a.end <= now) return a;
    const ran = Math.max(0, (Date.parse(now + ":00Z") - Date.parse(a.start + ":00Z")) / 3.6e6);
    return { ...a, end: now, duration_h: ran, cost: a.cost_basis === "per_day" ? a.per_hour * Math.min(a.flagged_h, ran) : 0,
             evidence: "still running; today_status has the readings so far", ongoing: true };
  });
};
const MODEL = process.env.PS12_MODEL || "claude-sonnet-5-5";
const SITES: Record<string, string> = { GGN: "Gurugram", JAI: "Jaipur", GOA: "Goa" };

// ---------- 1. guard ----------
const NEVER: [string, string][] = [
  ["kitchen exhaust", "The kitchen extract fans must run whenever anything is cooking, for fire and air safety, so they are never switched off automatically. A safer option: ask the chief engineer to link the fans to kitchen opening hours, so they stop 30 minutes after the last order. I can show the nights the fans ran after the kitchen closed."],
  ["extract fan", "The kitchen extract fans must run whenever anything is cooking, for fire and air safety, so they are never switched off automatically. A safer option: ask the chief engineer to link the fans to kitchen opening hours, so they stop 30 minutes after the last order. I can show the nights the fans ran after the kitchen closed."],
  ["thermostat", "Guest-room thermostats are not controlled by this product (guest comfort 22–25 °C, guest override 20–26 °C). The only allowed change is a setback for unsold rooms through the PMS, approved by a person."],
  ["fire", "Fire pumps, pressurisation fans and life-safety systems are never controlled or recommended for switching off."],
  ["life safety", "Life-safety systems are never controlled or recommended for switching off."],
  ["lift", "Lifts are never controlled by this product."],
  ["elevator", "Lifts are never controlled by this product."],
];
const CONTROL = /\b(auto|automatic|automatically|switch(ed)? off|turn(ed)? off|shut( down| off)?|disable|control|stop|schedule off)\b/;
function guard(q: string): string | null {
  const ql = q.toLowerCase();
  for (const [k, msg] of NEVER) if (ql.includes(k) && CONTROL.test(ql)) return "I can't do that. " + msg;
  const m = ql.match(/(chw|chilled[- ]water|setpoint)[^0-9]{0,40}(\d+(?:\.\d+)?)\s*°?\s*c?/);
  if (m && parseFloat(m[2]) < 6.5) return "I can't recommend that. Chilled water should never be set below 6.5 °C. The standard is 7 °C, and 8 °C is fine on cool, quiet days.";
  return null;
}

// ---------- 2. tools ----------
function site(x?: string): string {
  if (!x) return "GGN";
  const s = x.trim().toLowerCase();
  for (const [c, n] of Object.entries(SITES)) if (s === c.toLowerCase() || n.toLowerCase().startsWith(s)) return c;
  return "GGN";
}
const r0 = (x: number) => Math.round(x);
const LEVEL: Record<string, string> = { "BREACH RISK": "risk of going over the power limit", WARNING: "close to the power limit", "STACKING WATCH": "watch the afternoon", OK: "comfortably under the limit" };
const WASTE: Record<string, string> = {
  AHU_HAND_MODE: "banquet hall cooling left on after events", HEAT_COOL_FIGHT: "heating and cooling running together", KITCHEN_EXHAUST_OFF_HOURS: "kitchen extract fans left on after closing",
  LIGHTING_LEFT_ON: "event lighting left on", LAUNDRY_IN_PEAK: "laundry in the evening peak", POOL_PUMP_OFF_SCHEDULE: "pool pumps running round the clock",
  POWER_FACTOR_DROP: "capacitor panel fault", CHILLER_STAGING_LOW_LOAD: "two chillers running when one would do", STAGING_KWTR: "two chillers likely running when one would do",
  CHILLER_PART_LOAD_INEFFICIENCY: "chillers running inefficiently at low load", CHW_SETPOINT_LOW: "chilled water set colder than needed", DEMAND_NEAR_CONTRACT: "power demand over the contracted limit",
  EV_CHARGER_NIGHT_ON: "EV charger on overnight", RESIDUAL_UNEXPLAINED: "extra use with no single cause",
};
function riskOut(f: J) {
  const r = f.risk;
  return { forecast_peak_kva: r0(r.peak), peak_hour: r.hour, upper90_kva: r0(r.upper), chance_above_1000_kva_pct: r.p_exceed == null ? null : r0(r.p_exceed * 100),
    if_laundry_water_heating_and_banquet_cooling_overlap_kva: r0(r.stack_peak), based_on: r.stack_basis.replace("average of earlier breach days", "the days the limit was broken"),
    outlook: LEVEL[r.level] ?? r.level, contracted_limit_kva: 1000,
    shift_plan: f.plan ? f.plan.map((p: J) => ({ load: p.load === "Banquet AHUs" ? "Banquet hall cooling" : p.load, action: String(p.action).replace("banquet-hall AHU", "banquet hall cooling"), frees_up_kva: r0(p.relief_kva) })) : null };
}
function plainMeasure(m: string): string {
  if (m.startsWith("Act on detected")) return "fix the waste the alerts find";
  if (m.startsWith("Hold PF")) return "upgrade the capacitor panel so the bill stops charging for wasted power";
  if (m.startsWith("Keep PF")) return "repair capacitor faults within hours";
  if (m.startsWith("Right-size")) return m.replace(/Right-size contract demand (\d[\d,]*) → (\d[\d,]*) kVA.*/, "lower the contracted power limit from $1 to $2 kVA");
  if (m.startsWith("Dim")) return "dim corridor and outdoor lighting after midnight";
  if (m.startsWith("Avoid contract")) return "stay under the contracted power limit on hot afternoons";
  if (m.startsWith("Shift flexible")) return "move laundry, water heating and EV charging out of the evening peak";
  if (m.startsWith("CHW reset")) return "run chilled water at 8 °C on cool, quiet days";
  if (m.startsWith("VFDs")) return "fit speed controls to the chilled-water pumps (investment)";
  return m;
}
const PLAIN_DRIVER: Record<string, string> = { Weather: "weather", Occupancy: "guests in house", Events: "events", Calendar: "days in the month", Anomalies: "waste and faults (incl. capacitor panel)", Demand: "peak-demand charges", Diesel: "diesel generator", "Tariff mix": "time-of-day pricing", Unexplained: "not explained" };
// Live context, set per request: today's date in India and where the site's own static files live.
let ORIGIN = "";
// The plan API on Cloud Run (CLAUDE.md "API"); called directly from the function (the /api proxy is for the browser).
const PLAN_API = process.env.PLAN_API_URL || "https://saffron-api-579804303171.asia-south1.run.app";
const istToday = () => new Date(Date.now() + 5.5 * 3.6e6).toISOString().slice(0, 10);
const addDays = (d: string, k: number) => new Date(Date.parse(d + "T00:00:00Z") + k * 864e5).toISOString().slice(0, 10);
async function ggnTmax(date: string): Promise<number | null> {
  try {
    const r = await fetch(`https://api.open-meteo.com/v1/forecast?latitude=28.46&longitude=77.03&daily=temperature_2m_max&timezone=Asia%2FKolkata&forecast_days=16`);
    const j = await r.json(); const k = (j.daily?.time ?? []).indexOf(date); return k >= 0 ? j.daily.temperature_2m_max[k] : null;
  } catch { return null; }
}

const TOOLS: Record<string, { fn: (a: J) => J | Promise<J>; desc: string; params: Record<string, string> }> = {
  forecast_upcoming: {
    desc: "Gurugram peak power demand for tomorrow or another upcoming date (real weather forecast), with any conference the user mentions; contract-demand risk and what to move.",
    params: { date: "string YYYY-MM-DD, optional (default tomorrow)", conference_guests: "integer, optional", max_temp_c: "string number, optional: only if the user gives a temperature" },
    fn: async (a) => {
      const date = a.date || addDays(istToday(), 1);
      let d: J;
      try { const r = await fetch(`${ORIGIN}/data/live/${date}.json`); if (!r.ok) throw new Error(); d = await r.json(); }
      catch { return { error: `No forecast prepared for ${date} yet (forecasts cover the coming weeks).` }; }
      const fc = a.max_temp_c ? Number(a.max_temp_c) : await ggnTmax(date);
      const t0 = Math.round(fc ?? d.template_tmax);
      const t = Math.min(d.temps[d.temps.length - 1], Math.max(d.temps[0], t0));
      const gIn = Number(a.conference_guests) || 0;
      const g = d.guests.reduce((b: number, x: number) => (Math.abs(x - gIn) < Math.abs(b - gIn) ? x : b), 0);
      const c = d.grid[`${t}|${g}`];
      return { hotel: "Gurugram", date, top_temperature_c: t, temperature_source: a.max_temp_c ? "given by you" : fc != null ? "weather forecast" : "typical for the time of year",
        conference_guests: g, note: g !== gIn ? "guest count rounded to the nearest 100" : undefined, ...riskOut({ risk: c.risk, plan: c.plan }) };
    },
  },
  operating_plan: {
    desc: "Operating plan for one hotel (Gurugram, Jaipur or Goa) for today, tomorrow or a date up to two weeks ahead: timed steps (Gurugram: chillers, chilled-water setting, banquet air handlers, laundry, water heating, EV chargers; Jaipur / Goa: chiller staging, chilled-water setting (shown, not counted: no setpoint meter), event lighting, pool filtration (Goa), laundry, demand watch), each with its ₹ saving and whether it has been approved. If the team has not saved a plan for that day, returns the suggested plan for the usual bookings.",
    params: { day: "string: today / tomorrow / YYYY-MM-DD, optional (default tomorrow)", part_of_day: "string: morning / afternoon / evening / night, optional",
              hotel: "string: GGN / JAI / GOA or the hotel's name, optional (default Gurugram)" },
    fn: async (a) => {
      const hs = String(a.hotel ?? "GGN").toUpperCase();
      const site = hs.startsWith("JAI") ? "JAI" : hs.startsWith("GOA") ? "GOA" : "GGN";
      const hotel = SITES[site as keyof typeof SITES];
      const today = istToday();
      const raw = String(a.day ?? "tomorrow").toLowerCase();
      const date = /^\d{4}-\d{2}-\d{2}$/.test(raw) ? raw : raw.startsWith("today") || raw === "tonight" ? today : addDays(today, 1);
      const PART: Record<string, [number, number]> = { morning: [6, 12], afternoon: [12, 17], evening: [17, 22], night: [22, 30] };
      const part = PART[String(a.part_of_day ?? "").toLowerCase()];
      const hr = (t: string) => Number(t.slice(0, 2)) + (t.includes("next day") ? 24 : 0);
      const overlaps = (s: string, e: string) => !part || (hr(s) < part[1] && hr(e) > part[0]) || (part[0] === 22 && hr(s) < 6);
      let saved = null as ReturnType<typeof view> | null;
      if (gistReady()) { try { saved = view(date, (await readJSON<Record<string, Entry>>("plans.json", {}))[planKey(date, site)], "gist"); } catch { saved = null; } }
      if (saved?.plan) {
        const p = saved.plan;
        const steps = p.actions.map((x) => { const ed = saved!.edits[x.id]; const d = saved!.decisions[x.id];
          return { from: ed?.start ?? x.start, to: ed?.end ?? x.end, what: x.equipment, setting: x.setting, why: x.reason, saving_inr: r0(x.saving_inr),
                   status: d?.event === "approve" ? `approved by ${d.by}` : d?.event === "skip" ? `skipped by ${d.by}: ${d.reason}` : "not yet approved", time_changed: !!ed }; });
        return { hotel, date, plan: `saved by ${p.by} at ${p.at}`, bookings: p.inputs.bookings, notes: p.inputs.notes || undefined,
                 total_saving_inr: r0(p.total_inr), steps: steps.filter((x) => overlaps(x.from, x.to)), part_of_day: a.part_of_day || undefined };
      }
      // not saved: the same source as the page - the plan API (models on the usual inputs), else the browser rules on the exported inputs
      const suggest = (src: string, actions: J[], total: number, extra: J) => ({ hotel, date,
        plan: `not saved yet: this is the suggested plan for the usual rooms and covers, with no ${site === "GGN" ? "banquet" : "event"} bookings entered (${src})`, total_saving_inr: r0(total),
        steps: byTime(actions as any).filter((x) => overlaps(x.start, x.end)).map((x) => ({ from: x.start, to: x.end, what: x.equipment, setting: x.setting, why: x.reason, saving_inr: r0(x.saving_inr),
          counted: x.counted === false ? false : undefined, status: "suggested" })),
        part_of_day: a.part_of_day || undefined, ...extra });
      try {
        const r = await fetch(`${PLAN_API}/plan`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ date, site }), signal: AbortSignal.timeout(4000) });
        const j = await r.json();
        if (r.status === 422) return { error: j.error };
        if (r.ok) return suggest("plan service", j.actions, j.total_saving_inr, { weather: j.inputs_used?.weather, how_inputs_were_read: j.notes });
      } catch { /* fall back to the browser rules below (Gurugram only) */ }
      if (site !== "GGN") return { error: `The planning service did not answer; ${hotel}'s plan comes from it only. Try again in a minute.` };
      let day: PlanDay;
      try { const r = await fetch(`${ORIGIN}/data/plan/${date}.json`); if (!r.ok) throw new Error(); day = await r.json(); }
      catch { return { error: `No plan inputs for ${date} (plans cover the next few weeks).` }; }
      const tmax = await ggnTmax(date);
      const res = planFor(day, tmax != null ? { tmax } : {});
      return suggest("offline estimate: the plan service was not reachable", res.actions, res.total_inr, { top_temperature_c: Math.round(tmax ?? day.template_tmax) });
    },
  },
  monthly_report: {
    desc: "Monthly report for the general manager and finance (any month with an issued bill, Oct 2025 onward): the three hotels' bills vs last month and the same month last year, what drove the change, savings (verified from the daily plan, from acting on alerts, and the Option C total), the bill check, and the top problems. As of the day the bill was issued.",
    params: { month: "string YYYY-MM, optional (default: the latest month with a bill)" },
    fn: async (a) => {
      const bills = billsNow();
      const months = [...new Set(bills.map((r) => r.month))].sort();
      const m = a.month && months.includes(a.month) ? a.month : a.month ? null : months.at(-1);
      if (!m) return { error: `No bill has been issued for ${a.month} yet. Reports exist for ${months[0]} to ${months.at(-1)}.` };
      const add = (x: string, k: number) => { const [y, mo] = x.split("-").map(Number); return new Date(Date.UTC(y, mo - 1 + k, 1)).toISOString().slice(0, 7); };
      const prev = add(m, -1), ly = add(m, -12);
      const row = (s: string, mm: string) => bills.find((r) => r.site === s && r.month === mm);
      const issued = row("GGN", m)?.bill_issued?.slice(0, 10) ?? `${add(m, 1)}-05`;
      const asOf = `${issued}T09:00`;
      const tot = (mm: string) => Object.keys(SITES).reduce((x, s) => x + (row(s, mm)?.billed_total ?? 0), 0);
      const ch = changesNow();
      const drivers: J = {};
      for (const s of Object.keys(SITES)) { const c = ch[`${s}|${prev}|${m}`]; if (c) for (const [k, v] of Object.entries(c.groups as J)) drivers[PLAIN_DRIVER[k] ?? k] = r0((drivers[PLAIN_DRIVER[k] ?? k] ?? 0) + (v as number)); }
      const al = [...(origAlerts as J[]), ...(liveAlerts as J[])].filter((x) => x.alert_time <= asOf && x.start.slice(0, 7) === m && x.cost > 0);
      const top = al.sort((x, y) => y.cost - x.cost).slice(0, 5).map((x) => ({ hotel: x.hotel, problem: WASTE[x.rule] ?? x.title, inr: r0(x.cost), status: x.end <= asOf ? "resolved" : "still running" }));
      let plan: J | null = null;
      if (m >= "2026-10") {
        // all three hotels' plans (saved plans from the shared log, each hotel checked on its own meters), summed
        let all: Record<string, Entry> = {};
        if (gistReady()) { try { all = await readJSON<Record<string, Entry>>("plans.json", {}); } catch { all = {}; } }
        const rs = await Promise.all(Object.keys(SITES).map(async (s) => {
          const saved: Record<string, unknown[]> = {};
          for (const [k, e] of Object.entries(all)) { const d = k.slice(0, 10); if (d.startsWith(m) && k === planKey(d, s)) { const x = checkActions(view(d, e, "gist")); if (x.length) saved[d] = x; } }
          try { const r = await fetch(`${PLAN_API}/savings`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ month: m, site: s, as_of: asOf, saved }), signal: AbortSignal.timeout(15000) });
            return r.ok ? [s, await r.json()] as const : null; } catch { return null; }
        }));
        const ok = rs.filter((x): x is readonly [string, J] => !!x);
        if (ok.length) plan = { verified_inr: r0(ok.reduce((x, [, j]) => x + j.totals.verified_inr, 0)), planned_inr: r0(ok.reduce((x, [, j]) => x + j.totals.planned_inr, 0)),
          missed_inr: r0(ok.reduce((x, [, j]) => x + j.totals.missed_inr, 0)), days: Math.max(...ok.map(([, j]) => j.totals.days)), note: ok[0][1].honesty,
          hotels: ok.map(([s]) => SITES[s as keyof typeof SITES]), by_hotel: Object.fromEntries(ok.map(([s, j]) => [SITES[s as keyof typeof SITES], r0(j.totals.verified_inr)])) };
      }
      let optionC: J | null = null;
      if (m >= "2026-10") {
        let kwh = 0, inr = 0;
        for (const s of Object.keys(SITES)) {
          const h = HOURLY[s]; let A = 0, B = 0;
          h.t.forEach((t: string, i: number) => { if (t.slice(0, 7) === m && t <= asOf.slice(0, 13) && !h.f[i]) { A += h.a[i]; B += h.b[i]; } });
          const r = row(s, m); const rate = r ? r.billed_total / Math.max(r.billed_kvah * r.pf, 1) : 0;
          kwh += B - A; inr += (B - A) * rate;
        }
        optionC = { kwh_below_adjusted_baseline: r0(kwh), inr: r0(inr) };
      }
      const alertInr = r0(al.reduce((x, y) => x + y.cost, 0));
      return { month: m, as_of: issued, hotels: Object.fromEntries(Object.entries(SITES).map(([s, name]) => [name, { bill_inr: r0(row(s, m)?.billed_total ?? 0),
        last_month_inr: row(s, prev) ? r0(row(s, prev)!.billed_total) : null, same_month_last_year_inr: row(s, ly) ? r0(row(s, ly)!.billed_total) : null,
        bill_check: row(s, m)?.status, billed_minus_our_meter_inr: r0(row(s, m)?.billed_minus_corrected ?? 0) }])),
        total_inr: r0(tot(m)), change_vs_last_month_inr: tot(prev) ? r0(tot(m) - tot(prev)) : null, change_vs_last_year_inr: tot(ly) ? r0(tot(m) - tot(ly)) : null,
        what_drove_the_change_inr: Object.keys(drivers).length ? drivers : "no comparison available",
        savings: { from_the_daily_plan_verified: plan ?? (m < "2026-10" ? "daily plans started in October 2026" : "the planning service did not answer"),
          from_acting_on_alerts_inr: alertInr, option_c_total: optionC ?? "not computed for months before October 2026 here; see the Monthly report page",
          rule: "a rupee counts as a plan saving or an alert saving, never both" },
        top_problems: top, simulated_meters: m >= "2026-10" };
    },
  },
  today_status: {
    desc: "Right now at one or all hotels, from the live feed (simulated meters) up to the current hour in India: energy used today vs expected, today's peak power demand, problems running now with their cost per day and action, meter faults, and the latest bill received.",
    params: { site: "string: GGN/JAI/GOA or hotel name, optional (default all three)" },
    fn: (a) => {
      const now = istNowFull();
      const sites = a.site ? [site(a.site)] : Object.keys(SITES);
      return { as_of_india_time: now.replace("T", " "), source: "live feed from simulated meters (readings up to the current hour only)",
        hotels: sites.map((s) => {
          const f = feedFor(s as any, now, 24, { hourly: HOURLY[s], alerts: liveAlertsFull as any, faults: liveFaults as any, recon: RECON as any });
          const t = f.today;
          const last = f.readings.t.length - 1;
          return { hotel: SITES[s], latest_reading_hour: last >= 0 ? f.readings.t[last].replace("T", " ") + ":00" : null,
            latest_hour_kw: last >= 0 ? r0(f.readings.a[last]) : null, latest_hour_expected_kw: last >= 0 ? r0(f.readings.b[last]) : null,
            used_today_kwh: r0(t.used_kwh), expected_today_kwh: r0(t.expected_kwh),
            today_vs_expected_pct: t.expected_kwh > 0 ? Math.round((t.used_kwh / t.expected_kwh - 1) * 1000) / 10 : null,
            peak_power_demand_today_kva: t.peak_kva == null ? null : r0(t.peak_kva), peak_hour: t.peak_hour,
            contracted_power_limit_kva: s === "GGN" ? 1000 : s === "JAI" ? 700 : 600,
            problems_now: f.open_alerts.filter((x) => x.channel === "Alert").map((x) => ({ problem: WASTE[x.rule] ?? x.title, since: x.start.replace("T", " "),
              hours_so_far: Math.round(x.duration_h), inr_per_day: x.cost_basis === "per_day" ? r0(x.per_day) : null,
              inr_so_far: x.cost_basis === "per_day" ? r0(x.cost) : null, action: x.action })),
            meter_faults_now: f.faults_now.map((x) => ({ since: x.start.replace("T", " "), what: x.kind })),
            latest_bill: f.latest_bill ? { month: f.latest_bill.month, total_inr: r0(f.latest_bill.billed_total), check: f.latest_bill.status,
                                           issued: f.latest_bill.bill_issued ?? "on file" } : null };
        }) };
    },
  },
  explain_bill_change: {
    desc: "Split the change between two monthly bills of one hotel into weather, occupancy, events, calendar, anomalies (incl. PF), demand, diesel, tariff mix. Months as YYYY-MM.",
    params: { site: "string: GGN/JAI/GOA or hotel name", month_a: "string YYYY-MM", month_b: "string YYYY-MM" },
    fn: (a) => {
      const s = site(a.site); const [x, y] = [a.month_a, a.month_b].sort();
      const c = changesNow()[`${s}|${x}|${y}`];
      if (!c) return { error: "No comparison for those months: either a bill has not been issued yet, or the months are in different data years (Oct 2025 – Sep 2026, and the live feed from Oct 2026)." };
      return { hotel: SITES[s], month_a: x, month_b: y, bill_a_inr: r0(c.bill_a), bill_b_inr: r0(c.bill_b), change_inr: r0(c.delta),
        change_by_driver_inr: Object.fromEntries(Object.entries(c.groups).map(([k, v]) => [PLAIN_DRIVER[k] ?? k, v])), detail_inr: Object.fromEntries(c.lines.map((l: J) => [l.driver, r0(l.inr)])),
        context: { hottest_hour_c_before: c.context.tmax_A, hottest_hour_c_after: c.context.tmax_B, cooling_need_ratio: Math.round(c.context.cdh_B / Math.max(c.context.cdh_A, 1) * 10) / 10,
          room_nights_before: c.context.rooms_A, room_nights_after: c.context.rooms_B, event_guests_before: c.context.event_guests_A, event_guests_after: c.context.event_guests_B,
          highest_power_draw_kva_before: c.context.md_A, highest_power_draw_kva_after: c.context.md_B },
        waste_found_kwh: Object.fromEntries(Object.entries(c.waste_kwh_b).map(([k, v]) => [WASTE[k] ?? k, v])) };
    },
  },
  bill_reconciliation: {
    desc: "Issued bill vs tariff rebuild vs meter, with status (Reconciled / Meter fault / Provisional).",
    params: { site: "string", month: "string YYYY-MM, optional" },
    fn: (a) => {
      const s = site(a.site);
      const rows = billsNow().filter((r: J) => r.site === s && (!a.month || r.month === a.month))
        .map((r: J) => ({ month: r.month, status: r.status, billed_total: r0(r.billed_total), corrected_total: r0(r.corrected_total), billed_minus_corrected: r0(r.billed_minus_corrected), md_kva: r.md_kva, pf: r.pf, pf_source: r.pf_source, note: r.note }));
      return rows.length ? { hotel: SITES[s], rows } : { hotel: SITES[s], rows, error: `No bill for ${a.month ?? "that month"} has been issued yet.` };
    },
  },
  list_alerts: {
    desc: "Detected waste alerts with evidence, ₹ and action, largest ₹ first.",
    params: { site: "string, optional", date_from: "YYYY-MM-DD optional", date_to: "YYYY-MM-DD optional", top: "integer, optional" },
    fn: (a) => {
      let x = alertsNow();
      if (a.site) x = x.filter((q) => q.site === site(a.site));
      if (a.date_from) x = x.filter((q) => q.end >= a.date_from);
      if (a.date_to) x = x.filter((q) => q.start <= a.date_to + "T23:59");
      x = [...x].sort((p, q) => q.cost - p.cost).slice(0, Number(a.top) || 8);
      return { n: x.length, alerts: x.map((q) => ({ id: q.id, hotel: q.hotel, title: q.title, severity: q.severity, start: q.start, still_running: !!q.ongoing, hours: Math.round(q.duration_h * 10) / 10,
        inr: r0(q.cost), inr_per_day: q.cost_basis === "per_day" ? r0(q.per_day) : null, problem: WASTE[q.rule] ?? q.title, meter_readings: q.evidence, action: q.action })) };
    },
  },
  forecast_day: {
    desc: "Gurugram day-ahead peak-kVA forecast and contract-demand risk for a date.",
    params: { date: "YYYY-MM-DD" },
    fn: (a) => {
      const f = (days as J)[a.date];
      if (!f) return { error: "No forecast for that date (data covers 8 Oct 2025 – 30 Sep 2026, Gurugram only)." };
      return { hotel: "Gurugram", date: a.date, actual_peak_kva: f.actual ? r0(Math.max(...f.actual)) : null, ...riskOut(f) };
    },
  },
  forecast_scenario: {
    desc: "Gurugram what-if for tomorrow: weekday with a given max temperature and conference size; contract-demand risk and shift plan.",
    params: { max_temp_c: "string number, e.g. 40", conference_guests: "integer, optional" },
    fn: (a) => {
      const w = whatif as J;
      const t = Math.min(46, Math.max(30, Math.round(Number(a.max_temp_c) || 40)));
      const g = Math.min(600, Math.max(0, Math.round((Number(a.conference_guests) || 0) / 50) * 50));
      const f = w.grid[`${t}|${g}`];
      return { hotel: "Gurugram", scenario: `weekday, max ${t} °C, conference ${g} guests 09:00-18:00 (guest count rounded to the nearest 50)`, ...riskOut(f) };
    },
  },
  savings_plan: {
    desc: "Sized savings measures (energy / ToD / demand) with safety notes. Two totals: from operations, and with one capital item (pump VFDs, needs investment).",
    params: {},
    fn: () => {
      const s = savings as J, t = s.totals as J;
      const by: J = {}; for (const m of s.measures) by[m.category] = r0((by[m.category] ?? 0) + m.inr);
      return { operations_inr: r0(t.operations_inr), operations_pct: t.operations_pct, with_capital_inr: r0(t.with_capital_inr), with_capital_pct: t.with_capital_pct,
        capital_item: "pump speed controls (VFDs): needs investment; payback needs a supplier quote", target_pct: "8-12", by_category_inr: by,
        measures: s.measures.map((m: J) => ({ hotel: m.hotel, measure: plainMeasure(m.measure), kind: ({ Energy: "use less", ToD: "use at cheaper times", Demand: "lower peak charges", Capital: "needs investment" } as J)[m.category] ?? m.category, inr: r0(m.inr), how_sure: String(m.confidence).startsWith("High") ? "measured" : String(m.confidence).startsWith("Medium") ? "estimated" : "rough estimate", safety: m.safety, ...(m.payback ? { payback: m.payback } : {}) })) };
    },
  },
};
const schemas = Object.entries(TOOLS).map(([name, t]) => ({
  name, description: t.desc,
  input_schema: { type: "object" as const, properties: Object.fromEntries(Object.entries(t.params).map(([k, v]) => [k, { type: v.startsWith("integer") ? "integer" : "string", description: v }])),
    required: Object.entries(t.params).filter(([, v]) => !v.includes("optional")).map(([k]) => k) },
}));

const SYSTEM = `You are the energy assistant for Saffron Suites (fictional hotels: Gurugram, Jaipur, Goa; data Oct 2025 - Sep 2026; tariffs are illustrative).
Users are duty engineers, the chief engineer, the GM and finance. Answer using ONLY numbers returned by the tools - never compute, add up, subtract, total, round differently,
estimate or invent numbers (a sum of several drivers is NOT allowed unless a tool returned it); quote them as given (you may format with ₹ and thousands separators).
If the tools do not cover the question, say what the app can show instead. Be brief: lead with the answer, then 3-6 short points with the ₹ drivers. Plain text, no headings.
Write for hotel managers and engineers, not data scientists: plain business English, no jargon. Never use words like model, baseline, residual, anomaly label,
post-hoc, held-out, Shapley, kVAh, MD, CD, ToD, PF, APFC, CHW, AHU, BMS, TR or kW/TR without explaining them in everyday words (say "peak power demand", "contracted power limit",
"evening peak hours", "capacitor panel", "chilled water", "air handlers", "building control system"). Name drivers as the tools do. Never print tool field names, codes or capitalised labels such as BREACH RISK; say "risk of going over the power limit".
Don't mention the power factor by name; say "the capacitor panel fault made the utility bill for more electricity than was used". Use "chilled water set too cold", not "setpoint".
You only recommend; a person approves every action. Never suggest automatic control of kitchen exhaust, guest-room thermostats, lifts or life-safety,
and never a chilled-water setpoint below 6.5 °C. Questions about tomorrow or a coming date use forecast_upcoming (real weather forecast). forecast_scenario is a what-if for a hot weekday in May; forecast_day is for past dates.
Questions about right now, today, the latest readings or what is wrong at the moment use today_status (live feed, simulated meters, up to the current hour).
Questions about what to set or do today or tomorrow (chillers, chilled water, laundry, water heating, banquet air handlers, EV chargers, event lighting, pool pumps) use operating_plan with the hotel asked about (default Gurugram); say whether the step is approved or only suggested. For Jaipur and Goa the chilled-water step is never counted in ₹ (no setpoint meter).
Requests to summarise or report a month (for the GM or finance) use monthly_report.`;
const system = () => `${SYSTEM}\nNow is ${istNowFull().replace("T", " ")} (India). Meter data: Oct 2025 – Sep 2026 is the original sample year; from 1 Oct 2026 it is a live feed from simulated meters, available up to the current hour only. Bills are available once issued (5th of the following month); say so if asked about a later one.`;

// ---------- 3. number check ----------
function numbers(t: string): number[] {
  const out: number[] = [];
  for (const m of t.matchAll(/(?<![A-Za-z0-9])(\d[\d,]*\.?\d*)\s*(lakh|l\b|cr|crore)?/gi)) {
    const s = m[1].replace(/,/g, "").replace(/\.$/, ""); if (!s) continue;
    let v = parseFloat(s); const u = (m[2] || "").toLowerCase();
    if (u === "lakh" || u === "l") v *= 1e5; else if (u === "cr" || u === "crore") v *= 1e7;
    out.push(v);
  }
  return out;
}
function unverified(answer: string, facts: string, q: string): number[] {
  const known = [...numbers(facts), ...numbers(q)];
  return numbers(answer).filter((v) => !(v <= 31 || (v >= 2000 && v <= 2100)) && !known.some((k) => Math.abs(v - Math.abs(k)) <= Math.max(1, Math.abs(v) * 0.006)));
}

// ---------- 4. answer ----------
function route(q: string): [string, J][] {
  const ql = q.toLowerCase();
  const s = Object.entries(SITES).find(([c, n]) => ql.includes(n.toLowerCase()) || new RegExp(`\\b${c.toLowerCase()}\\b`).test(ql))?.[0] ?? "GGN";
  const M = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
  // a month without a year means its latest issued occurrence (e.g. "October" = Oct 2026 once that bill is in, else Oct 2025)
  const have = new Set(billsNow().map((r) => r.month));
  const ym = [...ql.matchAll(/\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b(?:\s+(20\d\d))?/g)].map((m) => {
    const k = String(M.indexOf(m[1]) + 1).padStart(2, "0");
    if (m[2]) return `${m[2]}-${k}`;
    return [2027, 2026, 2025].map((y) => `${y}-${k}`).find((x) => have.has(x)) ?? `${Number(k) >= 10 ? 2025 : 2026}-${k}`;
  });
  if (/chiller|chilled|setpoint|plan\b|laundry|water heat|air handler|ahu|ev charg|lighting|pool|what should (i|we) (set|do|run)/.test(ql) && /tomorrow|today|tonight|morning|afternoon|evening|night/.test(ql) && !/bill/.test(ql)) {
    const part = ["morning", "afternoon", "evening", "night"].find((p) => ql.includes(p)) ?? (ql.includes("tonight") ? "night" : undefined);
    return [["operating_plan", { day: ql.includes("tomorrow") ? "tomorrow" : "today", part_of_day: part, hotel: s }]];
  }
  const tm = ql.match(/(\d{2}(?:\.\d)?)\s*°?\s*c\b/);
  if (tm && (ql.includes("tomorrow") || ql.includes("what if"))) {
    const g = ql.match(/(\d{2,4})\s*(?:-|\s)?(?:guest|people|pax|delegate)/);
    return [["forecast_scenario", { max_temp_c: tm[1], conference_guests: g ? Number(g[1]) : ql.includes("conference") ? 300 : 0 }]];
  }
  if (ql.includes("bill") && /why|higher|change|increase|more/.test(ql) && ym.length) {
    let [a, b] = ym.length >= 2 ? [ym[1], ym[0]] : ["", ym[0]];
    if (!a) { const [y, m] = b.split("-").map(Number); a = m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, "0")}`; }
    return [["explain_bill_change", { site: s, month_a: a, month_b: b }]];
  }
  if (/report|summari[sz]e|summary|for the gm|for finance|month in review/.test(ql)) return [["monthly_report", ym[0] ? { month: ym[0] } : {}]];
  if (/bill|reconcil|provisional/.test(ql)) return [["bill_reconciliation", { site: s, month: ym[0] }]];
  const named = Object.entries(SITES).some(([c, n]) => ql.includes(n.toLowerCase()) || new RegExp(`\\b${c.toLowerCase()}\\b`).test(ql));
  if (/right now|\bnow\b|today|latest|currently|at the moment|so far|how is|how are|status/.test(ql)) return [["today_status", named ? { site: s } : {}]];
  if (/tomorrow|next week|upcoming/.test(ql)) { const g = ql.match(/(\d{2,4})\s*(?:-|\s)?(?:guest|people|pax|delegate)/); return [["forecast_upcoming", { conference_guests: g ? Number(g[1]) : 0 }]]; }
  if (/forecast|risk|peak|kva/.test(ql)) { const d = q.match(/20\d\d-\d\d-\d\d/); return [[d && d[0] > "2026-09-30" ? "forecast_upcoming" : "forecast_day", { date: d ? d[0] : "2026-06-18" }]]; }
  if (/saving|save/.test(ql)) return [["savings_plan", {}]];
  return [["list_alerts", { site: s }]];
}
function template(calls: [string, J, J][]): string {
  const p: string[] = [];
  const f = (x: number) => `₹${Math.round(x).toLocaleString("en-IN")}`;
  const D: Record<string, string> = { Weather: "Weather", Occupancy: "Guests in house", Events: "Events", Calendar: "Days in the month", Anomalies: "Waste and faults", Demand: "Peak-demand charges", Diesel: "Diesel generator", "Tariff mix": "Time-of-day pricing", Unexplained: "Not explained" };
  for (const [n, , r] of calls) {
    if (r.error) { p.push(r.error); continue; }
    if (n === "explain_bill_change") { p.push(`${r.hotel}'s bill for ${r.month_b} was ${f(r.bill_b_inr)}, against ${f(r.bill_a_inr)} for ${r.month_a}, a change of ${f(r.change_inr)}. Where it came from:`); for (const [k, v] of Object.entries(r.change_by_driver_inr as Record<string, number>).sort((x, y) => Math.abs(y[1]) - Math.abs(x[1]))) p.push(`- ${k[0].toUpperCase() + k.slice(1)}: ${v >= 0 ? "+" : "−"}${f(Math.abs(v))}`); }
    else if (n === "list_alerts") { p.push(`Top ${r.n} alerts by ₹:`); for (const a of r.alerts) p.push(`- ${a.hotel}: ${a.problem}, from ${a.start.replace("T", " ")} (${a.hours} h), ${f(a.inr)}.`); }
    else if (n === "bill_reconciliation") for (const x of r.rows) p.push(x.status === "Provisional"
      ? `${r.hotel}, ${x.month}: this is an estimated bill. It charges ${f(x.billed_total)}, but our meter puts it at ${f(x.corrected_total)}, so it is about ${f(x.billed_minus_corrected)} too high. Ask the utility for a bill on the actual meter reading.`
      : x.status === "Meter fault" ? `${r.hotel}, ${x.month}: billed ${f(x.billed_total)} using faulty meter readings; on our corrected reading it would be ${f(x.corrected_total)}.`
      : `${r.hotel}, ${x.month}: billed ${f(x.billed_total)}, which matches our meter.`);
    else if (n === "forecast_day" || n === "forecast_scenario" || n === "forecast_upcoming") { p.push(`${r.scenario ?? r.date}${r.top_temperature_c != null ? ` (top ${r.top_temperature_c} °C)` : ""}: expected peak ${r.forecast_peak_kva} kVA around ${r.peak_hour}:00 (limit 1,000 kVA); ${r.chance_above_1000_kva_pct}% chance of going over. If laundry, water heating and banquet cooling overlap that afternoon it could reach ${r.if_laundry_water_heating_and_banquet_cooling_overlap_kva} kVA.${r.shift_plan ? " Suggested moves:" : ""}`); for (const s of r.shift_plan ?? []) p.push(`- ${s.action} (frees about ${s.frees_up_kva} kVA)`); }
    else if (n === "operating_plan") {
      p.push(`${r.hotel} plan for ${r.date}${r.part_of_day ? ` (${r.part_of_day})` : ""}: ${r.plan}.`);
      for (const s of r.steps) p.push(`- ${s.from.replace(" (next day)", "")}–${s.to.replace("00:00 (next day)", "24:00").replace(" (next day)", "")}: ${s.what}: ${s.setting}${s.saving_inr >= 1 ? ` (saves about ${f(s.saving_inr)})` : s.counted === false ? " (not verifiable here, so not counted)" : ""}. ${s.status === "suggested" ? "Suggested." : s.status[0].toUpperCase() + s.status.slice(1) + "."}`);
      if (!r.steps.length) p.push("No steps fall in that part of the day.");
    }
    else if (n === "monthly_report") {
      p.push(`${r.month} (as of ${r.as_of}, when the bill was issued): the three hotels' bills came to ${f(r.total_inr)}` +
        (r.change_vs_last_month_inr != null ? `, ${r.change_vs_last_month_inr >= 0 ? "up" : "down"} ${f(Math.abs(r.change_vs_last_month_inr))} on last month` : "") +
        (r.change_vs_last_year_inr != null ? ` and ${r.change_vs_last_year_inr >= 0 ? "up" : "down"} ${f(Math.abs(r.change_vs_last_year_inr))} on the same month last year` : "") + ".");
      if (typeof r.what_drove_the_change_inr === "object") p.push("What drove the change: " + Object.entries(r.what_drove_the_change_inr as Record<string, number>).sort((x, y) => Math.abs(y[1]) - Math.abs(x[1])).slice(0, 5).map(([k, v]) => `${k} ${v >= 0 ? "+" : "−"}${f(Math.abs(v))}`).join(", ") + ".");
      const sv = r.savings;
      p.push(`Savings: from acting on alerts ${f(sv.from_acting_on_alerts_inr)}` + (typeof sv.from_the_daily_plan_verified === "object" ? `; from the daily plan (verified) ${f(sv.from_the_daily_plan_verified.verified_inr)}` : "") +
        (typeof sv.option_c_total === "object" ? `; total effect against the adjusted baseline ${f(sv.option_c_total.inr)}` : "") + ". A rupee is counted once.");
      for (const [h, x] of Object.entries(r.hotels as J)) p.push(`- ${h}: ${f((x as J).bill_inr)}, bill check: ${(x as J).bill_check}.`);
      if (r.top_problems.length) p.push("Top problems: " + r.top_problems.map((x: J) => `${x.hotel} ${x.problem} ${f(x.inr)} (${x.status})`).join("; ") + ".");
    }
    else if (n === "today_status") {
      p.push(`As of ${r.as_of_india_time} (India), from the live feed (simulated meters):`);
      for (const h of r.hotels) {
        p.push(`- ${h.hotel}: ${h.used_today_kwh.toLocaleString("en-IN")} kWh used today vs ${h.expected_today_kwh.toLocaleString("en-IN")} expected` +
          `${h.today_vs_expected_pct != null ? ` (${h.today_vs_expected_pct >= 0 ? "+" : ""}${h.today_vs_expected_pct}%)` : ""}; ` +
          `peak so far ${h.peak_power_demand_today_kva ?? "—"} kVA (limit ${h.contracted_power_limit_kva.toLocaleString("en-IN")}).` +
          (h.problems_now.length ? ` Running now: ${h.problems_now.map((x: J) => `${x.problem} since ${x.since}${x.inr_per_day != null ? `, about ${f(x.inr_per_day)} a day` : ""}`).join("; ")}.` : " Nothing needs attention.") +
          (h.meter_faults_now.length ? " The main meter is sending bad readings; those hours are ignored." : "") +
          (h.latest_bill ? ` Latest bill: ${h.latest_bill.month}, ${f(h.latest_bill.total_inr)}.` : ""));
      }
    }
    else if (n === "savings_plan") { p.push(`From operations we can save about ${f(r.operations_inr)} a year, ${r.operations_pct}% of the electricity bill. With one capital item (pump speed controls, which needs investment) it is ${f(r.with_capital_inr)}, ${r.with_capital_pct}%. The biggest items:`); for (const m of [...r.measures].sort((a: J, b: J) => b.inr - a.inr).slice(0, 6)) p.push(`- ${m.hotel}: ${m.measure}: ${f(m.inr)} a year`); }
  }
  return p.join("\n");
}

export default async (req: Request) => {
  if (req.method !== "POST") return Response.json({ error: "POST a question." }, { status: 405 });
  let body: J;
  try { body = await req.json(); } catch { return Response.json({ error: "Send JSON: {question}." }, { status: 400 }); }
  const q = String(body.question ?? "").slice(0, 1000);
  if (!q.trim()) return Response.json({ error: "Ask a question." }, { status: 400 });
  const g = guard(q);
  if (g) return Response.json({ text: g, mode: "Safety rule" });
  ORIGIN = process.env.URL || new URL(req.url).origin;
  const run = async (n: string, a: J): Promise<J> => { try { return await TOOLS[n].fn(a); } catch (e) { return { error: String(e) }; } };
  const runAll = (q2: string) => Promise.all(route(q2).map(async ([n, a]) => [n, a, await run(n, a)] as [string, J, J]));
  const key = process.env.ANTHROPIC_API_KEY;
  if (!key) { const calls = await runAll(q); return Response.json({ text: template(calls), mode: "Quick answer" }); }

  const client = new Anthropic({ apiKey: key });
  const hist = Array.isArray(body.history) ? body.history.filter((m: J) => m && (m.role === "user" || m.role === "assistant") && typeof m.content === "string").slice(-6) : [];
  const msgs: J[] = [...hist, { role: "user", content: q }];
  const calls: [string, J, J][] = [];
  try {
    let resp = await client.messages.create({ model: MODEL, max_tokens: 1200, system: system(), tools: schemas as any, messages: msgs as any });
    for (let i = 0; i < 5 && resp.stop_reason === "tool_use"; i++) {
      msgs.push({ role: "assistant", content: resp.content });
      const results: J[] = [];
      for (const b of resp.content as J[]) if (b.type === "tool_use") {
        const a = Object.fromEntries(Object.entries(b.input ?? {}).filter(([, v]) => v !== null && v !== ""));
        const r = TOOLS[b.name] ? await run(b.name, a) : { error: "unknown tool" };
        calls.push([b.name, a, r]); results.push({ type: "tool_result", tool_use_id: b.id, content: JSON.stringify(r) });
      }
      msgs.push({ role: "user", content: results });
      resp = await client.messages.create({ model: MODEL, max_tokens: 1200, system: system(), tools: schemas as any, messages: msgs as any });
    }
    let text = (resp.content as J[]).filter((b) => b.type === "text").map((b) => b.text).join("").trim();
    const facts = JSON.stringify(calls.map((c) => c[2]));
    let bad = unverified(text, facts, q);
    if (bad.length) {
      msgs.push({ role: "assistant", content: resp.content }, { role: "user", content: `Rewrite your answer. These numbers do not appear in the tool results: ${bad.slice(0, 8).join(", ")}. Do not add, subtract, total or convert numbers yourself; quote only figures exactly as the tools returned them.` });
      resp = await client.messages.create({ model: MODEL, max_tokens: 1200, system: system(), tools: schemas as any, messages: msgs as any });
      text = (resp.content as J[]).filter((b) => b.type === "text").map((b) => b.text).join("").trim();
      bad = unverified(text, facts, q);
    }
    if (bad.length) return Response.json({ text: calls.length ? template(calls) : "I could not verify the figures for that answer.", mode: "Figures straight from the data" });
    return Response.json({ text, mode: "Every figure checked against the hotel data", tools: calls.map((c) => c[0]) });
  } catch (e) {
    const fallback = await runAll(q);
    return Response.json({ text: template(fallback), mode: "Quick answer (the detailed assistant is busy)" });
  }
};
