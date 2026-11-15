import { useState } from "react";
import { SITE_NAME, SITES } from "../data";
import { fmtMonth, inr, n } from "../format";
import { useMonthSavings } from "../monthSavings";

/** Live months: plan savings (verified), alert savings, and the Option C total, side by side - never added together twice. */
export function MonthSavingsPanel({ now }: { now: string }) {
  const months: string[] = [];
  for (let d = new Date(Date.UTC(2026, 9, 1)); d.toISOString().slice(0, 7) <= now.slice(0, 7); d = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1)))
    months.push(d.toISOString().slice(0, 7));
  const [month, setMonth] = useState(months.at(-1) ?? now.slice(0, 7));
  const m = useMonthSavings(month, now);
  const p = m.plan;
  if (!months.length) return null;
  return (
    <>
      <div className="section-title"><h2>Savings this month, so far</h2>
        <select value={month} onChange={(e) => setMonth(e.target.value)} className="month-pick">{months.map((x) => <option key={x} value={x}>{fmtMonth(x)}</option>)}</select></div>
      <div className="grid g3">
        <div className="stat"><span>From acting on alerts</span><b>{m.alerts ? inr(m.alerts.inr) : "…"}</b>
          <em>{m.alerts ? `${m.alerts.alerts} alerts in ${fmtMonth(month)}; waste caught, counted once fixed${m.alerts.dropped_inr >= 1 ? ` (${inr(m.alerts.dropped_inr)} left out: the daily plan already covered those hours)` : ""}` : "loading"}</em></div>
        <div className="stat"><span>From the daily plan (verified)</span><b>{p ? inr(p.totals.verified_inr) : p === null ? "—" : "…"}</b>
          <em>{p ? `${p.totals.days} days checked (${p.totals.saved_days} with a saved plan, the rest the suggested plan); ${inr(p.totals.planned_inr)} planned, ${inr(p.totals.missed_inr)} missed`
            : p === null ? "the planning service did not answer" : "checking the meters"}</em></div>
        <div className="stat"><span>Total effect (Option C)</span><b style={{ color: m.optionC && m.optionC.inr < 0 ? "var(--coral)" : undefined }}>{m.optionC ? inr(m.optionC.inr) : "…"}</b>
          <em>{m.optionC ? `${n(m.optionC.kwh)} kWh ${m.optionC.kwh >= 0 ? "below" : "above"} what the weather, guests and events called for, all three hotels` : "loading"}</em></div>
      </div>
      {m.optionC && (
        <div className="panel flat" style={{ marginTop: 12 }}>
          <table className="t">
            <thead><tr><th>Hotel</th><th className="r">Used</th><th className="r">Adjusted baseline</th><th className="r">Difference</th><th className="r">₹ at the bill's average rate</th></tr></thead>
            <tbody>{SITES.map((s) => { const x = m.optionC!.bySite[s]; return (
              <tr key={s}><td>{SITE_NAME[s]}</td><td className="r">{n(x.actual)} kWh</td><td className="r">{n(x.baseline)} kWh</td>
                <td className="r">{x.kwh >= 0 ? "−" : "+"}{n(Math.abs(x.kwh))} kWh ({x.baseline ? Math.abs(x.kwh / x.baseline * 100).toFixed(1) : "0"}%)</td><td className="r">{inr(x.inr)}</td></tr>); })}</tbody>
          </table>
          <p className="muted small" style={{ marginBottom: 0 }}>A rupee counts as a plan saving or an alert saving, never both. Option C (the IPMVP whole-building check) is the total, however it is split; the gap between the split and the total is model noise and anything not yet tied to an action. {p?.honesty}</p>
        </div>
      )}
    </>
  );
}
