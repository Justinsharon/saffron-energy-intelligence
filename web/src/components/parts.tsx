import { useEffect, useState } from "react";
import { CartesianGrid, ComposedChart, Line, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis, Bar, Cell, ReferenceLine, LabelList } from "recharts";
import type { Alert } from "../data";
import { fmtDT, hours, inr, n, parse } from "../format";

/** Equipment tag plate: the label engraved on the plant item the alert is about. */
const TAG: Record<string, [string, string]> = {
  AHU_HAND_MODE: ["AHU-BQ", "Banquet AHUs"], HEAT_COOL_FIGHT: ["AHU-RH", "Re-heat banks"], KITCHEN_EXHAUST_OFF_HOURS: ["KEF", "Kitchen exhaust"],
  LIGHTING_LEFT_ON: ["LTG", "Event lighting"], LAUNDRY_IN_PEAK: ["LDY", "Laundry"], POOL_PUMP_OFF_SCHEDULE: ["PP", "Pool pumps"],
  POWER_FACTOR_DROP: ["APFC", "Capacitor panel"], CHILLER_STAGING_LOW_LOAD: ["CH-1/3", "Chiller plant"], STAGING_KWTR: ["CH-1/3", "Chiller plant"],
  CHILLER_PART_LOAD_INEFFICIENCY: ["CH-A/B", "Chillers"], CHW_SETPOINT_LOW: ["CHW-SP", "CHW setpoint"], DEMAND_NEAR_CONTRACT: ["MAIN", "Incomer kVA"],
  EV_CHARGER_NIGHT_ON: ["EVC", "EV chargers"], RESIDUAL_UNEXPLAINED: ["MAIN", "Site meter"],
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
  const cls = s === "High" ? "c-high" : s === "Medium" ? "c-med" : s === "Data quality" ? "c-dq" : "c-low";
  return <span className={`chip ${cls}`}>{s}</span>;
}
export function Status({ s }: { s: string }) {
  const cls = s === "Reconciled" ? "c-ok" : s === "Meter fault" ? "c-dq" : s === "Provisional" ? "c-high" : "c-med";
  return <span className={`chip ${cls}`}>{s}</span>;
}

const SIGNAL_LABEL: Record<string, string> = {
  ahu_banquet_kw: "Banquet AHU kW", ev_guests: "Event guests", ahu_heaters_kw: "Re-heat kW", temp_c: "Outdoor °C", kitchen_exhaust_kw: "Exhaust kW",
  lighting_kw: "Lighting kW", laundry_kw: "Laundry kW", pool_pump_kw: "Pool pump kW", pf: "Power factor", chillers_kw: "Chiller kW",
  chiller_load_tr: "Cooling load TR", n_chillers: "Chillers running (BMS)", kw_per_tr: "kW per TR", chw_setpoint_c: "CHW setpoint °C",
  kva_max_in_hour: "Peak kVA", ev_chargers_kw: "EV charger kW",
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
        <span><i style={{ background: "#17212a" }} />Site kW, actual</span>
        <span><i style={{ background: "#2b6c8f" }} />Expected for this weather, occupancy and events</span>
        <span><i style={{ background: "#e3a23b", height: 8, opacity: 0.4 }} />Alert window</span>
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

/** One alert as the duty engineer sees it: plate, what, since when, money, one action; tap to open evidence. */
export function Ticket({ a, now, onAck, acked, defaultOpen = false }: { a: Alert; now?: string; onAck?: (x: Ack) => void; acked?: Ack; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const [reason, setReason] = useState("");
  const [warn, setWarn] = useState("");
  useEffect(() => setOpen(defaultOpen), [a.id, defaultOpen]);
  const live = now && now < a.end && now >= a.start;
  const ranH = live ? (parse(now!).getTime() - parse(a.start).getTime()) / 3.6e6 : a.duration_h;
  const costSoFar = a.cost_basis === "per_day" ? a.per_hour * Math.min(ranH, a.flagged_h) : a.cost;
  const money = a.cost <= 0 ? <><b>—</b><span>₹ not material</span></>
    : a.cost_basis === "per_day" ? <><b>{inr(a.per_day)}</b><span>per day while it runs</span></>
    : <><b>{inr(a.cost)}</b><span>this occurrence</span></>;
  function respond(kind: string) {
    if (kind !== "Acknowledged" && !reason.trim()) { setWarn("Add a reason to snooze or dismiss."); return; }
    setWarn("");
    onAck?.({ id: a.id, response: kind, reason, at: new Date().toISOString().slice(0, 16).replace("T", " ") });
  }
  return (
    <article className={`ticket ${open ? "open" : ""}`}>
      <TagPlate rule={a.rule} severity={a.severity} site={a.site} />
      <div>
        <div className="title">{a.title}</div>
        <div className="meta">
          {a.hotel} · since {fmtDT(a.start)} · {live ? `running ${hours(ranH)}` : `${hours(a.duration_h)}`}
          {a.repeat_30d > 0 && <> · <strong style={{ color: "var(--red)" }}>{a.repeat_30d + 1}× in 30 days</strong></>}
          {a.post_hoc && <> · <em>post-hoc rule</em></>}
        </div>
        <div className="action"><strong>Do:</strong> {a.action}</div>
        {acked && <div className="small" style={{ marginTop: 6, color: "var(--green)" }}>{acked.response}{acked.reason ? ` — ${acked.reason}` : ""} ({acked.at})</div>}
      </div>
      <div className="money">
        {money}
        <div><button className="btn ghost" style={{ marginTop: 8, padding: "5px 10px", fontSize: 13 }} onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? "Hide evidence" : "Show evidence"}</button></div>
      </div>
      {open && (
        <div className="more">
          <dl className="facts">
            <dt>What we saw</dt><dd>{a.evidence}.{a.inferred_note && <> <em>{a.inferred_note}</em></>}</dd>
            <dt>Likely cause</dt><dd>{a.cause}</dd>
            <dt>Where</dt><dd>{a.equipment}</dd>
            <dt>Cost</dt><dd>{a.cost > 0 ? <>{a.cost_basis === "per_day" ? <>{inr(a.per_hour)}/h · {live ? `${inr(costSoFar)} so far` : `${inr(a.cost)} over ${n(a.flagged_h)} flagged hours`}</> : inr(a.cost)}{a.cost_note && <span className="muted"> ({a.cost_note})</span>}</> : "Not material"}</dd>
            <dt>Raised</dt><dd>{fmtDT(a.alert_time)}, {n(a.detect_lag_h, 1)} h after the signature started</dd>
          </dl>
          <Evidence a={a} upto={live ? now : undefined} />
          <div className="guard"><span aria-hidden>🛡</span><span>{a.guard_text}</span></div>
          {onAck && (
            <div>
              <div className="btn-row" style={{ alignItems: "center" }}>
                <button className="btn big" onClick={() => respond("Acknowledged")}>Acknowledge</button>
                <button className="btn ghost big" onClick={() => respond("Snoozed 2 h")}>Snooze 2 h</button>
                <button className="btn ghost big" onClick={() => respond("Not waste")}>Not waste</button>
                <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (needed to snooze or dismiss)"
                       style={{ flex: "1 1 220px", padding: "10px 12px", border: "1px solid var(--rule)", borderRadius: 4 }} />
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
        <span><i style={{ background: "#e3a23b" }} />Forecast kVA (made the day before)</span>
        {actual && <span><i style={{ background: "#17212a" }} />Actual kVA</span>}
        <span><i style={{ background: "#c4351f" }} />Contract demand {n(cd)}</span>
        <span><i style={{ background: "#c27a12" }} />EV-throttle 920</span>
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
