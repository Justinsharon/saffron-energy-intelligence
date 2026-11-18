// Saffron meter simulator ("Plant Room"): a SIMULATED stand-in for the Gurugram electrical meters and BMS points that feed the Saffron
// software, because the real plant can't be run live in a demo. It shows only meter channels and the meter rows sent on. It has no controls:
// the readings change when the chief engineer approves tomorrow's plan and the duty engineer marks a step Done in the Saffron app
// (the plans log), and when a demo fault is injected. Every curve is our forecast / plan for the day (model.ts); only the reading is simulated.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiPlan, RETRY_TIMEOUT_MS } from "../planApi";
import { planFor, type Booking, type PlanDay } from "../plan";
import { istStamp, type SavedAction } from "../planlog";
import { CHECK_WINDOW_H, FAULTS, checkWindow, covers, equipOf, hourOf, hourRow, snapshot, soFar,
  type FaultType, type Forecast, type PlantIndex, type PlantProfile, type SimDay, type SimState, type Snapshot } from "./model";
import { applyPlantEvent, activeFaults, hhmm, unsynced, type PlantView } from "./store";
import { getPlant, getPlants, istToday, postPlant, resetDemo } from "./client";

const PRESENTER = "Demo presenter";            // who injects / clears demo faults (the fault panel is the only control here)
const SPEEDS = [5, 10, 30];
const READINGS_EVERY_MS = 12000;               // shared storage is a gist: at most one readings write every 12 s (events carry readings too)
const POLL_MS = 5000;                          // the plans log is read every 5 s, so a Done in the app reaches the meters within one poll
const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"], MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const addDay = (d: string, k: number) => { const x = new Date(`${d}T00:00:00Z`); x.setUTCDate(x.getUTCDate() + k); return x.toISOString().slice(0, 10); };
const dayLabel = (d: string) => { const x = new Date(`${d}T00:00:00Z`); return `${DOW[x.getUTCDay()]} ${x.getUTCDate()} ${MON[x.getUTCMonth()]}`; };
const n0 = (x: number) => Math.round(x).toLocaleString("en-IN");
const n1 = (x: number) => x.toFixed(1);

// the channels the Saffron software reads for Gurugram (sub_ggn_hourly + the main incoming meter); eq = the equipment a plan step moves
type Chan = { id: string; point: string; unit: string; eq?: string; get: (s: Snapshot) => number; fmt?: (x: number) => string; monitored?: boolean; oos?: boolean };
const CHANNELS: Chan[] = [
  { id: "chiller_ch1_kw", point: "Chiller 1 (CH-1, 300 TR screw) · sub-meter", unit: "kW", eq: "CH-1", get: (s) => s.equip["CH-1"].kw },
  { id: "chiller_ch3_kw", point: "Chiller 3 (CH-3, 150 TR scroll) · sub-meter", unit: "kW", eq: "CH-3", get: (s) => s.equip["CH-3"].kw },
  { id: "chiller_ch2_kw", point: "Chiller 2 (CH-2) · sub-meter · out of service", unit: "kW", get: () => 0, oos: true },
  { id: "chiller_load_tr", point: "Chilled-water plant · cooling load (BMS)", unit: "TR", get: (s) => s.tr },
  { id: "chw_setpoint_c", point: "CHW supply setpoint (BMS point)", unit: "°C", eq: "CHW", get: (s) => s.setpoint, fmt: n1 },
  { id: "chw_supply_temp_c", point: "CHW supply temperature (BMS)", unit: "°C", eq: "CHW", get: (s) => s.supply_c, fmt: n1 },
  { id: "ahu_banquet_kw · A", point: "Banquet AHU-1 (AHU-BQ-A, Hall A) · sub-meter", unit: "kW", eq: "AHU-BQ-A", get: (s) => s.equip["AHU-BQ-A"].kw },
  { id: "ahu_banquet_kw · B", point: "Banquet AHU-2 (AHU-BQ-B, Hall B) · sub-meter", unit: "kW", eq: "AHU-BQ-B", get: (s) => s.equip["AHU-BQ-B"].kw },
  { id: "laundry_kw", point: "Laundry · sub-meter", unit: "kW", eq: "LAUNDRY", get: (s) => s.equip.LAUNDRY.kw },
  { id: "water_heating_kw", point: "Heat-pump water heaters (HP-DHW) · sub-meter", unit: "kW", eq: "HP-DHW", get: (s) => s.equip["HP-DHW"].kw },
  { id: "ev_chargers_kw", point: "EV chargers (EVC-1..4) · sub-meter", unit: "kW", eq: "EVC", get: (s) => s.equip.EVC.kw },
  { id: "kitchen_exhaust_mua_kw", point: "Kitchen exhaust + make-up air · monitored only", unit: "kW", get: (s) => s.monitored.KEF, monitored: true },
  { id: "rooms_fcu_plug_kw", point: "Guest rooms (FCU + plug) · monitored only", unit: "kW", get: (s) => s.monitored.ROOMS, monitored: true },
  { id: "lifts_kw", point: "Lifts · monitored only", unit: "kW", get: (s) => s.monitored.LIFTS, monitored: true },
];

