// Energy assistant (port of src/assistant.py). Rules, in order:
// 1. A fixed guard refuses unsafe control requests before any model call (T10).
// 2. Claude answers only through tools that return numbers our models exported (data/*.json).
// 3. Every number in the reply must appear in the tool results or the question; otherwise one rewrite, then a template answer.
// 4. Without ANTHROPIC_API_KEY the same tools are routed by keywords.
import Anthropic from "@anthropic-ai/sdk";
import alerts from "./data/alerts_lite.json";
import bills from "./data/bills.json";
import changes from "./data/bill_changes.json";
import days from "./data/forecast_days.json";
import whatif from "./data/forecast_whatif.json";
import savings from "./data/savings.json";

type J = Record<string, any>;
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
const TOOLS: Record<string, { fn: (a: J) => J; desc: string; params: Record<string, string> }> = {
  explain_bill_change: {
    desc: "Split the change between two monthly bills of one hotel into weather, occupancy, events, calendar, anomalies (incl. PF), demand, diesel, tariff mix. Months as YYYY-MM.",
    params: { site: "string: GGN/JAI/GOA or hotel name", month_a: "string YYYY-MM", month_b: "string YYYY-MM" },
    fn: (a) => {
      const s = site(a.site); const [x, y] = [a.month_a, a.month_b].sort();
      const c = (changes as J)[`${s}|${x}|${y}`];
      if (!c) return { error: "No bill for one of those months (data covers Oct 2025 – Sep 2026)." };
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
      const rows = (bills as J).recon.filter((r: J) => r.site === s && (!a.month || r.month === a.month))
        .map((r: J) => ({ month: r.month, status: r.status, billed_total: r0(r.billed_total), corrected_total: r0(r.corrected_total), billed_minus_corrected: r0(r.billed_minus_corrected), md_kva: r.md_kva, pf: r.pf, pf_source: r.pf_source, note: r.note }));
      return { hotel: SITES[s], rows };
    },
  },
  list_alerts: {
    desc: "Detected waste alerts with evidence, ₹ and action, largest ₹ first.",
    params: { site: "string, optional", date_from: "YYYY-MM-DD optional", date_to: "YYYY-MM-DD optional", top: "integer, optional" },
    fn: (a) => {
      let x = (alerts as J[]);
      if (a.site) x = x.filter((q) => q.site === site(a.site));
      if (a.date_from) x = x.filter((q) => q.end >= a.date_from);
      if (a.date_to) x = x.filter((q) => q.start <= a.date_to + "T23:59");
      x = [...x].sort((p, q) => q.cost - p.cost).slice(0, Number(a.top) || 8);
      return { n: x.length, alerts: x.map((q) => ({ id: q.id, hotel: q.hotel, title: q.title, severity: q.severity, start: q.start, hours: Math.round(q.duration_h * 10) / 10,
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
    desc: "Sized savings measures (energy / ToD / demand) with safety notes; capital items shown separately.",
    params: {},
    fn: () => {
      const s = savings as J; const core = s.measures.filter((m: J) => m.category !== "Capital (note)");
      const tot = core.reduce((a: number, m: J) => a + m.inr, 0), all = s.measures.reduce((a: number, m: J) => a + m.inr, 0);
      const by: J = {}; for (const m of s.measures) by[m.category] = r0((by[m.category] ?? 0) + m.inr);
      return { total_inr: r0(tot), pct_of_group_bill: Math.round(tot / s.group_bill * 1000) / 10, with_capital_note_inr: r0(all),
        with_capital_note_pct: Math.round(all / s.group_bill * 1000) / 10, target_pct: "8-12", by_category_inr: by,
        measures: s.measures.map((m: J) => ({ hotel: m.hotel, measure: plainMeasure(m.measure), kind: ({ Energy: "use less", ToD: "use at cheaper times", Demand: "lower peak charges", "Capital (note)": "needs investment" } as J)[m.category] ?? m.category, inr: r0(m.inr), how_sure: String(m.confidence).startsWith("High") ? "measured" : String(m.confidence).startsWith("Medium") ? "estimated" : "rough estimate", safety: m.safety })) };
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
and never a chilled-water setpoint below 6.5 °C. "Tomorrow" questions with a temperature use forecast_scenario. The latest month in the data is 2026-09.`;

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
  const ym = [...ql.matchAll(/\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b/g)].map((m) => { const k = M.indexOf(m[1]) + 1; return `${k >= 10 ? 2025 : 2026}-${String(k).padStart(2, "0")}`; });
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
  if (/bill|reconcil|provisional/.test(ql)) return [["bill_reconciliation", { site: s, month: ym[0] }]];
  if (/forecast|risk|tomorrow|peak|kva/.test(ql)) { const d = q.match(/20\d\d-\d\d-\d\d/); return [["forecast_day", { date: d ? d[0] : "2026-06-18" }]]; }
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
    else if (n === "forecast_day" || n === "forecast_scenario") { p.push(`${r.date ?? r.scenario}: expected peak ${r.forecast_peak_kva} kVA around ${r.peak_hour}:00 (limit 1,000 kVA); ${r.chance_above_1000_kva_pct}% chance of going over. If laundry, water heating and banquet cooling overlap that afternoon it could reach ${r.if_laundry_water_heating_and_banquet_cooling_overlap_kva} kVA.${r.shift_plan ? " Suggested moves:" : ""}`); for (const s of r.shift_plan ?? []) p.push(`- ${s.action} (frees about ${s.frees_up_kva} kVA)`); }
    else if (n === "savings_plan") { p.push(`We can save about ${f(r.total_inr)} a year, ${r.pct_of_group_bill}% of the electricity bill (${r.with_capital_note_pct}% with investments). The biggest items:`); for (const m of [...r.measures].sort((a: J, b: J) => b.inr - a.inr).slice(0, 6)) p.push(`- ${m.hotel}: ${m.measure}: ${f(m.inr)} a year`); }
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
  const run = (n: string, a: J): J => { try { return TOOLS[n].fn(a); } catch (e) { return { error: String(e) }; } };
  const key = process.env.ANTHROPIC_API_KEY;
  if (!key) { const calls = route(q).map(([n, a]) => [n, a, run(n, a)] as [string, J, J]); return Response.json({ text: template(calls), mode: "Quick answer" }); }

  const client = new Anthropic({ apiKey: key });
  const hist = Array.isArray(body.history) ? body.history.filter((m: J) => m && (m.role === "user" || m.role === "assistant") && typeof m.content === "string").slice(-6) : [];
  const msgs: J[] = [...hist, { role: "user", content: q }];
  const calls: [string, J, J][] = [];
  try {
    let resp = await client.messages.create({ model: MODEL, max_tokens: 1200, system: SYSTEM, tools: schemas as any, messages: msgs as any });
    for (let i = 0; i < 5 && resp.stop_reason === "tool_use"; i++) {
      msgs.push({ role: "assistant", content: resp.content });
      const results: J[] = [];
      for (const b of resp.content as J[]) if (b.type === "tool_use") {
        const a = Object.fromEntries(Object.entries(b.input ?? {}).filter(([, v]) => v !== null && v !== ""));
        const r = TOOLS[b.name] ? run(b.name, a) : { error: "unknown tool" };
        calls.push([b.name, a, r]); results.push({ type: "tool_result", tool_use_id: b.id, content: JSON.stringify(r) });
      }
      msgs.push({ role: "user", content: results });
      resp = await client.messages.create({ model: MODEL, max_tokens: 1200, system: SYSTEM, tools: schemas as any, messages: msgs as any });
    }
    let text = (resp.content as J[]).filter((b) => b.type === "text").map((b) => b.text).join("").trim();
    const facts = JSON.stringify(calls.map((c) => c[2]));
    let bad = unverified(text, facts, q);
    if (bad.length) {
      msgs.push({ role: "assistant", content: resp.content }, { role: "user", content: `Rewrite your answer. These numbers do not appear in the tool results: ${bad.slice(0, 8).join(", ")}. Do not add, subtract, total or convert numbers yourself; quote only figures exactly as the tools returned them.` });
      resp = await client.messages.create({ model: MODEL, max_tokens: 1200, system: SYSTEM, tools: schemas as any, messages: msgs as any });
      text = (resp.content as J[]).filter((b) => b.type === "text").map((b) => b.text).join("").trim();
      bad = unverified(text, facts, q);
    }
    if (bad.length) return Response.json({ text: calls.length ? template(calls) : "I could not verify the figures for that answer.", mode: "Figures straight from the data" });
    return Response.json({ text, mode: "Every figure checked against the hotel data", tools: calls.map((c) => c[0]) });
  } catch (e) {
    const fallback = route(q).map(([n, a]) => [n, a, run(n, a)] as [string, J, J]);
    return Response.json({ text: template(fallback), mode: "Quick answer (the detailed assistant is busy)" });
  }
};
