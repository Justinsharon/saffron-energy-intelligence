import { useEffect, useMemo, useState } from "react";
import { useClock } from "../App";
import { Status, Waterfall } from "../components/parts";
import { DRIVER, RULE } from "../copy";
import { load, SITE_NAME, SITES, useAlertsAt, useBillsAt, useChangesAt, useData, type ForecastDay, type Recon, type Site } from "../data";
import { fmtD, fmtMonth, inr, n } from "../format";
import { growthKwh, useMonthSavings } from "../monthSavings";
import { riskFor, type RiskCal } from "../plan";

/** One month's report, as exported by tools/export_reports.py for closed months (and built the same way in the browser otherwise). */
export interface ReportData {
  month: string; as_of: string; simulated: boolean;
  bills: Record<Site, { this: number | null; prev: number | null; last_year: number | null }>;
  option_c: { by_site: Record<Site, { actual_kwh: number; baseline_kwh: number; kwh: number; inr: number }>; kwh: number; inr: number } | null;
  savings: { plan: { verified_inr: number; planned_inr: number; missed_inr: number; would_have_saved_inr: number; approved_steps: number; saved_days: number } | null;
    plan_note: string | null; alerts: { inr: number; dropped_inr: number; alerts: number } | null };
  gap: { found_inr: number; option_c_inr: number; gap_inr: number; growth_inr: number; growth_kwh: number; rest_inr: number } | null;
  drivers: { complete: boolean; prev_total: number; this_total: number; steps: { group: string; inr: number }[] };
  bill_check: { site: Site; status: string; billed_minus_corrected: number }[];
  problems: { hotel: string; rule: string; title: string; inr: number; status: string }[];
  watch: { date: string; peak_kva: number; level: string; level_text: string }[];
  method: string; honesty: string;
}
interface PlanIndex { days: Record<string, { peak_kva: number }>; risk: RiskCal }
const LEVEL: Record<string, string> = { "BREACH RISK": "risk of going over", WARNING: "close to the limit", "STACKING WATCH": "watch the afternoon", OK: "comfortable" };
const addMonth = (m: string, k: number) => {
  if (!/^\d{4}-\d{2}$/.test(m)) return "";                    // no month yet (bills still loading)
  const [y, mo] = m.split("-").map(Number);
  return new Date(Date.UTC(y, mo - 1 + k, 1)).toISOString().slice(0, 7);
};
const issuedOn = (r: Recon | undefined, m: string) => (r?.bill_issued ? r.bill_issued.slice(0, 10) : m ? `${addMonth(m, 1)}-05` : "");
const pct = (a: number | null, b: number | null) => (a != null && b ? `${a >= b ? "+" : "−"}${Math.abs((a / b - 1) * 100).toFixed(1)}%` : "—");

/** Monthly report for the general manager and the finance controller: one A4 page, as of the day the month's bill was issued. Closed months
 *  come from static files made at build time (instant, never "unavailable"); a month issued after the last export is built here instead. */
export default function Report() {
  const { now } = useClock();
  const billsNow = useBillsAt(now);
  const months = useMemo(() => [...new Set((billsNow?.recon ?? []).map((r) => r.month))].sort(), [billsNow]);
  const [month, setMonth] = useState<string | null>(null);
  useEffect(() => { if (months.length && (!month || !months.includes(month))) setMonth(months.at(-1)!); }, [months.join()]);
  const m = month ?? months.at(-1) ?? "";
  const index = useData<{ months: string[] }>("reports/index.json");
  const isStatic = !!index?.months.includes(m);
  const [stat, setStat] = useState<ReportData | null>(null);
  useEffect(() => { setStat(null); if (isStatic) load<ReportData>(`reports/${m}.json`).then(setStat).catch(() => setStat(null)); }, [m, isStatic]);
  const live = useLiveReport(index && !isStatic ? m : "", now);
  const r = isStatic ? stat : live;

  return (
    <div className="report">
      <div className="page-head no-print">
        <div><h1>Monthly report</h1><p className="lead">For the general manager and the finance controller. Made automatically from the data on the day each month's bill arrives; nothing to prepare.</p></div>
        <div className="btn-row" style={{ alignItems: "center" }}>
          <select className="month-pick" value={m} onChange={(e) => setMonth(e.target.value)}>{months.map((x) => <option key={x} value={x}>{fmtMonth(x)}</option>)}</select>
          <button className="btn accent" onClick={() => window.print()}>Download PDF</button>
        </div>
      </div>
      {!r ? <p className="muted">Loading the report…</p> : <Sheet r={r} />}
    </div>
  );
}