interface Loaded { day: SimDay; source: string }

function useSimDay(view: PlantView | null, date: string): { loaded: Loaded | null; err: string } {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [err, setErr] = useState("");
  const inputs = (view?.plan?.inputs ?? null) as { rooms?: number; guests?: number; covers?: number; bookings?: Booking[]; temps_source?: string;
    weather_mode?: string; scenario_date?: string } | null;
  const key = view ? JSON.stringify([date, view.plan?.version ?? 0, inputs]) : "";
  const stepsSig = (view?.plan?.steps ?? []).map((s) => s.id + s.start + s.end).join(";");
  useEffect(() => {
    if (!view) return;
    let on = true;
    setErr("");
    (async () => {
      try {
        const [pd, prof, idx] = await Promise.all([`/data/plan/${date}.json`, `/data/plant/${date}.json`, "/data/plant/index.json"].map((u) => fetch(u).then((r) => {
          if (!r.ok) throw new Error(`${u} not found: the simulator covers the live year (2 Oct 2026 – 29 Sep 2027).`); return r.json(); })));
        const planDay = pd as PlanDay;
        // the SAME request as Tomorrow's plan: the saved inputs; typical temperatures when the plan was saved with them
        const typical = (inputs?.temps_source ?? "").startsWith("typical");
        // a scenario plan (hot-day what-if) runs on the same real hot-day curve the plan page used
        const scen = inputs?.weather_mode === "scenario-40C" ? (await fetch("/data/plan/scenario_hot.json").then((r) => r.json())) as { temps: number[]; label: string } : null;
        const temps = scen ? scen.temps : typical ? planDay.base.temp : null;
        const req = { date, site: "GGN" as const, rooms: inputs?.rooms, guests: inputs?.guests, covers: inputs?.covers, bookings: inputs?.bookings ?? [],
                      ...(temps ? { temps } : {}) };
        let fc: Forecast, bookings: Booking[], source: string;
        try {
          const r = await apiPlan(req, "/api", RETRY_TIMEOUT_MS);
          fc = r.forecast; bookings = r.bookings; source = `plan API forecast for the saved inputs (weather: ${scen ? `SCENARIO, ${scen.label}` : r.weather})`;
        } catch {
          const r = planFor(planDay, { rooms: req.rooms, guests: req.guests, covers: req.covers, bookings: req.bookings, temps });
          fc = r.forecast; bookings = req.bookings; source = "offline estimate in the browser (the plan API did not answer)";
        }
        if (on) setLoaded({ day: { date, forecast: fc, steps: (view.plan?.steps ?? []) as SavedAction[], bookings, profile: prof as PlantProfile,
          index: idx as PlantIndex, ref: planDay.ref, tariff: planDay.tariff, pf: planDay.pf }, source });
      } catch (e) { if (on) setErr(String((e as Error).message ?? e)); }
    })();
    return () => { on = false; };
  }, [key, stepsSig]);
  return { loaded, err };
}

/** Today if it has approved steps, else tomorrow if it does, else today (?date= overrides). */
function useDate(): [string | null, (d: string) => void] {
  const [date, setDate] = useState<string | null>(null);
  useEffect(() => {
    const q = new URLSearchParams(location.search).get("date");
    if (q && /^\d{4}-\d{2}-\d{2}$/.test(q)) { setDate(q); return; }
    const today = istToday(), tomorrow = addDay(today, 1);
    getPlants([today, tomorrow]).then(([a, b]) => setDate(a?.plan?.steps.length ? today : b?.plan?.steps.length ? tomorrow : today)).catch(() => setDate(today));
  }, []);
  return [date, setDate];
}

