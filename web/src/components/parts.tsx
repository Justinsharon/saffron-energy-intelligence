import { useEffect, useState } from "react";
import { CartesianGrid, ComposedChart, Line, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis, Bar, Cell, ReferenceLine, LabelList } from "recharts";
import type { Alert } from "../data";
import { fmtDT, hours, inr, n, parse } from "../format";
import { BILL_STATUS, EQUIPMENT, PRIORITY, RULE, SAFETY } from "../copy";

/** Equipment tag plate: the label engraved on the plant item the alert is about. */
const TAG: Record<string, [string, string]> = {
  AHU_HAND_MODE: ["AHU-BQ", "Banquet cooling"], HEAT_COOL_FIGHT: ["AHU-RH", "Re-heaters"], KITCHEN_EXHAUST_OFF_HOURS: ["KEF", "Kitchen fans"],
  LIGHTING_LEFT_ON: ["LTG", "Event lighting"], LAUNDRY_IN_PEAK: ["LDY", "Laundry"], POOL_PUMP_OFF_SCHEDULE: ["PP", "Pool pumps"],
  POWER_FACTOR_DROP: ["APFC", "Capacitor panel"], CHILLER_STAGING_LOW_LOAD: ["CH-1/3", "Chiller plant"], STAGING_KWTR: ["CH-1/3", "Chiller plant"],
  CHILLER_PART_LOAD_INEFFICIENCY: ["CH-A/B", "Chillers"], CHW_SETPOINT_LOW: ["CHW-SP", "Chilled water"], DEMAND_NEAR_CONTRACT: ["MAIN", "Main supply"],
  EV_CHARGER_NIGHT_ON: ["EVC", "EV chargers"], RESIDUAL_UNEXPLAINED: ["MAIN", "Whole hotel"],
};
export function TagPlate({ rule, severity, site }: { rule: string; severity: string; site: string }) {
  const [code, where] = TAG[rule] ?? ["EQ", "Equipment"];
  return (
    <div className={`plate ${severity.toLowerCase()}`} aria-label={`${where}, ${site}`}>
      <span className="code">{code}</span>
      <span className="where">{site} · {where}</span>
    </div>
  );
}

export function Sev({ s }: { s: string }) {
  const cls = s === "High" ? "c-high" : s === "Medium" ? "c-med" : "c-low";
  return <span className={`chip ${cls}`}>{PRIORITY[s] ?? s}</span>;
}
export function Status({ s }: { s: string }) {
  const b = BILL_STATUS[s] ?? { label: s, tone: "med" };
  return <span className={`chip c-${b.tone}`}>{b.label}</span>;
}

const SIGNAL_LABEL: Record<string, string> = {
  ahu_banquet_kw: "Banquet hall air handlers (kW)", ev_guests: "Event guests", ahu_heaters_kw: "Re-heaters (kW)", temp_c: "Outside temperature (°C)",
  kitchen_exhaust_kw: "Kitchen extract fans (kW)", lighting_kw: "Lighting (kW)", laundry_kw: "Laundry (kW)", pool_pump_kw: "Pool pumps (kW)",
  pf: "Power factor (1.0 is ideal)", chillers_kw: "Chillers (kW)", chiller_load_tr: "Cooling delivered (tons)",
  n_chillers: "Chillers shown running", kw_per_tr: "Chiller power per ton of cooling (lower is better)", chw_setpoint_c: "Chilled-water temperature setting (°C)",
  kva_max_in_hour: "Peak power demand (kVA)", ev_chargers_kw: "EV chargers (kW)",
};
const SIG_COLORS = ["#c27a12", "#6b4c9a", "#2f7a57"];

function tick(t: string) {
  const d = parse(t);
  return `${d.getUTCDate()}/${d.getUTCMonth() + 1} ${String(d.getUTCHours()).padStart(2, "0")}h`;
}

