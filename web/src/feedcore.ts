// The live feed's one rule: nothing after the current hour in India is ever shown. Pure functions, shared by the browser
// (look back, and a fallback when the feed function can't be reached) and by the Netlify functions (feed, assistant), so
// every place cuts the data the same way. The live year (Oct 2026 - Sep 2027) is synthetic: simulated meters.
import type { Alert, BillChange, Bills, Fault, Hourly, Recon, Site } from "./data";

export const LIVE_START = "2026-10-01T00:00";          // first hour of the live (simulated) year; before it, the original year
export const DATA_FIRST = "2025-10-01";

/** Real wall-clock time in India, "YYYY-MM-DDTHH:MM" (the data's convention: IST, start of interval). */
export function istNow(): string { return new Date(Date.now() + 5.5 * 3.6e6).toISOString().slice(0, 16); }
const ms = (t: string) => Date.parse(t.length <= 13 ? `${t}:00:00Z` : `${t.slice(0, 16)}:00Z`);
const hourKey = (now: string) => now.slice(0, 13);
const iso = (x: number) => new Date(x).toISOString().slice(0, 16);

/** Hourly rows up to and including the current hour; `hours` keeps only the most recent ones. */
export function clipHourly(h: Hourly, now: string, hours?: number): Hourly {
  const key = hourKey(now);
  let end = h.t.findIndex((t) => t > key);
  if (end < 0) end = h.t.length;
  const start = hours ? Math.max(0, end - hours) : 0;
  const s = <T,>(x: T[]) => x.slice(start, end);
  return { t: s(h.t), a: s(h.a), b: s(h.b), temp: s(h.temp), kva: s(h.kva), ev: s(h.ev), f: s(h.f) };
}
export function joinHourly(a: Hourly, b: Hourly): Hourly {
  return { t: [...a.t, ...b.t], a: [...a.a, ...b.a], b: [...a.b, ...b.b], temp: [...a.temp, ...b.temp], kva: [...a.kva, ...b.kva], ev: [...a.ev, ...b.ev], f: [...a.f, ...b.f] };
}

const SIGNAL: Record<string, string> = {
  ahu_banquet_kw: "banquet AHUs", ahu_heaters_kw: "AHU re-heat", kitchen_exhaust_kw: "kitchen exhaust", lighting_kw: "lighting", laundry_kw: "laundry",
  pool_pump_kw: "pool pumps", chillers_kw: "chillers", ev_chargers_kw: "EV chargers", kva_max_in_hour: "site demand (kVA)", chiller_load_tr: "cooling load (TR)",
};
const mean = (xs: (number | null)[]) => { const v = xs.filter((x): x is number => x != null); return v.length ? v.reduce((p, q) => p + q, 0) / v.length : null; };

/** An alert as it looked at `now`: null if not raised yet; if still running, cut to the readings so far. The precomputed episode
 *  figures (end, duration, ₹, evidence text) use the whole episode, so for a running alert they are rebuilt from the clipped readings. */
export function clipAlert(a: Alert, now: string): Alert | null {
  if (a.alert_time > now) return null;
  const key = hourKey(now);
  let k = a.chart.t.findIndex((t) => t > key);
  if (k < 0) k = a.chart.t.length;
  const chart = k === a.chart.t.length ? a.chart : { t: a.chart.t.slice(0, k), actual: a.chart.actual.slice(0, k), baseline: a.chart.baseline.slice(0, k),
                  signals: Object.fromEntries(Object.entries(a.chart.signals).map(([n, v]) => [n, v.slice(0, k)])) };
  if (a.end <= now) return chart === a.chart ? a : { ...a, chart };      // ended: figures are final; only the chart's padding is cut
  const ran = Math.max(0, (ms(now) - ms(a.start)) / 3.6e6);
  const flagged = Math.min(a.flagged_h, ran);
  const inWin = chart.t.map((t) => t >= a.start.slice(0, 13));
  const part = (x: (number | null)[]) => x.filter((_, i) => inWin[i]);
  const bits = Object.entries(chart.signals).filter(([n]) => SIGNAL[n]).map(([n, v]) => { const m = mean(part(v)); return m == null ? "" : `${SIGNAL[n]} ${m.toFixed(n === "kva_max_in_hour" || n === "chiller_load_tr" ? 0 : 1)}`; }).filter(Boolean);
  const act = mean(part(chart.actual)), base = mean(part(chart.baseline));
  const evidence = `Readings so far (${Math.round(ran)} h since ${a.start.slice(11, 16)} ${a.start.slice(8, 10)}/${a.start.slice(5, 7)}, to ${key.slice(11)}:00): ` +
    (bits.length ? `average ${bits.join(", ")}` : "the waste signal is still on") +
    (act != null && base != null ? `; site load ${act.toFixed(0)} kW vs ${base.toFixed(0)} kW expected` : "");
  const cost = a.cost_basis === "per_day" ? a.per_hour * flagged : 0;
  return { ...a, end: now, duration_h: ran, flagged_h: flagged, cost, excess_kwh: a.excess_kwh * (a.flagged_h ? flagged / a.flagged_h : 0), evidence, chart, ongoing: true,
           cost_note: a.cost_basis === "per_day" ? a.cost_note : "₹ worked out when it ends",
           text: `${a.hotel} · ${a.title} — since ${a.start.replace("T", " ")}, still running (${Math.round(ran)} h so far). ${evidence}. Likely cause: ${a.cause} Action: ${a.action}` };
}
export function visibleAlerts(xs: Alert[], now: string): Alert[] {
  const out: Alert[] = [];
  for (const a of xs) { const c = clipAlert(a, now); if (c) out.push(c); }
  return out;
}
export function visibleFaults(xs: Fault[], now: string): Fault[] {
  return xs.filter((f) => f.detected_at <= now).map((f) => (f.end <= now ? f : { ...f, end: now, duration_h: (ms(now) - ms(f.start)) / 3.6e6 }));
}