export default function PlantApp() {
  const [date, setDate] = useDate();
  return date ? <Sim key={date} date={date} setDate={setDate} /> : <Shell date={istToday()} t={6}><div className="pr-panel">Finding the day with an approved plan…</div></Shell>;
}

function Sim({ date, setDate }: { date: string; setDate: (d: string) => void }) {
  const [view, setView] = useState<PlantView | null>(null);
  const [t, setT] = useState(6);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(10);
  const [msg, setMsg] = useState<{ kind: "err" | "ok"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const { loaded, err } = useSimDay(view, date);
  const day = loaded?.day ?? null;
  const st: SimState = useMemo(() => ({ applied: view?.applied ?? {}, faults: view?.faults ?? [] }), [view]);
  const tc = Math.min(t, 23.999);
  const tRef = useRef(t); tRef.current = t;
  const viewRef = useRef(view); viewRef.current = view;

  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => setT((x) => { const y = Math.min(24, x + 0.2 / speed); if (y >= 24) setPlaying(false); return y; }), 200);
    return () => clearInterval(id);
  }, [playing, speed]);

  const readingsFor = useCallback((s: SimState, lastFix: number | null, at: number) => {
    if (!day) return undefined;
    const now = Math.min(at, 23.999);
    const snap = snapshot(day, s, now);
    const values: Record<string, number | string> = { setpoint_c: snap.setpoint, tr: Math.round(snap.tr) };
    for (const [k, v] of Object.entries(snap.equip)) values[k] = Math.round(v.kw * 10) / 10;
    return { simHour: now, kva: Math.round(snap.kva), kw: Math.round(snap.kw), values, lastFix, recent: checkWindow(now, lastFix).map((h) => hourRow(day, s, h, now)) };
  }, [day]);

  // one write: the event (or just readings) with the readings as they will be after it, so the app sees the change at once
  const post = useCallback(async (body: Record<string, unknown>, ok?: string) => {
    const v = viewRef.current;
    if (!v) return;
    const full = { ...body, date, simHour: Math.round(Math.min(tRef.current, 23.999) * 100) / 100 };
    const local = applyPlantEvent(v, full, istStamp(), (v.plan?.steps ?? []) as SavedAction[], v.plan?.duty);
    const readings = local.error ? undefined : readingsFor({ applied: local.entry.applied, faults: local.entry.faults }, local.entry.lastFix, tRef.current);
    const r = await postPlant({ ...full, readings });
    lastPost.current = Date.now();
    setView(r.view);
    if (r.error) setMsg({ kind: "err", text: r.error }); else if (ok) setMsg({ kind: "ok", text: ok });
  }, [date, readingsFor]);

  // the plans log: approvals change the plan; Done / Can't do from the duty engineer move the meters (taken in with the current sim time)
  useEffect(() => {
    let on = true, timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      const v = await getPlant(date).catch(() => null);
      if (on && v) {
        setView((cur) => (cur && cur.updated > v.updated ? cur : v));
        // a Done / Can't do to take in, or a fault fixed from the app ("Fixed on site"): post fresh readings at once
        const stale = !!v.readings && (v.readings.lastFix ?? null) !== (v.lastFix ?? null);
        if (day && v.plan && (unsynced(v, v.plan.duty, v.plan.steps as SavedAction[]).length || stale)) { viewRef.current = v; await post({ event: "sync" }).catch(() => {}); }
      }
      if (on) timer = setTimeout(tick, POLL_MS);
    };
    tick();
    return () => { on = false; clearTimeout(timer); };
  }, [date, day, post]);

  // readings: every sim hour, at most one write every 12 s (trailing)
  const lastPost = useRef(0), pending = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hourNow = Math.floor(tc);
  useEffect(() => {
    if (!day || !view?.plan) return;
    const send = () => { pending.current = null; post({ event: "readings" }).catch(() => {}); };
    const wait = READINGS_EVERY_MS - (Date.now() - lastPost.current);
    if (wait <= 0) send();
    else if (!pending.current) pending.current = setTimeout(send, wait);
  }, [hourNow, day, view?.plan?.version]);

  async function act(body: Record<string, unknown>, ok: string) {
    setBusy(true); setMsg(null);
    try { await post({ ...body, by: PRESENTER }, ok); } catch (e) { setMsg({ kind: "err", text: String((e as Error).message ?? e) }); }
    finally { setBusy(false); }
  }

  const today = istToday();
  const dates: [string, string][] = [[today, "Today"], [addDay(today, 1), "Tomorrow"]];
  if (err) return <Shell date={date} t={tc}><div className="pr-panel pr-err">{err}</div></Shell>;
  if (!view || !day) return <Shell date={date} t={tc}><div className="pr-panel">Loading the plan and the forecast for {dayLabel(date)}…</div></Shell>;

  const snap = snapshot(day, st, tc);
  const h = Math.floor(tc);
  const faults = activeFaults(view);
  const ahuStep = day.steps.find((s) => s.group === "ahu");
  const conf = day.bookings.find((b) => Number(b.start.slice(0, 2)) <= 13 && (b.end === "23:59" || Number(b.end.slice(0, 2)) > 13));
  const after = ahuStep ? Math.min(23, hourOf(ahuStep.end) + 1) : 19;
  const quick: [string, number][] = [["06:00", 6], [conf ? "13:00 conference" : "13:00", 13], [`${String(after).padStart(2, "0")}:00 after event`, after]];
  const duty = view.plan?.duty ?? {};
  const done = day.steps.filter((a) => duty[a.id]?.event === "done" && view.applied[a.id]).length;      // marked Done AND taken in by the meters
  const kwh = soFar(day, st, tc).kwh;
  const pct = snap.kva / 1000;
  // what moves each channel right now: the plan step done in the app, a demo fault, or habit
  const sourceOf = (c: Chan): { cls: string; text: string } => {
    if (c.oos) return { cls: "oos", text: "out of service (register)" };
    if (c.monitored) return { cls: "mon", text: "metered; never controlled" };
    if (!c.eq) return { cls: "", text: "from the forecast" };
    const f = c.eq === "CHW" ? snap.equip.CHW.following : (snap.equip as Record<string, { following: string }>)[c.eq]?.following;
    if (f === "fault") return { cls: "fault", text: "FAULT (demo)" };
    const step = day.steps.find((a) => equipOf(a).includes(c.eq as never) && covers(a, h));
    const ap = step && view.applied[step.id];
    if (f === "plan" && ap) return { cls: "plan", text: `plan: ${step!.setting.split(" (")[0]} · done by ${ap.by} ${ap.at.slice(11)}` };
    if (step && duty[step.id]?.event === "cant") return { cls: "", text: `habit: can't do (${duty[step.id].reason})` };
    if (step && view.applied[step.id] && view.applied[step.id].simHour > tc) return { cls: "", text: `habit until sim ${hhmm(view.applied[step.id].simHour)}` };
    return { cls: "", text: step ? "habit: approved, not done yet" : "habit" };
  };
  const scenario = (view.plan?.inputs as { weather_mode?: string } | undefined)?.weather_mode === "scenario-40C";
  return (
    <Shell date={date} t={tc} scenario={scenario}>
      {scenario && <div className="pr-msg warn-banner">SCENARIO: hot-day weather (40 °C) from a real May 2026 day, not the real forecast for {dayLabel(date)}. A what-if: never in savings or bills.</div>}
      <section className="pr-top">
        <div className="pr-panel pr-clock">
          <div className="pr-lbl">Sim clock</div>
          <div className="pr-row" style={{ marginTop: 0 }}>{dates.map(([d, l]) => <button key={d} className={`pr-btn ${d === date ? "" : "ghost"}`} onClick={() => setDate(d)}>{l}</button>)}</div>
          <div className="pr-time num">{hhmm(tc)}</div>
          <div className="pr-row">
            <button className="pr-btn" onClick={() => setPlaying(!playing)} aria-pressed={playing}>{playing ? "❚❚ Pause" : "▶ Play"}</button>
            <label className="pr-small">1 h =
              <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>{SPEEDS.map((s) => <option key={s} value={s}>{s} s</option>)}</select>
            </label>
          </div>
          <input className="pr-slider" type="range" min={0} max={23.9} step={0.25} value={tc} aria-label="Sim hour" onChange={(e) => setT(Number(e.target.value))} />
          <div className="pr-row wrap">{quick.map(([l, x]) => <button key={l} className="pr-btn ghost" onClick={() => setT(x)}>{l}</button>)}</div>
        </div>
        <div className="pr-panel pr-meter">
          <div className="pr-lbl">Main incoming meter (EM-01) · contract demand 1,000 kVA</div>
          <Gauge pct={pct} kva={snap.kva} />
          <table className="pr-tab num"><tbody>
            <tr><td>Active power</td><td>{n0(snap.kw)} kW</td><td>Power factor</td><td>{(snap.kw / snap.kva).toFixed(3)}</td></tr>
            <tr><td>Energy today (register)</td><td>{n0(kwh)} kWh</td><td>Cooling load</td><td>{n0(snap.tr)} TR</td></tr>
          </tbody></table>
        </div>
        <div className="pr-panel pr-sofar">
          <div className="pr-lbl">What drives these readings</div>
          <p className="pr-small" style={{ margin: "0 0 6px" }}>{view.plan ? <>Plan v{view.plan.version} for {dayLabel(date)}: <b>{day.steps.length}</b> approved steps, <b data-testid="done-count">{done}</b> marked Done in the Saffron app.</>
            : <>No saved plan for {dayLabel(date)}: every channel follows habit.</>}</p>
          <p className="pr-small muted" style={{ margin: 0 }}>A channel follows habit (last year's matched days) until its approved step is marked Done in the app; then it follows the plan. Nothing here is controlled.</p>
          <p className="pr-small muted" style={{ margin: "6px 0 0" }}>Curves: {loaded?.source}. Reading = curve × (1 ± up to 2.5 %).</p>
        </div>
      </section>

      {msg && <div className={`pr-msg ${msg.kind}`} role={msg.kind === "err" ? "alert" : "status"}>{msg.text}</div>}

      <section className="pr-panel">
        <div className="pr-lbl">Meter channels · live · sim {hhmm(tc)}</div>
        <div className="pr-meters" data-testid="channels">
          {CHANNELS.map((c) => { const s = sourceOf(c); return (
            <div key={c.id} className={`pr-mtile ${c.monitored ? "mon" : c.oos ? "oos" : ""} src-${s.cls || "habit"}`}
                 data-testid={`chan-${c.id.split(" ")[0]}${c.id.endsWith("B") ? "-B" : c.id.endsWith("A") ? "-A" : ""}`}>
              <div className="pr-mname">{c.point.split(" · ")[0]}</div>
              <div className="pr-cid">{c.id}</div>
              <div className="pr-mval num">{(c.fmt ?? n0)(c.get(snap))}<span>{c.unit}</span></div>
              <Spark day={day} st={st} t={tc} get={c.get} />
              <div className={`pr-src ${s.cls}`}>{s.text}</div>
            </div>); })}
        </div>
      </section>

      <section className="pr-split">
        <div className="pr-panel">
          <div className="pr-lbl">Meter rows sent to Saffron · last {CHECK_WINDOW_H} sim hours{view.readings ? ` · posted ${view.readings.at.slice(11)}` : ""}</div>
          <MeterRows rows={view.readings?.recent ?? []} />
          <p className="pr-small muted" style={{ marginBottom: 0 }}>Posted every sim hour and at once on a fault. The Saffron app checks these rows against the approved plan with the plan API's /check (in the browser if the API is unavailable). Never used for savings or bills.</p>
        </div>
        <FaultPanel faults={faults.map((f) => f.type)} busy={busy} hasAhu={!!ahuStep} t={tc} ahuOff={ahuStep ? ahuStep.end.replace(" (next day)", "") : null}
                    onFault={(type) => act({ event: "fault", type }, `${FAULTS[type].label}: injected at sim ${hhmm(tc)}.`)}
                    onClear={() => act({ event: "clearFault" }, "Fault cleared.")}
                    onReset={() => act({ event: "reset", reason: "rehearsal reset" }, "Simulation reset.")}
                    onDemoReset={async () => {
                      setBusy(true); setMsg(null);
                      try { const r = await resetDemo(date, Math.round(tc * 100) / 100); if (r.view) setView(r.view); setMsg({ kind: "ok", text: r.lines.join(" ") }); }
                      catch (e) { setMsg({ kind: "err", text: `Reset demo failed: ${String((e as Error).message ?? e)}` }); }
                      finally { setBusy(false); }
                    }} />
      </section>

      <section className="pr-panel pr-audit">
        <div className="pr-lbl">Audit log · latest 10 · storage: {view.storage === "gist" ? "shared (gist)" : view.storage === "device" ? "this device only" : view.storage}</div>
        <table className="num"><tbody>
          {view.audit.filter((r) => !r.superseded).slice(-10).reverse().map((r, i) => (
            <tr key={i} style={r.superseded ? { opacity: 0.45 } : undefined} className={r.event.includes("fault injected") ? "warn" : r.event.includes("fixed") || r.event.includes("cleared") || r.event.includes("done") ? "okr" : ""}>
              <td>{r.at.slice(11)}</td><td>sim {r.simHour !== undefined ? hhmm(r.simHour) : "—"}</td><td>{r.by}</td><td><b>{r.event}</b></td><td>{r.what}{r.why ? ` — ${r.why}` : ""}</td>
            </tr>
          ))}
          {!view.audit.length && <tr><td colSpan={5} className="muted">Nothing yet. Steps marked Done in the app, faults and resets appear here with who, when and why.</td></tr>}
        </tbody></table>
      </section>
    </Shell>
  );
}