/** Main meter vs baseline, then the equipment signals, with the alert window shaded. */
export function Evidence({ a, upto }: { a: Alert; upto?: string }) {
  const ch = a.chart;
  const cut = upto ? ch.t.findIndex((t) => t > upto.slice(0, 13)) : -1;
  const N = cut > 0 ? cut : ch.t.length;
  const rows = ch.t.slice(0, N).map((t, i) => {
    const r: Record<string, number | string | null> = { t, actual: ch.actual[i], baseline: ch.baseline[i] };
    for (const [k, v] of Object.entries(ch.signals)) r[k] = v[i];
    return r;
  });
  const x0 = a.start.slice(0, 13), x1 = (upto && upto < a.end ? upto : a.end).slice(0, 13);
  const sigs = Object.keys(ch.signals);
  const small = sigs.filter((s) => RATIO.has(s));          // ratios and states get their own scale, or they flatten to zero
  const big = sigs.filter((s) => !RATIO.has(s));
  return (
    <div>
      <div className="legend" style={{ marginBottom: 4 }}>
        <span><i style={{ background: "#17212a" }} />Electricity the hotel used (kW)</span>
        <span><i style={{ background: "#2b6c8f" }} />What it should use for that weather, guests and events</span>
        <span><i style={{ background: "#e3a23b", height: 8, opacity: 0.4 }} />While the problem ran</span>
      </div>
      <ResponsiveContainer width="100%" height={190}>
        <ComposedChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
          <CartesianGrid stroke="#e8ecee" vertical={false} />
          <XAxis dataKey="t" tickFormatter={tick} minTickGap={50} tick={{ fontSize: 11, fill: "#7b8792" }} />
          <YAxis tick={{ fontSize: 11, fill: "#7b8792" }} width={46} />
          <Tooltip labelFormatter={(t) => fmtDT(String(t) + ":00")} formatter={(v: number, k: string) => [n(v, 0) + " kW", k === "actual" ? "Actual" : "Expected"]} />
          <ReferenceArea x1={x0} x2={x1} fill="#e3a23b" fillOpacity={0.14} />
          <Line dataKey="baseline" stroke="#2b6c8f" strokeDasharray="4 3" dot={false} strokeWidth={1.6} isAnimationActive={false} />
          <Line dataKey="actual" stroke="#17212a" dot={false} strokeWidth={1.6} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
      {big.length > 0 && <SignalChart rows={rows} sigs={big} x0={x0} x1={x1} />}
      {small.map((s) => <SignalChart key={s} rows={rows} sigs={[s]} x0={x0} x1={x1} height={96} />)}
    </div>
  );
}

const RATIO = new Set(["kw_per_tr", "pf", "n_chillers", "chw_setpoint_c"]);
const STEP = new Set(["n_chillers", "chw_setpoint_c", "ev_guests"]);

