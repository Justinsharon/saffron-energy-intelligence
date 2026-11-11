import { useState } from "react";
import { useClock } from "../App";
import { KVA } from "../components/parts";
import { useData, type ForecastDay, type WhatIf } from "../data";
import { fmtD, iso, n, parse } from "../format";
import { LOAD } from "../copy";

const HEAD: Record<string, string> = {
  "BREACH RISK": "Risk of going over the limit",
  WARNING: "Close to the limit",
  "STACKING WATCH": "Watch the afternoon",
  OK: "Comfortably under the limit",
};

function RiskBlock({ f, title }: { f: ForecastDay; title: string }) {
  const r = f.risk;
  const cls = r.level === "BREACH RISK" ? "breach" : r.level === "WARNING" ? "warn" : r.level === "OK" ? "ok" : "";
  const stackOver = r.stack_peak >= 1000;
  const reason = r.level === "OK" ? "Even if laundry, water heating and banquet cooling overlap in the afternoon, demand stays below the limit."
    : stackOver ? `On its own the hotel should peak around ${n(r.peak)} kVA. But if laundry, water heating and banquet cooling all run in the afternoon, as on the days the limit was broken, it could reach ${n(r.stack_peak)} kVA.`
    : r.upper >= 920 ? `On a bad day the peak could reach ${n(r.upper)} kVA, close to the 1,000 kVA limit.`
    : `Peak around ${n(r.peak)} kVA; it only gets close if the flexible loads pile up in the afternoon.`;
  return (
    <>
      <div className={`banner ${cls}`}>
        <div>
          <div style={{ fontSize: 13, color: "var(--ink-3)" }}>{title}</div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>{HEAD[r.level]}{r.level !== "OK" && <span style={{ fontWeight: 500, fontSize: 15, color: "var(--ink-2)" }}> around {r.hour}:00</span>}</div>
          <div className="small" style={{ color: "var(--ink-2)", maxWidth: "75ch" }}>{reason}</div>
        </div>
      </div>
      <div className="grid g4" style={{ margin: "16px 0" }}>
        <div className="stat"><span>Expected peak</span><b>{n(r.peak)} kVA</b><em>around {r.hour}:00</em></div>
        <div className="stat"><span>Chance of going over 1,000 kVA</span><b>{r.p_exceed == null ? "—" : `${Math.round(r.p_exceed * 100)}%`}</b><em>based on how past forecasts turned out</em></div>
        <div className="stat"><span>On a bad day</span><b>{n(r.upper)} kVA</b><em>9 days out of 10 stay below this</em></div>
        <div className="stat"><span>If flexible loads overlap</span><b style={{ color: stackOver ? "var(--red)" : undefined }}>{n(r.stack_peak)} kVA</b><em>adds {n(r.stack_increment)} kVA, as on the days the limit was broken</em></div>
      </div>
      <div className="split">
        <div className="panel"><KVA hoursArr={f.hours} pred={f.pred} actual={f.actual} stack={r.stack_peak} /></div>
        <div>
          {f.plan ? (
            <div className="panel">
              <h3>What to move tomorrow</h3>
              <p className="muted small" style={{ marginTop: 0 }}>Suggestions for the team to approve. Chillers, kitchens, lifts, guest rooms and safety systems are never cut.</p>
              <table className="t">
                <thead><tr><th>Load</th><th>Suggestion</th><th className="r">Frees up</th></tr></thead>
                <tbody>{f.plan.map((p) => (
                  <tr key={p.load}><td><strong>{LOAD[p.load] ?? p.load}</strong></td><td className="small">{p.action.replace("banquet-hall AHU", "banquet hall cooling").replace("heat-pump water heating", "water heating")}</td><td className="r">{n(p.relief_kva)} kVA</td></tr>
                ))}</tbody>
              </table>
            </div>
          ) : <div className="panel flat"><h3>Nothing to move</h3><p className="muted small" style={{ margin: 0 }}>Demand stays well under the limit even if the flexible loads overlap.</p></div>}
          <div className="panel flat" style={{ marginTop: 12 }}>
            <h3>What piled up on the days the limit was broken</h3>
            <table className="t">
              <thead><tr><th>Load</th><th className="r">Drew</th><th className="r">Normally</th><th className="r">Extra</th></tr></thead>
              <tbody>{f.stack_table.map((s) => (
                <tr key={s.load}><td>{LOAD[s.load] ?? s.load}</td><td className="r">{s.actual_kw != null ? `${n(s.actual_kw)} kW` : "—"}</td><td className="r">{s.typical_kw != null ? `${n(s.typical_kw)} kW` : "—"}</td><td className="r">{n(s.extra_kw)} kW</td></tr>
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
          <h1>Peak power demand, Gurugram</h1>
          <p className="lead">Gurugram's contract allows 1,000 kVA at any moment. Going over costs double for every extra kVA, all month: ₹88,218 in penalties this year. Each of the three times it happened (12 May, 18 June, 25 June), laundry, water heating and banquet cooling were running together on a hot afternoon.</p>
        </div>
        <div className="seg" role="group" aria-label="View">
          <button aria-pressed={mode === "day"} onClick={() => setMode("day")}>Tomorrow</button>
          <button aria-pressed={mode === "whatif"} onClick={() => setMode("whatif")}>Plan ahead</button>
        </div>
      </div>

      {mode === "day" && (
        <>
          <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 12, flexWrap: "wrap" }}>
            <label htmlFor="fd" className="small muted">Day</label>
            <input id="fd" type="date" min="2025-10-08" max="2026-09-30" value={day} onChange={(e) => setPick(e.target.value)}
                   style={{ padding: "6px 8px", border: "1px solid var(--rule)", borderRadius: 4 }} />
            {pick && <button className="btn ghost" onClick={() => setPick(null)}>Back to tomorrow</button>}
            <span className="small muted">Days the limit was broken:</span>
            {["2026-05-12", "2026-06-18", "2026-06-25"].map((d) => <button key={d} className="btn ghost" style={{ padding: "4px 10px" }} onClick={() => setPick(d)}>{fmtD(d)}</button>)}
          </div>
          {!days ? <p className="muted">Loading forecast…</p> : !f ? <p className="muted">No forecast for {fmtD(day)}. Forecasts are available from 8 Oct 2025 to 30 Sep 2026.</p> :
            <RiskBlock f={f} title={`Forecast for ${fmtD(day)}, made the day before`} />}
          <p className="muted small" style={{ marginTop: 14 }}>Forecasts are usually within about 5% of the actual peak. Over the year the warning was raised on 14 days, including two of the three days the limit was broken. The first, 12 May, came before there was a past example to learn from.</p>
        </>
      )}

      {mode === "whatif" && (
        <>
          <div className="panel" style={{ display: "flex", gap: 28, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
            <label style={{ flex: "1 1 240px" }}>
              <div className="small muted">Tomorrow's top temperature</div>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <input type="range" min={30} max={46} value={temp} onChange={(e) => setTemp(Number(e.target.value))} style={{ flex: 1, accentColor: "var(--saffron)" }} />
                <strong className="num" style={{ width: 52 }}>{temp} °C</strong>
              </div>
            </label>
            <label style={{ flex: "1 1 240px" }}>
              <div className="small muted">Conference guests (9 am – 6 pm)</div>
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