function Shell({ date, t, scenario, children }: { date: string; t: number; scenario?: boolean; children: React.ReactNode }) {
  return (
    <div className="pr-shell">
      <header className="pr-head">
        <div className="pr-sim" data-testid="sim-banner"><span className="pr-dot" />SIMULATION · Gurugram · Sim time {dayLabel(date)} {hhmm(t)}</div>
        {scenario && <div className="pr-sim pr-scen" data-testid="scenario-pill">SIMULATION · SCENARIO 40 °C</div>}
        <div className="pr-brand">Saffron meter simulator <small>stands in for the hotel's meters and BMS points · not live data</small></div>
      </header>
      {children}
    </div>
  );
}

function Gauge({ pct, kva }: { pct: number; kva: number }) {
  const p = Math.max(0, Math.min(1.2, pct));
  const col = pct > 1 ? "var(--pr-red)" : pct >= 0.85 ? "var(--pr-amber)" : "var(--pr-green)";
  const a = Math.PI * (1 - p / 1.2), x = 100 + 80 * Math.cos(a), y = 100 - 80 * Math.sin(a);
  const lim = Math.PI * (1 - 1 / 1.2);
  return (
    <svg viewBox="0 0 200 118" className="pr-gauge" role="img" aria-label={`${Math.round(kva)} kVA, ${Math.round(pct * 100)} % of the 1,000 kVA contract`}>
      <path d="M20 100 A80 80 0 0 1 180 100" fill="none" stroke="var(--pr-line)" strokeWidth="14" strokeLinecap="round" />
      <path d={`M20 100 A80 80 0 0 1 ${x.toFixed(1)} ${y.toFixed(1)}`} fill="none" stroke={col} strokeWidth="14" strokeLinecap="round" />
      <line x1={100 + 66 * Math.cos(lim)} y1={100 - 66 * Math.sin(lim)} x2={100 + 88 * Math.cos(lim)} y2={100 - 88 * Math.sin(lim)} stroke="var(--pr-red)" strokeWidth="3" />
      <text x="100" y="86" textAnchor="middle" className="pr-gv" fill={col}>{Math.round(kva)}</text>
      <text x="100" y="106" textAnchor="middle" className="pr-gu">kVA · {Math.round(pct * 100)} % of contract</text>
    </svg>
  );
}

