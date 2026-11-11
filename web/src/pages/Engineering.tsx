import { useMemo, useState } from "react";
import { useClock } from "../App";
import { Ticket } from "../components/parts";
import { SITE_NAME, useData, type Alert, type Fault, type Quality, type Site } from "../data";
import { fmtD, fmtDT, inr, n, parse, pct } from "../format";
import { SiteSwitch } from "./Shift";

const START = Date.UTC(2025, 9, 1);
const WEEKS = 53;
function week(t: string) { return Math.floor((parse(t).getTime() - START) / (7 * 864e5)); }

export default function Engineering() {
  const { now } = useClock();
  const alerts = useData<Alert[]>("alerts.json");
  const faults = useData<Fault[]>("faults.json");
  const q = useData<Quality>("quality.json");
  const [site, setSite] = useState<Site | "ALL">("GGN");
  const [sel, setSel] = useState<{ title: string; w: number } | null>(null);
  const nowW = week(now);

  const v = useMemo(() => {
    if (!alerts) return null;
    const seen = alerts.filter((a) => (site === "ALL" || a.site === site) && a.alert_time <= now);
    const types = [...new Set(seen.map((a) => a.title))];
    const grid: Record<string, number[]> = {};
    for (const t of types) grid[t] = Array(WEEKS).fill(0);
    for (const a of seen) { const w = week(a.start); if (w >= 0 && w < WEEKS) grid[a.title][w] += a.cost; }
    const byType = types.map((t) => {
      const xs = seen.filter((a) => a.title === t);
      const last30 = xs.filter((a) => parse(now).getTime() - parse(a.alert_time).getTime() < 30 * 864e5);
      return { t, n: xs.length, cost: xs.reduce((s, a) => s + a.cost, 0), last30: last30.length, lag: median(xs.map((a) => a.detect_lag_h)),
               last: xs.map((a) => a.alert_time).sort().at(-1)!, hotels: [...new Set(xs.map((a) => a.site))] };
    }).sort((a, b) => b.cost - a.cost);
    const max = Math.max(1, ...Object.values(grid).flat());
    return { seen, byType, grid, max };
  }, [alerts, site, now]);

  const cellAlerts = sel && v ? v.seen.filter((a) => a.title === sel.title && week(a.start) === sel.w) : [];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Engineering review</h1>
          <p className="lead">What keeps coming back, what it costs, and how fast it is caught. Darker squares cost more that week; click one to see its alerts.</p>
        </div>
        <SiteSwitch value={site} onChange={(s) => { setSite(s); setSel(null); }} />
      </div>

      <div className="panel">
        <h3>Waste by type and week, Oct 2025 – Sep 2026{site !== "ALL" ? `, ${SITE_NAME[site]}` : ""}</h3>
        {!v ? <p className="muted">Loading…</p> : (
          <div className="scroll-x">
            <div style={{ minWidth: 820 }}>
              {v.byType.map((r) => (
                <div key={r.t} style={{ display: "grid", gridTemplateColumns: "250px 1fr", alignItems: "center", gap: 10, marginBottom: 3 }}>
                  <div className="small" style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }} title={r.t}>{r.t}</div>
                  <div className="heat" style={{ gridTemplateColumns: `repeat(${WEEKS}, 1fr)` }}>
                    {v.grid[r.t].map((c, w) => (
                      <button key={w} className="cell" aria-label={`${r.t}, week ${w + 1}: ${inr(c)}`}
                              onClick={() => c > 0 && setSel({ title: r.t, w })}
                              style={{ border: 0, padding: 0, cursor: c > 0 ? "pointer" : "default",
                                       outline: sel && sel.title === r.t && sel.w === w ? "2px solid var(--ink)" : undefined,
                                       background: w > nowW ? "transparent" : c === 0 ? "#edf0f1" : `rgba(196,53,31,${0.18 + 0.82 * Math.sqrt(c / v.max)})` }} />
                    ))}
                  </div>
                </div>
              ))}
              <div style={{ display: "grid", gridTemplateColumns: "250px 1fr", gap: 10 }}>
                <div />
                <div style={{ position: "relative", height: 18 }} className="small muted">
                  {[["Oct", 2025, 9], ["Dec", 2025, 11], ["Feb", 2026, 1], ["Apr", 2026, 3], ["Jun", 2026, 5], ["Aug", 2026, 7]].map(([m, y, mo]) => (
                    <span key={m as string} style={{ position: "absolute", left: `${((Date.UTC(y as number, mo as number, 1) - START) / (7 * 864e5)) / WEEKS * 100}%` }}>{m}</span>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {sel && (
        <div style={{ marginTop: 14 }}>
          <h3>{sel.title}, week of {fmtD(new Date(START + sel.w * 7 * 864e5))}</h3>
          {cellAlerts.map((a) => <Ticket key={a.id} a={a} />)}
        </div>
      )}

      <h2>Recurring faults</h2>
      {v && (
        <div className="panel scroll-x">
          <table className="t">
            <thead><tr><th>Type</th><th>Hotels</th><th className="r">Alerts</th><th className="r">Last 30 days</th><th className="r">₹ flagged</th><th className="r">Median time to alert</th><th>Last seen</th></tr></thead>
            <tbody>{v.byType.map((r) => (
              <tr key={r.t}>
                <td><strong>{r.t}</strong></td><td>{r.hotels.map((s) => SITE_NAME[s]).join(", ")}</td><td className="r">{r.n}</td>
                <td className="r" style={{ color: r.last30 >= 2 ? "var(--red)" : undefined, fontWeight: r.last30 >= 2 ? 700 : 400 }}>{r.last30}</td>
                <td className="r">{inr(r.cost)}</td><td className="r">{n(r.lag, 1)} h</td><td>{fmtDT(r.last, false)}</td>
              </tr>
            ))}</tbody>
          </table>
          <p className="muted small" style={{ marginBottom: 0 }}>Red: two or more in the last 30 days — treat as a standing fault, not a one-off (fix the schedule, interlock or panel, not the symptom).</p>
        </div>
      )}

      <div className="grid g2" style={{ marginTop: 24 }}>
        <div className="panel">
          <h3>How well it detects</h3>
          {q && (
            <table className="t">
              <thead><tr><th></th><th className="r">BMS alarms today</th><th className="r">This product</th></tr></thead>
              <tbody>
                <tr><td>Alerts that are real waste</td><td className="r">{pct(q.bms.precision)}</td><td className="r"><strong>{pct(q.frozen.precision_any, 1)}</strong></td></tr>
                <tr><td>High + Medium waste caught</td><td className="r">{pct(q.bms.recall)}</td><td className="r"><strong>{pct(q.frozen.recall_HM, 1)}</strong></td></tr>
                <tr><td>Time to act / detect</td><td className="r">{q.bms.median_action_h} h</td><td className="r"><strong>1.0 h</strong></td></tr>
                <tr><td>Closed with no action</td><td className="r">{pct(q.bms.closed_no_action)}</td><td className="r">see ratings</td></tr>
              </tbody>
            </table>
          )}
          <p className="muted small" style={{ marginBottom: 0 }}>Scored on the {q?.frozen.n_labels ?? 69} labelled anomalies from 1 Apr 2026, which the detector never saw while it was tuned. Rules added after that freeze are labelled post-hoc and excluded.</p>
        </div>
        <div className="panel">
          <h3>Meter data faults (kept out of alerts and savings)</h3>
          <table className="t">
            <thead><tr><th>Hotel</th><th>When</th><th>Kind</th><th className="r">Hours</th></tr></thead>
            <tbody>{faults?.map((f) => (
              <tr key={f.start}><td>{f.hotel}</td><td>{fmtDT(f.start, false)}</td><td>{f.kind}</td><td className="r">{n(f.duration_h, 1)}</td></tr>
            ))}</tbody>
          </table>
          <p className="muted small" style={{ marginBottom: 0 }}>Found from the billed readings themselves (frozen or zero while live kW keeps moving). Bills issued on those readings are left as issued; Finance shows the corrected figure beside them.</p>
        </div>
      </div>
    </>
  );
}

function median(xs: number[]) { const s = [...xs].sort((a, b) => a - b); return s.length ? s[Math.floor(s.length / 2)] : NaN; }
