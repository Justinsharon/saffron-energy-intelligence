import { useEffect, useMemo, useState } from "react";
import { useClock } from "../App";
import { Status, Waterfall } from "../components/parts";
import { DRIVER, RULE } from "../copy";
import { SITE_NAME, SITES, useAlertsAt, useBillsAt, useChangesAt, useData, type ForecastDay, type Recon, type Site } from "../data";
import { fmtD, fmtMonth, inr, n } from "../format";
import { useMonthSavings } from "../monthSavings";
import { riskFor, type RiskCal } from "../plan";

interface PlanIndex { days: Record<string, { peak_kva: number }>; risk: RiskCal }
const addMonth = (m: string, k: number) => { const [y, mo] = m.split("-").map(Number); const d = new Date(Date.UTC(y, mo - 1 + k, 1)); return d.toISOString().slice(0, 7); };
/** When the month's bill was issued (live-year bills carry it; original-year bills are taken as the 5th of the next month). */
const issuedOn = (r: Recon | undefined, m: string) => (r?.bill_issued ? r.bill_issued.slice(0, 10) : `${addMonth(m, 1)}-05`);
const pct = (a: number, b: number) => (b ? `${a >= b ? "+" : "−"}${Math.abs((a / b - 1) * 100).toFixed(1)}%` : "—");

/** Monthly report for the general manager and the finance controller: one A4 page, built only from data available on the day the
 *  month's bill was issued, so it is the same whenever it is opened. Print or "Download PDF" uses the browser's print dialog. */