function Spark({ day, st, t, get }: { day: SimDay; st: SimState; t: number; get: (s: Snapshot) => number }) {
  const xs = useMemo(() => [...Array.from({ length: Math.floor(t) }, (_, h) => get(snapshot(day, st, h + 0.5))), get(snapshot(day, st, t))], [day, st, Math.floor(t), get]);
  if (xs.length < 2) return <svg className="pr-spark" viewBox="0 0 100 20" />;
  const hi = Math.max(...xs, 1), lo = Math.min(...xs, 0);
  const pts = xs.map((v, i) => `${((i / 23) * 100).toFixed(1)},${(18 - ((v - lo) / (hi - lo || 1)) * 16).toFixed(1)}`).join(" ");
  return <svg className="pr-spark" viewBox="0 0 100 20" preserveAspectRatio="none"><polyline points={pts} fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>;
}

const ROW_COLS: [keyof import("./model").MeterRow, string][] = [["chiller_ch1_kw", "CH-1"], ["chiller_ch3_kw", "CH-3"], ["chiller_load_tr", "TR"], ["chw_setpoint_c", "CHW °C"],
  ["ahu_banquet_kw", "AHU-BQ"], ["laundry_kw", "Laundry"], ["water_heating_kw", "DHW"], ["ev_chargers_kw", "EV"], ["kva", "kVA"], ["total_kwh", "kWh"]];