function Sheet({ r }: { r: ReportData }) {
  const m = r.month, prev = addMonth(m, -1), ly = addMonth(m, -12);
  const tot = (k: "this" | "prev" | "last_year") => SITES.reduce((x, s) => x + (r.bills[s][k] ?? 0), 0);
  const total = tot("this"), totPrev = tot("prev"), totLy = tot("last_year");
  const p = r.savings.plan, oc = r.option_c, g = r.gap;
  const wf = r.drivers.steps.map((x) => ({ label: DRIVER[x.group] ?? x.group, value: x.inr }));
  return (
    <section className="sheet">
      <header className="sheet-head">
        <h2>Saffron Suites · Electricity, {fmtMonth(m)}</h2>
        <p className="small muted">Gurugram, Jaipur and Goa · as of {fmtD(r.as_of)}, when the bill was issued · tariff rates are illustrative{r.simulated ? " · meters from Oct 2026 are simulated" : ""}</p>
      </header>
      <div className="sheet-grid">
        <div>
          <h3>a) The bill</h3>
          <table className="t compact">
            <thead><tr><th></th><th className="r">{fmtMonth(m)}</th><th className="r">vs {fmtMonth(prev)}</th><th className="r">vs {fmtMonth(ly)}</th><th className="r">vs adjusted baseline</th></tr></thead>
            <tbody>
              {SITES.map((s) => { const b = r.bills[s], c = oc?.by_site[s]; return (
                <tr key={s}><td>{SITE_NAME[s]}</td><td className="r">{inr(b.this)}</td><td className="r">{pct(b.this, b.prev)}</td><td className="r">{pct(b.this, b.last_year)}</td>
                  <td className="r">{c ? `${c.kwh >= 0 ? "−" : "+"}${Math.abs(c.kwh / Math.max(c.baseline_kwh, 1) * 100).toFixed(1)}% use` : "…"}</td></tr>); })}
              <tr className="tot"><td>All hotels</td><td className="r">{inr(total)}</td><td className="r">{totPrev ? `${inr(total - totPrev)} (${pct(total, totPrev)})` : "—"}</td>
                <td className="r">{totLy ? `${inr(total - totLy)} (${pct(total, totLy)})` : "—"}</td><td className="r">{oc ? `${n(Math.abs(oc.kwh))} kWh ${oc.kwh >= 0 ? "below" : "above"}` : "…"}</td></tr>
            </tbody>
          </table>

          <h3>c) Savings this month</h3>
          <table className="t compact">
            <tbody>
              <tr><td>From the daily plan (approved steps, verified)</td><td className="r">{p ? inr(p.verified_inr) : r.savings.plan_note ? "—" : "…"}</td></tr>
              <tr><td>From acting on alerts</td><td className="r">{r.savings.alerts ? inr(r.savings.alerts.inr) : "…"}</td></tr>
              <tr className="tot"><td>Total effect (Option C, all hotels)</td><td className="r">{oc ? inr(oc.inr) : "…"}</td></tr>
            </tbody>
          </table>
          {g && Math.abs(g.gap_inr) >= 1 && (
            <p className="gap-line">Why the total differs from the savings found ({inr(g.found_inr)} vs {inr(g.option_c_inr)}): the live year grows about 1.2 % a year, which the
              baseline (trained on last year) does not adjust for: {inr(g.growth_inr)} ({n(g.growth_kwh)} kWh) this month. The other {inr(g.rest_inr)} is mostly waste from new faults
              that the alerts caught but that still ran on the meters, plus model noise.</p>
          )}
          <p className="tiny">{p ? `${p.approved_steps} approved steps on ${p.saved_days} saved ${p.saved_days === 1 ? "day" : "days"}${p.would_have_saved_inr >= 1 ? `; suggested plans on other days would have saved ${inr(p.would_have_saved_inr)} if followed (not counted)` : ""}. ` : r.savings.plan_note ? `${r.savings.plan_note} ` : ""}Method: {r.method}</p>

          <h3>d) Bill check</h3>
          <table className="t compact">
            <tbody>{r.bill_check.map((b) => (
              <tr key={b.site}><td>{SITE_NAME[b.site]}</td><td><Status s={b.status} /></td><td className="r">{Math.abs(b.billed_minus_corrected) < 1 ? "matches our meter" : `${b.billed_minus_corrected > 0 ? "billed" : "under-billed"} ${inr(Math.abs(b.billed_minus_corrected))}`}</td></tr>
            ))}</tbody>
          </table>
        </div>

        <div>
          <h3>b) What drove the change from {fmtMonth(prev)}</h3>
          {r.drivers.complete && wf.length ? <Waterfall start={r.drivers.prev_total} end={r.drivers.this_total} startLabel={fmtMonth(prev)} endLabel={fmtMonth(m)} steps={wf} height={200} stagger />
            : <p className="small muted">No comparison with {fmtMonth(prev)} is available for this month.</p>}

          <h3>e) Top problems in {fmtMonth(m)}</h3>
          <table className="t compact">
            <tbody>{r.problems.map((a, i) => (
              <tr key={i}><td>{a.hotel}: {RULE[a.rule]?.title ?? a.title}</td><td className="r">{inr(a.inr)}</td><td className="small">{a.status}</td></tr>
            ))}{!r.problems.length && <tr><td className="muted">No costed problems this month.</td></tr>}</tbody>
          </table>
          <p className="small" style={{ margin: "8px 0 0" }}><strong>Watch in {fmtMonth(addMonth(m, 1))} (Gurugram, 1,000 kVA limit): </strong>
            {r.watch.length ? r.watch.map((w) => `${fmtD(w.date).replace(/ \d{4}$/, "")} ${n(w.peak_kva)} kVA (${w.level_text})`).join("; ") : "no forecast yet for those days."}</p>
        </div>
      </div>
      <p className="tiny" style={{ marginTop: 6 }}>Recommend only: every change is approved by a person. {r.honesty}</p>
    </section>
  );
}

