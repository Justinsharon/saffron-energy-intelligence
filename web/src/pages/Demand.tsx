import { useEffect, useState } from "react";
import { useClock } from "../App";
import { KVA } from "../components/parts";
import { useData, type ForecastDay } from "../data";
import { pickCell, useLiveDay, useLiveIndex, useWeather } from "../live";
import { addMs, DAY_MS, fmtD, iso, n, parse } from "../format";
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
              <h3>What to move on the day</h3>
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

function dow(d: string) { return ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][parse(d).getUTCDay()]; }

/** Live: a real future date, the real temperature forecast, and any conference the team enters. */
function LiveDay({ day, guests, tempOverride, showControls, setGuests, setTemp }: {
  day: string; guests: number; tempOverride: number | null; showControls: boolean; setGuests: (g: number) => void; setTemp: (t: number | null) => void;
}) {
  const wx = useWeather();
  const d = useLiveDay(day);
  const fcT = wx?.daily.GGN[day]?.tmax;
  if (d === undefined) return <p className="muted">Loading forecast…</p>;
  if (d === null) return <p className="muted">There is no forecast for {fmtD(day)} yet. Forecasts are prepared for the coming weeks.</p>;
  const t = tempOverride ?? fcT ?? d.template_tmax;
  const cell = pickCell(d, t, guests);
  const src = tempOverride != null ? "your setting" : fcT != null ? "weather forecast" : wx === null ? "typical for the time of year; weather forecast unavailable" : "typical for the time of year";
  return (
    <>
      {showControls && (
        <div className="panel" style={{ display: "flex", gap: 28, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
          <label style={{ flex: "1 1 240px" }}>
            <div className="small muted">Top temperature {tempOverride == null && fcT != null ? "(from the weather forecast)" : ""}</div>
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <input type="range" min={d.temps[0]} max={d.temps[d.temps.length - 1]} value={cell.t} onChange={(e) => setTemp(Number(e.target.value))} style={{ flex: 1, accentColor: "var(--saffron)" }} />
              <strong className="num" style={{ width: 52 }}>{cell.t} °C</strong>
            </div>
            {tempOverride != null && fcT != null && <button className="btn ghost" style={{ padding: "2px 8px", marginTop: 4 }} onClick={() => setTemp(null)}>Use the forecast ({Math.round(fcT)} °C)</button>}
          </label>
          <label style={{ flex: "1 1 240px" }}>
            <div className="small muted">Conference or banquet guests (9 am – 6 pm)</div>
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <input type="range" min={0} max={600} step={100} value={guests} onChange={(e) => setGuests(Number(e.target.value))} style={{ flex: 1, accentColor: "var(--saffron)" }} />
              <strong className="num" style={{ width: 52 }}>{guests}</strong>
            </div>
          </label>
        </div>
      )}
      <RiskBlock f={cell.f} title={`${dow(day)} ${fmtD(day)} · top ${cell.t} °C (${src}) · ${guests ? `${guests}-guest event` : "no events entered"}`} />
      {cell.clamped && <p className="small muted">The temperature is outside the range prepared for this date, so the nearest one ({cell.t} °C) is shown.</p>}
      <p className="muted small" style={{ marginTop: 14 }}>
        The forecast uses the real weather forecast and the hotel's usual pattern for a {dow(day)} at this time of year (rooms, restaurant, laundry).
        Event bookings aren't connected yet, so enter any conference or banquet in Plan ahead. On past days the forecast was usually within about 5% of the actual peak.
      </p>
    </>
  );
}

export default function Demand() {
  const { now, live, setNow } = useClock();
  const days = useData<Record<string, ForecastDay>>("forecast_days.json");
  const idx = useLiveIndex();
  const wx = useWeather();
  const [mode, setMode] = useState<"day" | "whatif">("day");
  const [pick, setPick] = useState<string | null>(null);
  const [temp, setTemp] = useState<number | null>(null);
  const [guests, setGuests] = useState(0);
  const tomorrow = iso(new Date(parse(now).getTime() + DAY_MS)).slice(0, 10);
  useEffect(() => { setPick(null); }, [live]);
  const day = pick ?? tomorrow;
  const f = days?.[day];
  const upcoming = idx ? Object.keys(idx).filter((d) => d >= tomorrow).sort() : [];
  const maxPlan = upcoming[upcoming.length - 1] ?? tomorrow;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Peak power demand, Gurugram</h1>
          <p className="lead">Gurugram's contract allows 1,000 kVA at any moment. Going over costs double for every extra kVA, all month: ₹88,218 in penalties in the last 12 months. Each of the three times it happened (12 May, 18 June, 25 June 2026), laundry, water heating and banquet cooling were running together on a hot afternoon.</p>
        </div>
        {live && (
          <div className="seg" role="group" aria-label="View">
            <button aria-pressed={mode === "day"} onClick={() => setMode("day")}>Tomorrow</button>
            <button aria-pressed={mode === "whatif"} onClick={() => setMode("whatif")}>Plan ahead</button>
          </div>
        )}
      </div>

      {live && mode === "day" && <LiveDay day={tomorrow} guests={0} tempOverride={null} showControls={false} setGuests={() => {}} setTemp={() => {}} />}

      {live && mode === "whatif" && (
        <>
          <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 12, flexWrap: "wrap" }}>
            <label htmlFor="pd" className="small muted">Day</label>
            <input id="pd" type="date" min={tomorrow} max={maxPlan} value={day} onChange={(e) => e.target.value && setPick(e.target.value)}
                   style={{ padding: "6px 8px", border: "1px solid var(--rule)", borderRadius: 4 }} />
            {upcoming.slice(0, 7).map((d) => (
              <button key={d} className="btn ghost" aria-pressed={d === day} style={{ padding: "4px 10px" }} onClick={() => { setPick(d); setTemp(null); }}>
                {dow(d).slice(0, 3)} {parse(d).getUTCDate()}{wx?.daily.GGN[d] ? ` · ${Math.round(wx.daily.GGN[d].tmax)}°` : ""}
              </button>
            ))}
          </div>
          <LiveDay day={day} guests={guests} tempOverride={temp} showControls setGuests={setGuests} setTemp={setTemp} />
        </>
      )}

      {!live && (
        <>
          <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 12, flexWrap: "wrap" }}>
            <label htmlFor="fd" className="small muted">Day</label>
            <input id="fd" type="date" min="2025-10-08" max="2026-09-30" value={day} onChange={(e) => setPick(e.target.value)}
                   style={{ padding: "6px 8px", border: "1px solid var(--rule)", borderRadius: 4 }} />
            {pick && <button className="btn ghost" onClick={() => setPick(null)}>Back to the next day</button>}
          </div>
          {!days ? <p className="muted">Loading forecast…</p> : !f ? <p className="muted">No forecast for {fmtD(day)}. Past forecasts are available from 8 Oct 2025 to 30 Sep 2026.</p> :
            <RiskBlock f={f} title={`Forecast for ${fmtD(day)}, made the day before, with what actually happened`} />}
          <p className="muted small" style={{ marginTop: 14 }}>Forecasts were usually within about 5% of the actual peak. Over the year the warning was raised on 14 days, including two of the three days the limit was broken. The first, 12 May, came before there was a past example to learn from.</p>
        </>
      )}

      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 18, flexWrap: "wrap" }}>
        <span className="small muted">See how the warning looked the day before the limit was broken:</span>
        {["2026-05-12", "2026-06-18", "2026-06-25"].map((d) => (
          <button key={d} className="btn ghost" style={{ padding: "4px 10px" }} onClick={() => { setNow(`${addMs(d + "T10:00", -DAY_MS).slice(0, 10)}T10:00`); setPick(null); }}>{fmtD(d)}</button>
        ))}
      </div>
    </>
  );
}