function MeterRows({ rows }: { rows: import("./model").MeterRow[] }) {
  if (!rows.length) return <p className="pr-small muted">No rows posted yet.</p>;
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="pr-rows num" data-testid="meter-rows"><thead><tr><th>timestamp</th>{ROW_COLS.map(([, l]) => <th key={l}>{l}</th>)}</tr></thead>
        <tbody>{rows.map((r) => <tr key={r.timestamp}><td>{r.timestamp.slice(11)}</td>{ROW_COLS.map(([k]) => <td key={k}>{k === "chw_setpoint_c" ? Number(r[k]).toFixed(1) : n0(Number(r[k]))}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

/** Two-step button: the first press arms it for 5 s ("Confirm reset"); no browser dialog. */
function ConfirmButton({ label, confirm, disabled, onConfirm }: { label: string; confirm: string; disabled: boolean; onConfirm: () => void }) {
  const [armed, setArmed] = useState(false);
  useEffect(() => { if (!armed) return; const id = setTimeout(() => setArmed(false), 5000); return () => clearTimeout(id); }, [armed]);
  return <button className={`pr-btn ${armed ? "warn on" : "ghost"}`} disabled={disabled} onClick={() => { if (armed) { setArmed(false); onConfirm(); } else setArmed(true); }}>{armed ? confirm : label}</button>;
}

function FaultPanel({ faults, busy, hasAhu, t, ahuOff, onFault, onClear, onReset, onDemoReset }: { faults: FaultType[]; busy: boolean; hasAhu: boolean; t: number; ahuOff: string | null;
  onFault: (f: FaultType) => void; onClear: () => void; onReset: () => void; onDemoReset: () => void }) {
  return (
    <div className="pr-panel pr-faults">
      <div className="pr-lbl">Simulate a fault (demo)</div>
      <div className="pr-row wrap">
        {(Object.keys(FAULTS) as FaultType[]).map((f, i) => {
          const off = f === "ahu_left_on" && !hasAhu;
          return <button key={f} className={`pr-btn warn ${faults.includes(f) ? "on" : ""}`} disabled={busy || off || faults.includes(f)} onClick={() => onFault(f)}
                         title={off ? "No banquet booking in the approved plan, so there is no AHU off time to miss." : FAULTS[f].what}>{i + 1}. {FAULTS[f].label}</button>;
        })}
      </div>
      <div className="pr-row wrap">
        <button className="pr-btn" disabled={busy || !faults.length} onClick={onClear}>Clear fault</button>
        <ConfirmButton label="Reset simulation" confirm="Confirm reset" disabled={busy} onConfirm={onReset} />
        <ConfirmButton label="Reset demo for this day" confirm="Confirm reset" disabled={busy} onConfirm={onDemoReset} />
      </div>
      <div className="pr-small muted" style={{ marginTop: 8 }}>
        {faults.length ? `Active: ${faults.map((f) => FAULTS[f].label).join(", ")}.` : "No fault active."}
        {hasAhu && ahuOff ? ` Fault 1: the AHU keeps running past its planned off time (${ahuOff}).` : ""} Fault 3 acts only inside 18:00–22:00{t < 18 ? " (from 18:00)" : ""}.
        "Reset demo for this day" withdraws a TEST plan (never one saved under a real name), sets aside a weather-scenario plan and clears the simulator; once per rehearsal is enough (each press writes to the shared storage). An alert needs 2 of the last {CHECK_WINDOW_H} sim hours to differ from the approved plan (the plan check's own rule). The duty engineer can mark it fixed on the alert in the app.
      </div>
    </div>
  );
}