/** A bill is shown once it has been issued (original-year bills carry no date and are all on file). */
export const issued = (r: { bill_issued?: string | null }, now: string) => !r.bill_issued || r.bill_issued.slice(0, 10) <= now.slice(0, 10);
export function visibleBills(orig: Bills, live: Bills | null, now: string): Bills {
  const lr = live ? live.recon.filter((r) => issued(r, now)) : [];
  const ok = new Set(lr.map((r) => `${r.site}|${r.month}`));
  const comp = {} as Bills["components"];
  for (const s of Object.keys(orig.components) as Site[])
    comp[s] = [...orig.components[s], ...(live?.components[s] ?? []).filter((c) => ok.has(`${s}|${c.billing_month}`))];
  return { recon: [...orig.recon, ...lr], components: comp, unused_demand: orig.unused_demand };
}
export function visibleChanges(orig: Record<string, BillChange>, live: Record<string, BillChange> | null, bills: Bills): Record<string, BillChange> {
  const ok = new Set(bills.recon.map((r) => `${r.site}|${r.month}`));
  const out = { ...orig };
  for (const [k, v] of Object.entries(live ?? {})) if (ok.has(`${v.site}|${v.a}`) && ok.has(`${v.site}|${v.b}`)) out[k] = v;
  return out;
}

export interface Feed {
  site: Site; now: string; source: "live feed (simulated meters)" | "original year";
  readings: Hourly;                       // last `hours` rows up to the current hour
  today: { used_kwh: number; expected_kwh: number; peak_kva: number | null; peak_hour: number | null; hours: number };
  open_alerts: Alert[];                   // raised and still running at `now`, clipped to the readings so far
  recent_alerts: Alert[];                 // everything raised in the last 24 h or still running (open, resolved, digest), clipped
  faults_now: Fault[];
  latest_bill: Recon | null;              // most recent bill issued by `now`
}
export interface FeedSource { hourly: Hourly; alerts: Alert[]; faults: Fault[]; recon: Recon[] }

export function feedFor(site: Site, now: string, hours: number, src: FeedSource): Feed {
  const readings = clipHourly(src.hourly, now, Math.max(hours, 1));
  const day = now.slice(0, 10);
  const all = clipHourly(src.hourly, now, 24);
  let used = 0, exp = 0, peak: number | null = null, ph: number | null = null, nh = 0;
  all.t.forEach((t, i) => {
    if (t.slice(0, 10) !== day) return;
    used += all.a[i]; exp += all.b[i]; nh++;
    if (peak == null || all.kva[i] > peak) { peak = all.kva[i]; ph = Number(t.slice(11, 13)); }
  });
  const dayAgo = iso(ms(now) - 864e5);
  const mine = visibleAlerts(src.alerts.filter((a) => a.site === site), now);
  const recent = mine.filter((a) => a.end > dayAgo || a.alert_time > dayAgo);
  const bills = src.recon.filter((r) => r.site === site && issued(r, now)).sort((p, q) => p.month.localeCompare(q.month));
  return { site, now, source: now >= LIVE_START ? "live feed (simulated meters)" : "original year", readings,
           today: { used_kwh: used, expected_kwh: exp, peak_kva: peak, peak_hour: ph, hours: nh },
           open_alerts: recent.filter((a) => a.ongoing), recent_alerts: recent,
           faults_now: visibleFaults(src.faults.filter((f) => f.site === site), now).filter((f) => f.end >= now),
           latest_bill: bills.at(-1) ?? null };
}