/** The same report built in the browser, for a month whose bill arrived after the last export. `m` = "" turns it off (no API call). */
function useLiveReport(m: string, now: string): ReportData | null {
  const billsNow = useBillsAt(now);
  const asOfDate = issuedOn(billsNow?.recon.find((r) => r.month === m), m);
  const asOf = asOfDate ? `${asOfDate}T09:00` : now;
  const bills = useBillsAt(asOf);
  const changes = useChangesAt(bills);
  const alerts = useAlertsAt(asOf);
  const sav = useMonthSavings(m, asOf);
  const idx = useData<PlanIndex>("plan/index.json");
  const past = useData<Record<string, ForecastDay>>("forecast_days.json");
  const hr = sav.hourly;
  return useMemo(() => {
    if (!m || !bills || !alerts) return null;
    const prev = addMonth(m, -1), ly = addMonth(m, -12);
    const val = (s: Site, mm: string) => bills.recon.find((r) => r.site === s && r.month === mm)?.billed_total ?? null;
    const groups: Record<string, number> = {};
    let have = 0;
    for (const s of SITES) { const c = changes?.[`${s}|${prev}|${m}`]; if (c) { have++; for (const [k, v] of Object.entries(c.groups)) groups[k] = (groups[k] ?? 0) + v; } }
    const st = Object.entries(groups).filter(([, v]) => Math.abs(v) >= 1).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
    const steps = st.slice(0, 5).map(([group, inr]) => ({ group, inr }));
    const rest = st.slice(5).reduce((x, [, v]) => x + v, 0);
    if (Math.abs(rest) >= 1) steps.push({ group: "Other", inr: rest });
    const nm = addMonth(m, 1);
    let watch: ReportData["watch"] = [];
    if (idx) for (const [d, x] of Object.entries(idx.days)) if (d.startsWith(nm) && d > asOfDate) { const k = riskFor([x.peak_kva], idx.risk); watch.push({ date: d, peak_kva: k.peak, level: k.level, level_text: LEVEL[k.level] }); }
    if (!watch.length && past) for (const [d, f] of Object.entries(past)) if (d.startsWith(nm) && d > asOfDate) watch.push({ date: d, peak_kva: f.risk.peak, level: f.risk.level, level_text: LEVEL[f.risk.level] });
    watch = watch.sort((a, b) => b.peak_kva - a.peak_kva).slice(0, 4);
    const oc = sav.optionC;
    const plan = sav.plan ? { verified_inr: sav.plan.totals.verified_inr, planned_inr: sav.plan.totals.planned_inr, missed_inr: sav.plan.totals.missed_inr,
      would_have_saved_inr: sav.plan.totals.would_have_saved_inr, approved_steps: sav.plan.totals.approved_steps, saved_days: sav.plan.totals.saved_days } : null;
    const live = m >= "2026-10";
    const gKwh = live && hr ? growthKwh(hr, m, asOf) : null;
    const found = (sav.alerts?.inr ?? 0) + (plan?.verified_inr ?? 0);
    const growthInr = gKwh && oc ? SITES.reduce((x, s) => x + gKwh[s] * oc.bySite[s].rate, 0) : 0;
    return {
      month: m, as_of: asOfDate, simulated: live,
      bills: Object.fromEntries(SITES.map((s) => [s, { this: val(s, m), prev: val(s, prev), last_year: val(s, ly) }])) as ReportData["bills"],
      option_c: oc ? { by_site: Object.fromEntries(SITES.map((s) => [s, { actual_kwh: oc.bySite[s].actual, baseline_kwh: oc.bySite[s].baseline, kwh: oc.bySite[s].kwh, inr: oc.bySite[s].inr }])) as ReportData["option_c"] extends infer T ? T extends { by_site: infer B } ? B : never : never,
                       kwh: oc.kwh, inr: oc.inr } : null,
      savings: { plan, plan_note: live ? null : "Daily plans started in Oct 2026.", alerts: sav.alerts },
      gap: live && oc && gKwh ? { found_inr: found, option_c_inr: oc.inr, gap_inr: found - oc.inr, growth_inr: growthInr, growth_kwh: SITES.reduce((x, s) => x + gKwh[s], 0),
                                  rest_inr: found - oc.inr - growthInr } : null,
      drivers: { complete: have === SITES.length, prev_total: SITES.reduce((x, s) => x + (val(s, prev) ?? 0), 0), this_total: SITES.reduce((x, s) => x + (val(s, m) ?? 0), 0), steps },
      bill_check: SITES.map((s) => bills.recon.find((r) => r.site === s && r.month === m)).filter((r): r is Recon => !!r)
        .map((r) => ({ site: r.site, status: r.status, billed_minus_corrected: r.billed_minus_corrected })),
      problems: alerts.filter((a) => a.start.slice(0, 7) === m && a.cost > 0 && a.rule !== "PLAN_DEVIATION").sort((a, b) => b.cost - a.cost).slice(0, 5)
        .map((a) => ({ hotel: a.hotel, rule: a.rule, title: a.title, inr: a.cost, status: a.end <= asOf ? "resolved" : "still running" })),
      watch,
      method: "Plan = approved steps of saved plans that were followed, meters vs matched days last year; alerts = waste caught, counted once and never for hours an approved plan step covered; Option C = actual vs the weather-, occupancy- and event-adjusted baseline (IPMVP).",
      honesty: live ? (sav.plan?.honesty ?? "Meters from Oct 2026 are simulated.") : "",
    };
  }, [m, bills, changes, alerts, sav, idx, past, hr]);
}