export default function Report() {
  const { now } = useClock();
  const billsNow = useBillsAt(now);
  const months = useMemo(() => [...new Set((billsNow?.recon ?? []).map((r) => r.month))].sort(), [billsNow]);
  const [month, setMonth] = useState<string | null>(null);
  useEffect(() => { if (months.length && (!month || !months.includes(month))) setMonth(months.at(-1)!); }, [months.join()]);
  const m = month ?? months.at(-1) ?? "";
  const asOfDate = issuedOn(billsNow?.recon.find((r) => r.month === m), m);
  const asOf = `${asOfDate}T09:00`;
  const bills = useBillsAt(asOf);
  const changes = useChangesAt(bills);
  const alerts = useAlertsAt(asOf);
  const sav = useMonthSavings(m, asOf);
  const idx = useData<PlanIndex>("plan/index.json");
  const past = useData<Record<string, ForecastDay>>("forecast_days.json");
  if (!m || !bills) return <p className="muted">Loading the report…</p>;

  const row = (s: Site, mm: string) => bills.recon.find((r) => r.site === s && r.month === mm);
  const sum = (mm: string) => SITES.reduce((x, s) => x + (row(s, mm)?.billed_total ?? 0), 0);
  const prev = addMonth(m, -1), ly = addMonth(m, -12);
  const total = sum(m), totPrev = sum(prev), totLy = sum(ly);
  // what drove the change vs last month, all three hotels (same-year or cross-year attribution, whichever exists)
  const groups: Record<string, number> = {};
  let have = 0;
  for (const s of SITES) { const c = changes?.[`${s}|${prev}|${m}`]; if (c) { have++; for (const [k, v] of Object.entries(c.groups)) groups[k] = (groups[k] ?? 0) + v; } }
  const steps = Object.entries(groups).filter(([, v]) => Math.abs(v) >= 1).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  const top = steps.slice(0, 6), rest = steps.slice(6).reduce((x, [, v]) => x + v, 0);
  const wf = [...top.map(([k, v]) => ({ label: DRIVER[k] ?? k, value: v })), ...(Math.abs(rest) >= 1 ? [{ label: "Other", value: rest }] : [])];
  // top problems in the month
  const probs = (alerts ?? []).filter((a) => a.start.slice(0, 7) === m && a.cost > 0).sort((a, b) => b.cost - a.cost).slice(0, 5);
  // next month's watch-outs: days forecast nearest the 1,000 kVA limit (Gurugram)
  const nm = addMonth(m, 1);
  const watch = (() => {
    const out: { d: string; peak: number; level: string }[] = [];
    if (idx) for (const [d, x] of Object.entries(idx.days)) if (d.startsWith(nm)) { const r = riskFor([x.peak_kva], idx.risk); out.push({ d, peak: r.peak, level: r.level }); }
    if (!out.length && past) for (const [d, f] of Object.entries(past)) if (d.startsWith(nm)) out.push({ d, peak: f.risk.peak, level: f.risk.level });
    return out.sort((a, b) => b.peak - a.peak).slice(0, 4);
  })();
  const p = sav.plan;
  const LEVEL: Record<string, string> = { "BREACH RISK": "risk of going over", WARNING: "close to the limit", "STACKING WATCH": "watch the afternoon", OK: "comfortable" };
  const recon = SITES.map((s) => row(s, m)).filter(Boolean) as Recon[];

  return (
    <div className="report">
      <div className="page-head no-print">
        <div><h1>Monthly report</h1><p className="lead">For the general manager and the finance controller. Made automatically from the data on the day each month's bill arrives; nothing to prepare.</p></div>
        <div className="btn-row" style={{ alignItems: "center" }}>
          <select className="month-pick" value={m} onChange={(e) => setMonth(e.target.value)}>{months.map((x) => <option key={x} value={x}>{fmtMonth(x)}</option>)}</select>
          <button className="btn accent" onClick={() => window.print()}>Download PDF</button>
        </div>
      </div>

      <section className="sheet">
        <header className="sheet-head">
          <div><h2>Saffron Suites · Electricity, {fmtMonth(m)}</h2><p className="small muted">Gurugram, Jaipur and Goa · as of {fmtD(asOfDate)}, when the bill was issued · tariff rates are illustrative{m >= "2026-10" ? " · meters from Oct 2026 are simulated" : ""}</p></div>
        </header>

        <div className="sheet-grid">
          <div>
            <h3>a) The bill</h3>
            <table className="t compact">
              <thead><tr><th></th><th className="r">{fmtMonth(m)}</th><th className="r">vs {fmtMonth(prev)}</th><th className="r">vs {fmtMonth(ly)}</th><th className="r">vs adjusted baseline</th></tr></thead>
              <tbody>
                {SITES.map((s) => { const r = row(s, m), a = row(s, prev), y = row(s, ly), c = sav.optionC?.bySite[s]; return (
                  <tr key={s}><td>{SITE_NAME[s]}</td><td className="r">{inr(r?.billed_total)}</td><td className="r">{a ? pct(r!.billed_total, a.billed_total) : "—"}</td>
                    <td className="r">{y ? pct(r!.billed_total, y.billed_total) : "—"}</td><td className="r">{c ? `${c.kwh >= 0 ? "−" : "+"}${Math.abs(c.kwh / Math.max(c.baseline, 1) * 100).toFixed(1)}% use` : "…"}</td></tr>); })}
                <tr className="tot"><td>All hotels</td><td className="r">{inr(total)}</td><td className="r">{totPrev ? `${inr(total - totPrev)} (${pct(total, totPrev)})` : "—"}</td>
                  <td className="r">{totLy ? `${inr(total - totLy)} (${pct(total, totLy)})` : "—"}</td><td className="r">{sav.optionC ? `${n(Math.abs(sav.optionC.kwh))} kWh ${sav.optionC.kwh >= 0 ? "below" : "above"}` : "…"}</td></tr>
              </tbody>
            </table>

            <h3>c) Savings this month</h3>
            <table className="t compact">
              <tbody>
                <tr><td>From the daily plan (verified)</td><td className="r">{m < "2026-10" ? "—" : p ? inr(p.totals.verified_inr) : p === null ? "unavailable" : "…"}</td></tr>
                <tr><td>From acting on alerts</td><td className="r">{sav.alerts ? inr(sav.alerts.inr) : "…"}</td></tr>
                <tr className="tot"><td>Total effect (Option C, all hotels)</td><td className="r">{sav.optionC ? inr(sav.optionC.inr) : "…"}</td></tr>
              </tbody>
            </table>
            <p className="tiny">Method: plan = followed steps only, meters vs matched days last year; alerts = waste caught, counted once and never for hours the plan covered; Option C = actual vs the weather-, occupancy- and event-adjusted baseline (IPMVP), the total however it is split.{m < "2026-10" ? " Daily plans started in Oct 2026." : ""}</p>

            <h3>d) Bill check</h3>
            <table className="t compact">
              <tbody>{recon.map((r) => (
                <tr key={r.site}><td>{SITE_NAME[r.site]}</td><td><Status s={r.status} /></td><td className="r">{Math.abs(r.billed_minus_corrected) < 1 ? "matches our meter" : `${r.billed_minus_corrected > 0 ? "billed" : "under-billed"} ${inr(Math.abs(r.billed_minus_corrected))}`}</td></tr>
              ))}</tbody>
            </table>
          </div>

          <div>
            <h3>b) What drove the change from {fmtMonth(prev)}</h3>
            {have === SITES.length && wf.length ? <Waterfall start={totPrev} end={total} startLabel={fmtMonth(prev)} endLabel={fmtMonth(m)} steps={wf} height={190} />
              : <p className="small muted">No comparison with {fmtMonth(prev)} is available for this month.</p>}

            <h3>e) Top problems in {fmtMonth(m)}</h3>
            <table className="t compact">
              <tbody>{probs.map((a) => (
                <tr key={a.id}><td>{a.hotel}: {RULE[a.rule]?.title ?? a.title}</td><td className="r">{inr(a.cost)}</td><td className="small">{a.end <= asOf ? "resolved" : "still running"}</td></tr>
              ))}{!probs.length && <tr><td className="muted">No costed problems this month.</td></tr>}</tbody>
            </table>
            <p className="small" style={{ margin: "8px 0 0" }}><strong>Watch in {fmtMonth(nm)} (Gurugram, 1,000 kVA limit): </strong>
              {watch.length ? watch.map((w) => `${fmtD(w.d).replace(/ \d{4}$/, "")} ${n(w.peak)} kVA (${LEVEL[w.level] ?? w.level})`).join("; ") : "no forecast yet for those days."}</p>
          </div>
        </div>
        <p className="tiny" style={{ marginTop: 6 }}>Recommend only: every change is approved by a person. {p?.honesty ?? ""}</p>
      </section>
    </div>
  );
}
