import { useState } from "react";
import { useClock } from "../App";
import { KVA } from "../components/parts";
import { useData, type ForecastDay, type WhatIf } from "../data";
import { fmtD, iso, n, parse } from "../format";

function RiskBlock({ f, title }: { f: ForecastDay; title: string }) {
  const r = f.risk;
  const cls = r.level === "BREACH RISK" ? "breach" : r.level === "WARNING" ? "warn" : r.level === "OK" ? "ok" : "";
  const label = r.level === "OK" ? "No demand risk" : r.level.charAt(0) + r.level.slice(1).toLowerCase();
  return (
    <>
      <div className={`banner ${cls}`}>
        <div>
          <div style={{ fontSize: 13, color: "var(--ink-3)" }}>{title}</div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>{label}{r.level !== "OK" && <span style={{ fontWeight: 500, fontSize: 15, color: "var(--ink-2)" }}> at {r.hour}:00</span>}</div>
          {r.why && <div className="small" style={{ color: "var(--ink-2)", maxWidth: "70ch" }}>{r.why[0].toUpperCase() + r.why.slice(1)}.</div>}
        </div>
      </div>
      <div className="grid g4" style={{ margin: "14px 0" }}>
        <div className="stat"><span>Forecast peak</span><b>{n(r.peak)} kVA</b><em>model {n(r.raw_peak)} × {r.bias.toFixed(3)} peak correction</em></div>
        <div className="stat"><span>Chance above 1,000 kVA</span><b>{r.p_exceed == null ? "—" : `${Math.round(r.p_exceed * 100)}%`}</b><em>from earlier days' forecast errors</em></div>
        <div className="stat"><span>90% upper bound</span><b>{n(r.upper)} kVA</b><em>9 days in 10 stay below</em></div>
        <div className="stat"><span>If shiftable loads stack</span><b style={{ color: r.stack_peak >= 1000 ? "var(--red)" : undefined }}>{n(r.stack_peak)} kVA</b><em>+{n(r.stack_increment)} kVA: {r.stack_basis}</em></div>
      </div>
      <div className="split">
        <div className="panel"><KVA hoursArr={f.hours} pred={f.pred} actual={f.actual} stack={r.stack_peak} /></div>
        <div>
          {f.plan ? (
            <div className="panel">
              <h3>Move these loads</h3>
              <p className="muted small" style={{ marginTop: 0 }}>Recommend only; a person approves each. Chillers, kitchen, lifts, guest rooms and life-safety are never shed.</p>
              <table className="t">
                <thead><tr><th>Load</th><th>What to do</th><th className="r">Relief</th></tr></thead>
                <tbody>{f.plan.map((p) => (
                  <tr key={p.load}><td><strong>{p.load}</strong></td><td className="small">{p.action}</td><td className="r">{n(p.relief_kva)} kVA</td></tr>
                ))}</tbody>
              </table>
            </div>
          ) : <div className="panel flat"><h3>No moves needed</h3><p className="muted small" style={{ margin: 0 }}>Forecast and stacking scenario both stay under the 900 kVA watch line.</p></div>}
          <div className="panel flat" style={{ marginTop: 12 }}>
            <h3>What stacked on the breach days</h3>
            <table className="t">
              <thead><tr><th>Load</th><th className="r">Drew</th><th className="r">Usual</th><th className="r">Extra</th></tr></thead>
              <tbody>{f.stack_table.map((s) => (
                <tr key={s.load}><td>{s.load}</td><td className="r">{s.actual_kw != null ? `${n(s.actual_kw)} kW` : "—"}</td><td className="r">{s.typical_kw != null ? `${n(s.typical_kw)} kW` : "—"}</td><td className="r">{n(s.extra_kw)} kW</td></tr>
              ))}</tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  );
}

export default function Demand() {
  const { now } = useClock();
  const days = useData<Record<string, ForecastDay>>("forecast_days.json");
  const wi = useData<WhatIf>("forecast_whatif.json");
  const [mode, setMode] = useState<"day" | "whatif">("day");
  const [pick, setPick] = useState<string | null>(null);
  const [temp, setTemp] = useState(40);
  const [guests, setGuests] = useState(300);
  const day = pick ?? iso(new Date(parse(now).getTime() + 864e5)).slice(0, 10);
  const f = days?.[day];
  const g = wi?.grid[`${temp}|${guests}`];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Contract demand, Gurugram</h1>
          <p className="lead">Gurugram pays a 2× penalty on every kVA above its 1,000 kVA contract. All three breaches this year (12 May, 18 Jun, 25 Jun) came from laundry, water heating and banquet AHUs piling up on a hot afternoon.</p>
        </div>
        <div className="seg" role="group" aria-label="View">
          <button aria-pressed={mode === "day"} onClick={() => setMode("day")}>Day-ahead forecast</button>
          <button aria-pressed={mode === "whatif"} onClick={() => setMode("whatif")}>What if tomorrow…</button>
        </div>
      </div>

      {mode === "day" && (
        <>
          <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 12, flexWrap: "wrap" }}>
            <label htmlFor="fd" className="small muted">Day</label>
            <input id="fd" type="date" min="2025-10-08" max="2026-09-30" value={day} onChange={(e) => setPick(e.target.value)}
                   style={{ padding: "6px 8px", border: "1px solid var(--rule)", borderRadius: 4 }} />
            {pick && <button className="btn ghost" onClick={() => setPick(null)}>Back to tomorrow</button>}
            <span className="small muted">Shortcuts:</span>
            {["2026-05-12", "2026-06-18", "2026-06-25"].map((d) => <button key={d} className="btn ghost" style={{ padding: "4px 10px" }} onClick={() => setPick(d)}>{fmtD(d)}</button>)}
          </div>
          {!days ? <p className="muted">Loading forecast…</p> : !f ? <p className="muted">No forecast for {fmtD(day)}. The data covers 8 Oct 2025 – 30 Sep 2026.</p> :
            <RiskBlock f={f} title={`Forecast for ${fmtD(day)}, made the day before`} />}
          <p className="muted small" style={{ marginTop: 14 }}>Replayed day by day with only earlier data, the breach-risk warning fired on 14 days and caught 18 Jun and 25 Jun; 12 May had no earlier breach to learn from. Daily-peak accuracy: 5.4% mean error, 59% of days within ±5%.</p>
        </>
      )}

      {mode === "whatif" && (
        <>
          <div className="panel" style={{ display: "flex", gap: 28, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
            <label style={{ flex: "1 1 240px" }}>
              <div className="small muted">Tomorrow's maximum temperature</div>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <input type="range" min={30} max={46} value={temp} onChange={(e) => setTemp(Number(e.target.value))} style={{ flex: 1, accentColor: "var(--saffron)" }} />
                <strong className="num" style={{ width: 52 }}>{temp} °C</strong>
              </div>
            </label>
            <label style={{ flex: "1 1 240px" }}>
              <div className="small muted">Conference guests, 09:00–18:00</div>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <input type="range" min={0} max={600} step={50} value={guests} onChange={(e) => setGuests(Number(e.target.value))} style={{ flex: 1, accentColor: "var(--saffron)" }} />
                <strong className="num" style={{ width: 52 }}>{guests}</strong>
              </div>
            </label>
          </div>
          {!g ? <p className="muted">Loading scenarios…</p> : <RiskBlock f={g} title={`A weekday at ${temp} °C${guests ? ` with a ${guests}-guest conference` : ""}`} />}
        </>
      )}
    </>
  );
}
