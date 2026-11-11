import { useMemo, useState } from "react";
import { useClock } from "../App";
import { Ticket } from "../components/parts";
import { SITE_NAME, useData, type Alert, type Fault, type Quality, type Site } from "../data";
import { DATA_LAST, fmtD, fmtDT, inr, n, parse, pct } from "../format";
import { SiteSwitch } from "./Shift";
import { RULE } from "../copy";
const T = (a: Alert) => RULE[a.rule]?.title ?? a.title;

const START = Date.UTC(2025, 9, 1);
const WEEKS = 53;
function week(t: string) { return Math.floor((parse(t).getTime() - START) / (7 * 864e5)); }

export default function Engineering() {
  const { now: shown, live } = useClock();
  // History page: live, it covers the 12 months of meter data; looking back, everything up to that moment.
  const now = live ? `${DATA_LAST}T23:59` : shown;
  const alerts = useData<Alert[]>("alerts.json");
  const faults = useData<Fault[]>("faults.json");
  const q = useData<Quality>("quality.json");
  const [site, setSite] = useState<Site | "ALL">("GGN");
  const [sel, setSel] = useState<{ title: string; w: number } | null>(null);
  const nowW = week(now);

  const v = useMemo(() => {
    if (!alerts) return null;
    const seen = alerts.filter((a) => (site === "ALL" || a.site === site) && a.alert_time <= now);
    const types = [...new Set(seen.map(T))];
    const grid: Record<string, number[]> = {};
    for (const t of types) grid[t] = Array(WEEKS).fill(0);
    for (const a of seen) { const w = week(a.start); if (w >= 0 && w < WEEKS) grid[T(a)][w] += a.cost; }
    const byType = types.map((t) => {
      const xs = seen.filter((a) => T(a) === t);
      const last30 = xs.filter((a) => parse(now).getTime() - parse(a.alert_time).getTime() < 30 * 864e5);
      return { t, n: xs.length, cost: xs.reduce((s, a) => s + a.cost, 0), last30: last30.length, lag: median(xs.map((a) => a.detect_lag_h)),
               last: xs.map((a) => a.alert_time).sort().at(-1)!, hotels: [...new Set(xs.map((a) => a.site))] };
    }).sort((a, b) => b.cost - a.cost);
    const max = Math.max(1, ...Object.values(grid).flat());
    return { seen, byType, grid, max };
  }, [alerts, site, now]);

  const cellAlerts = sel && v ? v.seen.filter((a) => T(a) === sel.title && week(a.start) === sel.w) : [];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Equipment patterns</h1>
          <p className="lead">Which problems keep coming back, what they cost, and how quickly they are spotted. Fix the cause of a repeat problem, not each occurrence.{live ? " Covers the 12 months of meter data, October 2025 to September 2026." : ""}</p>
        </div>
        <SiteSwitch value={site} onChange={(s) => { setSite(s); setSel(null); }} />
      </div>

      <div className="panel">
        <h3>Waste week by week{site !== "ALL" ? `, ${SITE_NAME[site]}` : ""}</h3>
        <p className="muted small" style={{ marginTop: 0 }}>Darker means more money wasted that week. Click a square to see what happened.</p>
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
                                       background: w > nowW ? "transparent" : c === 0 ? "#f0f0f0" : `rgba(232,97,60,${0.18 + 0.82 * Math.sqrt(c / v.max)})` }} />
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

      <h2>Repeat problems</h2>
      {v && (
        <div className="panel scroll-x">
          <table className="t">
            <thead><tr><th>Problem</th><th>Hotels</th><th className="r">Times this year</th><th className="r">Last 30 days</th><th className="r">Cost</th><th className="r">Spotted after</th><th>Last seen</th></tr></thead>
            <tbody>{v.byType.map((r) => (
              <tr key={r.t}>
                <td><strong>{r.t}</strong></td><td>{r.hotels.map((s) => SITE_NAME[s]).join(", ")}</td><td className="r">{r.n}</td>
                <td className="r" style={{ color: r.last30 >= 2 ? "var(--red)" : undefined, fontWeight: r.last30 >= 2 ? 700 : 400 }}>{r.last30}</td>
                <td className="r">{inr(r.cost)}</td><td className="r">{n(Math.max(1, r.lag), 0)} h</td><td>{fmtDT(r.last, false)}</td>
              </tr>
            ))}</tbody>
          </table>
          <p className="muted small" style={{ marginBottom: 0 }}>Red means it happened twice or more in the last 30 days. Fix the schedule, setting or panel behind it rather than each occurrence.</p>
        </div>
      )}

      <div className="grid g2" style={{ marginTop: 24 }}>
        <div className="panel">
          <h3>Compared with your current building alarms</h3>
          {q && (
            <table className="t">
              <thead><tr><th></th><th className="r">Building alarms</th><th className="r">Saffron Energy</th></tr></thead>
              <tbody>
                <tr><td>Alerts that turn out to be real problems</td><td className="r">{Math.round(q.bms.precision * 100)} in 100</td><td className="r"><strong>{Math.round(q.frozen.precision_any * 100)} in 100</strong></td></tr>
                <tr><td>Serious problems that get flagged</td><td className="r">{Math.round(q.bms.recall * 100)} in 100</td><td className="r"><strong>{Math.round(q.frozen.recall_HM * 100)} in 100</strong></td></tr>
                <tr><td>Time until someone knows</td><td className="r">{q.bms.median_action_h} hours</td><td className="r"><strong>about 1 hour</strong></td></tr>
                <tr><td>Alerts a year, all three hotels</td><td className="r">{n(q.bms.alarms)}</td><td className="r"><strong>{n(alerts?.filter((a) => a.channel === "Alert").length ?? 0)}</strong></td></tr>
              </tbody>
            </table>
          )}
          <p className="muted small" style={{ marginBottom: 0 }}>Checked against {q?.frozen.n_labels ?? 69} confirmed problems from April to September 2026, which the system had not seen before.</p>
        </div>
        <div className="panel">
          <h3>Meter reading problems</h3>
          <table className="t">
            <thead><tr><th>Hotel</th><th>When</th><th>What went wrong</th><th className="r">Hours</th></tr></thead>
            <tbody>{faults?.map((f) => (
              <tr key={f.start}><td>{f.hotel}</td><td>{fmtDT(f.start, false)}</td><td>{f.kind === "flat line" ? "Reading stuck" : f.kind === "zero reading" ? "Reading zero" : f.kind === "missing readings" ? "No readings" : f.kind}</td><td className="r">{n(f.duration_h, 1)}</td></tr>
            ))}</tbody>
          </table>
          <p className="muted small" style={{ marginBottom: 0 }}>When the main meter sends bad readings, those hours are left out, so they never cause false alerts or count as savings. Bills issued on bad readings are shown next to the corrected figure in Bills & savings.</p>
        </div>
      </div>
    </>
  );
}

function median(xs: number[]) { const s = [...xs].sort((a, b) => a - b); return s.length ? s[Math.floor(s.length / 2)] : NaN; }