function SignalChart({ rows, sigs, x0, x1, height = 150 }: { rows: Record<string, number | string | null>[]; sigs: string[]; x0: string; x1: string; height?: number }) {
  const twoAxes = sigs.length > 1;
  return (
    <>
      <div className="legend" style={{ margin: "8px 0 4px" }}>
        {sigs.map((s, i) => <span key={s}><i style={{ background: SIG_COLORS[i % 3] }} />{SIGNAL_LABEL[s] ?? s}{twoAxes ? (i === 0 ? " (left)" : " (right)") : ""}</span>)}
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
          <CartesianGrid stroke="#e8ecee" vertical={false} />
          <XAxis dataKey="t" tickFormatter={tick} minTickGap={50} tick={{ fontSize: 11, fill: "#7b8792" }} />
          <YAxis yAxisId="a" tick={{ fontSize: 11, fill: "#7b8792" }} width={46} domain={["auto", "auto"]} />
          {twoAxes && <YAxis yAxisId="b" orientation="right" tick={{ fontSize: 11, fill: "#7b8792" }} width={40} />}
          <Tooltip labelFormatter={(t) => fmtDT(String(t) + ":00")} formatter={(v: number, k: string) => [n(v, RATIO.has(k) ? 2 : 0), SIGNAL_LABEL[k] ?? k]} />
          <ReferenceArea yAxisId="a" x1={x0} x2={x1} fill="#e3a23b" fillOpacity={0.14} />
          {sigs.map((s, i) => (
            <Line key={s} yAxisId={i === 0 ? "a" : "b"} dataKey={s} stroke={SIG_COLORS[i % 3]} dot={false} strokeWidth={1.6}
                  type={STEP.has(s) ? "stepAfter" : "linear"} isAnimationActive={false} connectNulls />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </>
  );
}

export interface Ack { id: string; response: string; reason: string; at: string }

/** One alert as the team sees it: what is wrong, why it matters, what to do, what it costs. Readings one tap away. */
export function Ticket({ a, now, onAck, acked, defaultOpen = false }: { a: Alert; now?: string; onAck?: (x: Ack) => void; acked?: Ack; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const [reason, setReason] = useState("");
  const [warn, setWarn] = useState("");
  useEffect(() => setOpen(defaultOpen), [a.id, defaultOpen]);
  const c = RULE[a.rule] ?? { title: a.title, why: a.cause, todo: a.action };
  const live = now && now < a.end && now >= a.start;
  const ranH = live ? (parse(now!).getTime() - parse(a.start).getTime()) / 3.6e6 : a.duration_h;
  const costSoFar = a.cost_basis === "per_day" ? a.per_hour * Math.min(ranH, a.flagged_h) : a.cost;
  const money = a.cost <= 0 ? <><b>Small</b><span>cost not significant</span></>
    : a.cost_basis === "per_day" ? <><b>{inr(a.per_day)}</b><span>a day while it continues</span></>
    : <><b>{inr(a.cost)}</b><span>this time</span></>;
  function respond(kind: string) {
    if (kind !== "Done / on it" && !reason.trim()) { setWarn("Add a short note to snooze or dismiss."); return; }
    setWarn("");
    onAck?.({ id: a.id, response: kind, reason, at: new Date().toISOString().slice(0, 16).replace("T", " ") });
  }
  return (
    <article className={`ticket p-${a.severity} ${open ? "open" : ""}`}>
      <TagPlate rule={a.rule} severity={a.severity} site={a.site} />
      <div>
        <div className="title">{c.title}</div>
        <div className="meta">
          {a.hotel} · started {fmtDT(a.start)} · {live ? `going on for ${hours(ranH)}` : `lasted ${hours(a.duration_h)}`}
          {a.repeat_30d > 0 && <> · <strong style={{ color: "var(--red)" }}>{a.repeat_30d + 1}{a.repeat_30d === 1 ? "nd" : a.repeat_30d === 2 ? "rd" : "th"} time this month</strong></>}
        </div>
        <div className="why">{c.why}</div>
        <div className="todo"><strong>What to do:</strong> {c.todo}</div>
        {a.repeat_30d >= 2 && <div className="small" style={{ marginTop: 6, color: "var(--red)" }}>Keeps coming back: worth a permanent fix with the chief engineer.</div>}
        {acked && <div className="small" style={{ marginTop: 6, color: "var(--green)" }}>{acked.response}{acked.reason ? `: ${acked.reason}` : ""} ({acked.at})</div>}
      </div>
      <div className="money">
        {money}
        <div><button className="btn ghost" style={{ marginTop: 8, padding: "5px 10px", fontSize: 13 }} onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? "Hide details" : "See the evidence"}</button></div>
      </div>
      {open && (
        <div className="more">
          <dl className="facts">
            <dt>Cost so far</dt><dd>{a.cost > 0 ? (a.cost_basis === "per_day" ? <>{inr(live ? costSoFar : a.cost)} ({inr(a.per_hour)} an hour)</> : inr(a.cost)) : "Not significant"}</dd>
            <dt>Spotted</dt><dd>{fmtDT(a.alert_time)}, about {n(Math.max(1, a.detect_lag_h))} hour{Math.round(a.detect_lag_h) > 1 ? "s" : ""} after it started</dd>
            <dt>Equipment</dt><dd>{EQUIPMENT[a.equipment] ?? a.equipment}</dd>
          </dl>
          <Evidence a={a} upto={live ? now : undefined} />
          <details className="more-info"><summary>Meter readings for the engineer</summary><p className="tech">{a.evidence}.{a.inferred_note ? ` ${a.inferred_note}` : ""}</p></details>
          <div className="guard"><span aria-hidden>🛡</span><span>{SAFETY[a.guardrail] ?? a.guard_text}</span></div>
          {onAck && (
            <div>
              <div className="btn-row" style={{ alignItems: "center" }}>
                <button className="btn big" onClick={() => respond("Done / on it")}>On it</button>
                <button className="btn ghost big" onClick={() => respond("Snoozed 2 hours")}>Snooze 2 hours</button>
                <button className="btn ghost big" onClick={() => respond("Not a problem")}>Not a problem</button>
                <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Note (needed to snooze or dismiss)"
                       style={{ flex: "1 1 220px", padding: "10px 12px", border: "1px solid var(--rule)", borderRadius: 6 }} />
              </div>
              {warn && <div className="small" style={{ color: "var(--red)", marginTop: 6 }}>{warn}</div>}
            </div>
          )}
        </div>
      )}
    </article>
  );
}

/** Waterfall: from one value to another through signed drivers. */
export function Waterfall({ start, end, startLabel, endLabel, steps, height = 300 }:
  { start: number; end: number; startLabel: string; endLabel: string; steps: { label: string; value: number }[]; height?: number }) {
  let run = start;
  const rows = [{ label: startLabel, base: 0, value: start, kind: "total" }];
  for (const s of steps) {
    const lo = Math.min(run, run + s.value);
    rows.push({ label: s.label, base: lo, value: Math.abs(s.value), kind: s.value >= 0 ? "up" : "down" });
    run += s.value;
  }
  rows.push({ label: endLabel, base: 0, value: end, kind: "total" });
  const lo = Math.min(start, end, ...rows.map((r) => r.base).filter((b) => b > 0)) * 0.93;
  const hi = Math.max(start, end, ...rows.map((r) => r.base + r.value)) * 1.02;
  const signed = (r: typeof rows[number]) => r.kind === "down" ? -r.value : r.value;
  return (
    <ResponsiveContainer width="100%" height={height + 30}>
      <ComposedChart data={rows} margin={{ top: 22, right: 8, bottom: 4, left: 8 }}>
        <CartesianGrid stroke="#e8ecee" vertical={false} />
        <XAxis dataKey="label" interval={0} angle={-35} textAnchor="end" tick={{ fontSize: 11.5, fill: "#4a5763" }} height={78} />
        <YAxis domain={[lo, hi]} tickFormatter={(v) => inr(v)} tick={{ fontSize: 11, fill: "#7b8792" }} width={70} allowDataOverflow />
        <Tooltip formatter={(_v: number, _k: string, p: any) => [p.payload.kind === "total" ? inr(p.payload.value, { exact: true }) : (signed(p.payload) >= 0 ? "+" : "") + inr(signed(p.payload), { exact: true }), ""]} />
        <Bar dataKey="base" stackId="w" fill="transparent" isAnimationActive={false} />
        <Bar dataKey="value" stackId="w" isAnimationActive={false} radius={[2, 2, 0, 0]}>
          {rows.map((r, i) => <Cell key={i} fill={r.kind === "total" ? "#22323d" : r.kind === "up" ? "#c4351f" : "#2f7a57"} />)}
          <LabelList dataKey="value" position="top" formatter={() => ""} content={(p: any) => {
            const r = rows[p.index ?? 0];
            const txt = r.kind === "total" ? inr(r.value) : (r.kind === "up" ? "+" : "−") + inr(r.value);
            if (r.kind !== "total" && rows.length > 8 && r.value < (hi - lo) * 0.02) return null;   // tiny steps: tooltip only, avoids label pile-ups
            return <text x={(p.x ?? 0) + (p.width ?? 0) / 2} y={(p.y ?? 0) - 6} textAnchor="middle" fontSize={11} fill="#4a5763">{txt}</text>;
          }} />
        </Bar>
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function KVA({ hoursArr, pred, actual, cd = 1000, stack }: { hoursArr: number[]; pred: number[]; actual?: number[]; cd?: number; stack?: number }) {
  const rows = hoursArr.map((h, i) => ({ h, pred: pred[i], actual: actual?.[i] ?? null }));
  return (
    <>
      <div className="legend" style={{ marginBottom: 4 }}>
        <span><i style={{ background: "#e3a23b" }} />Forecast power demand (kVA)</span>
        {actual && <span><i style={{ background: "#17212a" }} />What actually happened</span>}
        <span><i style={{ background: "#c4351f" }} />Contracted limit {n(cd)} kVA</span>
        <span><i style={{ background: "#c27a12" }} />Early-warning level 920 kVA</span>
      </div>
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={rows} margin={{ top: 8, right: 10, bottom: 0, left: -6 }}>
          <CartesianGrid stroke="#e8ecee" vertical={false} />
          <XAxis dataKey="h" tickFormatter={(h) => `${h}:00`} tick={{ fontSize: 11, fill: "#7b8792" }} />
          <YAxis domain={[300, Math.max(1100, (stack ?? 0) + 40)]} tick={{ fontSize: 11, fill: "#7b8792" }} width={48} />
          <Tooltip labelFormatter={(h) => `${h}:00`} formatter={(v: number, k: string) => [n(v) + " kVA", k === "pred" ? "Forecast" : "Actual"]} />
          <ReferenceLine y={cd} stroke="#c4351f" strokeDasharray="5 3" />
          <ReferenceLine y={920} stroke="#c27a12" strokeDasharray="2 3" />
          <Line dataKey="pred" stroke="#e3a23b" strokeWidth={2.4} dot={false} isAnimationActive={false} />
          {actual && <Line dataKey="actual" stroke="#17212a" strokeWidth={1.4} dot={false} isAnimationActive={false} />}
        </ComposedChart>
      </ResponsiveContainer>
    </>
  );
}
