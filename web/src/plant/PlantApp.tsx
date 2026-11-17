// Saffron Plant Room: a SIMULATED building-management screen for Gurugram. It closes the demo loop: approved plan -> the duty engineer
// applies the presets here -> equipment and meters change -> a demo fault -> the real plan check raises an alert in the Saffron app ->
// the engineer applies the fix here. Every curve is our forecast / plan for the chosen day (model.ts); only the reading is simulated.
// Nothing is applied without a person's click; monitored-only systems have no controls; every action is in the audit log.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { apiPlan, RETRY_TIMEOUT_MS } from "../planApi";
import { planFor, type Booking, type PlanDay } from "../plan";
import { istStamp, type SavedAction } from "../planlog";
import { CHECK_WINDOW_H, CONTROLLED, FAULTS, MONITORED, checkWindow, equipOf, hourOf, hourRow, snapshot, soFar, chillersAt,
  type EquipId, type FaultType, type Forecast, type PlantIndex, type PlantProfile, type SimDay, type SimState } from "./model";
import { applyPlantEvent, activeFaults, hhmm, type PlantView } from "./store";
import { getPlant, istToday, postPlant } from "./client";

const USERS = ["Rahul (Duty engineer)", "Meera (Chief engineer)"];
const SPEEDS = [5, 10, 30];
const READINGS_EVERY_MS = 12000;             // shared storage is a gist: at most one readings write every 12 s (events carry readings too)
const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"], MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const addDay = (d: string, k: number) => { const x = new Date(`${d}T00:00:00Z`); x.setUTCDate(x.getUTCDate() + k); return x.toISOString().slice(0, 10); };
const dayLabel = (d: string) => { const x = new Date(`${d}T00:00:00Z`); return `${DOW[x.getUTCDay()]} ${x.getUTCDate()} ${MON[x.getUTCMonth()]}`; };
const inr = (x: number) => "₹" + Math.round(x).toLocaleString("en-IN");
const n0 = (x: number) => Math.round(x).toLocaleString("en-IN");
const t1 = (x: string) => x.replace(" (next day)", "⁺¹");

interface Loaded { day: SimDay; source: string; notes: string[] }

function useSimDay(view: PlantView | null, date: string): { loaded: Loaded | null; err: string } {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [err, setErr] = useState("");
  const inputs = (view?.plan?.inputs ?? null) as { rooms?: number; guests?: number; covers?: number; bookings?: Booking[]; temps_source?: string } | null;
  const key = view ? JSON.stringify([date, view.plan?.version ?? 0, inputs]) : "";
  const stepsSig = (view?.plan?.steps ?? []).map((s) => s.id).join(";");
  useEffect(() => {
    if (!view) return;
    let on = true;
    (async () => {
      try {
        const [pd, prof, idx] = await Promise.all([`/data/plan/${date}.json`, `/data/plant/${date}.json`, "/data/plant/index.json"].map((u) => fetch(u).then((r) => {
          if (!r.ok) throw new Error(`${u} not found: the Plant Room covers the live year (2 Oct 2026 – 29 Sep 2027).`); return r.json(); })));
        const planDay = pd as PlanDay;
        // the SAME request as Tomorrow's plan page: the saved inputs (rooms, guests, covers, bookings) for the date and hotel
        // weather as the plan was saved: if it used the typical temperatures (the forecast service did not answer then), send those, so the
        // numbers match the plan the engineer approved; otherwise the API reads the same Open-Meteo forecast as Tomorrow's plan did
        const typical = (inputs?.temps_source ?? "").startsWith("typical");
        const req = { date, site: "GGN" as const, rooms: inputs?.rooms, guests: inputs?.guests, covers: inputs?.covers, bookings: inputs?.bookings ?? [],
                      ...(typical ? { temps: planDay.base.temp } : {}) };
        let fc: Forecast, bookings: Booking[], source: string, notes: string[] = [];
        try {
          const r = await apiPlan(req, "/api", RETRY_TIMEOUT_MS);
          fc = r.forecast; bookings = r.bookings; source = `plan API: the forecast for the saved inputs (weather: ${r.weather})`; notes = r.notes;
        } catch {
          const r = planFor(planDay, { rooms: req.rooms, guests: req.guests, covers: req.covers, bookings: req.bookings, temps: typical ? planDay.base.temp : null });
          fc = r.forecast; bookings = req.bookings; source = "offline estimate in the browser (the plan API did not answer)";
        }
        if (on) setLoaded({ day: { date, forecast: fc, steps: (view.plan?.steps ?? []) as SavedAction[], bookings, profile: prof as PlantProfile,
          index: idx as PlantIndex, ref: planDay.ref, tariff: planDay.tariff, pf: planDay.pf }, source, notes });
      } catch (e) { if (on) setErr(String((e as Error).message ?? e)); }
    })();
    return () => { on = false; };
  }, [key, stepsSig]);
  return { loaded, err };
}

export default function PlantApp() {
  const q = new URLSearchParams(location.search);
  const date = /^\d{4}-\d{2}-\d{2}$/.test(q.get("date") ?? "") ? q.get("date")! : addDay(istToday(), 1);
  const [view, setView] = useState<PlantView | null>(null);
  const [user, setUser] = useState(() => { try { return localStorage.getItem("plant_user") ?? USERS[0]; } catch { return USERS[0]; } });
  useEffect(() => { try { localStorage.setItem("plant_user", user); } catch { /* ignore */ } }, [user]);
  const [t, setT] = useState(6);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(10);
  const [sel, setSel] = useState<EquipId | null>(null);
  const [msg, setMsg] = useState<{ kind: "err" | "ok"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { getPlant(date).then(setView); }, [date]);
  const { loaded, err } = useSimDay(view, date);
  const day = loaded?.day ?? null;
  const st: SimState = useMemo(() => ({ applied: view?.applied ?? {}, faults: view?.faults ?? [] }), [view]);

  // sim clock
  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => setT((x) => { const y = Math.min(24, x + 0.2 / speed); if (y >= 24) setPlaying(false); return y; }), 200);
    return () => clearInterval(id);
  }, [playing, speed]);
  const tc = Math.min(t, 23.999);

  const readingsFor = useCallback((s: SimState, lastFix: number | null, at: number) => {
    if (!day) return undefined;
    const now = Math.min(at, 23.999);
    const snap = snapshot(day, s, now);
    const values: Record<string, number | string> = { setpoint_c: snap.setpoint, tr: Math.round(snap.tr) };
    for (const [k, v] of Object.entries(snap.equip)) values[k] = Math.round(v.kw * 10) / 10;
    return { simHour: now, kva: Math.round(snap.kva), kw: Math.round(snap.kw), values, lastFix, recent: checkWindow(now, lastFix).map((h) => hourRow(day, s, h, now)) };
  }, [day]);

  // readings: every sim hour, at most one write every 12 s (trailing), and with every event
  const lastPost = useRef(0), pending = useRef<ReturnType<typeof setTimeout> | null>(null);
  const viewRef = useRef(view); viewRef.current = view;
  const tRef = useRef(t); tRef.current = t;
  const hourNow = Math.floor(tc);
  useEffect(() => {
    if (!day || !view?.plan) return;
    const send = () => {
      lastPost.current = Date.now(); pending.current = null;
      const v = viewRef.current;
      const r = readingsFor({ applied: v?.applied ?? {}, faults: v?.faults ?? [] }, v?.lastFix ?? null, tRef.current);
      postPlant({ date, event: "readings", readings: r }).then((x) => setView((cur) => (cur && x.view.updated >= cur.updated ? { ...x.view } : cur))).catch(() => {});
    };
    const wait = READINGS_EVERY_MS - (Date.now() - lastPost.current);
    if (wait <= 0) send();
    else if (!pending.current) pending.current = setTimeout(send, wait);
  }, [hourNow, day, view?.plan?.version]);

  async function act(body: Record<string, unknown>, ok?: string) {
    if (!view) return;
    setBusy(true); setMsg(null);
    const full = { ...body, date, by: user, simHour: Math.round(tc * 100) / 100 };
    // readings as they will be after this event (same rules as the store), so the app sees the change at once
    const local = applyPlantEvent(view, full, istStamp(), (view.plan?.steps ?? []) as SavedAction[]);
    const readings = local.error ? undefined : readingsFor({ applied: local.entry.applied, faults: local.entry.faults }, local.entry.lastFix, tc);
    try {
      const r = await postPlant({ ...full, readings });
      setView(r.view);
      lastPost.current = Date.now();
      setMsg(r.error ? { kind: "err", text: r.error } : ok ? { kind: "ok", text: ok } : null);
    } catch (e) { setMsg({ kind: "err", text: String((e as Error).message ?? e) }); }
    finally { setBusy(false); }
  }

  if (err) return <Shell date={date} t={tc} user={user} setUser={setUser}><div className="pr-panel pr-err">{err}</div></Shell>;
  if (!view || !day) return <Shell date={date} t={tc} user={user} setUser={setUser}><div className="pr-panel">Loading the approved plan and the forecast for {dayLabel(date)}…</div></Shell>;

  const snap = snapshot(day, st, tc);
  const steps = [...day.steps].sort((a, b) => hourOf(a.start) - hourOf(b.start) || a.group.localeCompare(b.group));
  const faults = activeFaults(view);
  const ahuStep = steps.find((s) => s.group === "ahu");
  const conf = day.bookings.find((b) => Number(b.start.slice(0, 2)) <= 13 && (b.end === "23:59" || Number(b.end.slice(0, 2)) > 13));
  const after = ahuStep ? Math.min(23, hourOf(ahuStep.end) + 1) : 19;
  const quick: [string, number][] = [["06:00", 6], [conf ? "13:00 conference" : "13:00", 13], [`${String(after).padStart(2, "0")}:00 after event`, after]];
  const sf = soFar(day, st, tc);
  const pct = snap.kva / 1000;
  return (
    <Shell date={date} t={tc} user={user} setUser={setUser}>
      <section className="pr-top">
        <div className="pr-panel pr-clock">
          <div className="pr-lbl">Sim clock</div>
          <div className="pr-time num">{hhmm(tc)}</div>
          <div className="pr-row">
            <button className="pr-btn" onClick={() => setPlaying(!playing)} aria-pressed={playing}>{playing ? "❚❚ Pause" : "▶ Play"}</button>
            <label className="pr-small">1 h =
              <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>{SPEEDS.map((s) => <option key={s} value={s}>{s} s</option>)}</select>
            </label>
          </div>
          <input className="pr-slider" type="range" min={0} max={23.9} step={0.25} value={tc} aria-label="Sim hour" onChange={(e) => setT(Number(e.target.value))} />
          <div className="pr-row">{quick.map(([l, h]) => <button key={l} className="pr-btn ghost" onClick={() => setT(h)}>{l}</button>)}</div>
        </div>
        <div className="pr-panel pr-meter">
          <div className="pr-lbl">Main incoming meter · contract 1,000 kVA</div>
          <Gauge pct={pct} kva={snap.kva} />
          <div className="pr-small muted">Forecast as usually run: {n0(snap.habit_kva)} kVA · reading {n0(snap.kva)} kVA ({snap.kva >= snap.habit_kva ? "+" : "−"}{n0(Math.abs(snap.kva - snap.habit_kva))})</div>
        </div>
        <div className="pr-panel pr-sofar">
          <div className="pr-lbl">Today so far (00:00–{hhmm(tc)})</div>
          <table className="pr-tab num"><tbody>
            <tr><th></th><th>kWh</th><th>₹</th></tr>
            <tr><td>As usually run (forecast)</td><td>{n0(sf.habitKwh)}</td><td>{inr(sf.habitInr)}</td></tr>
            <tr><td>Simulated reading</td><td>{n0(sf.kwh)}</td><td>{inr(sf.inr)}</td></tr>
            <tr className={sf.inr <= sf.habitInr ? "good" : "bad"}><td>Difference</td><td>{sf.kwh <= sf.habitKwh ? "−" : "+"}{n0(Math.abs(sf.kwh - sf.habitKwh))}</td><td>{sf.inr <= sf.habitInr ? "−" : "+"}{inr(Math.abs(sf.inr - sf.habitInr))}</td></tr>
          </tbody></table>
          <div className="pr-small muted">Priced with the plan's tariff (energy + FSA + duty per kVAh, peak / off-peak ToD). Simulation only: never in savings or bills.</div>
        </div>
      </section>

      {msg && <div className={`pr-msg ${msg.kind}`} role={msg.kind === "err" ? "alert" : "status"}>{msg.text}</div>}
      {!view.plan && <div className="pr-msg err">No saved plan for {dayLabel(date)} yet. Save and approve steps on Tomorrow's plan in the Saffron app; the equipment follows habit until then.</div>}

      <section className="pr-main">
        <div>
          <div className="pr-tiles">
            {CONTROLLED.map((c) => <Tile key={c.id} id={c.id} name={c.name} sub={c.sub} day={day} st={st} t={tc} snap={snap} selected={sel === c.id} onClick={() => setSel(sel === c.id ? null : c.id)} />)}
          </div>
          <div className="pr-monitored">
            <div className="pr-lbl">Monitored only — never controlled</div>
            <div className="pr-mon-row">
              {MONITORED.map((m) => (
                <div key={m.id} className="pr-tile mon" data-testid={`mon-${m.id}`}>
                  <div className="pr-tname">{m.name}</div>
                  <div className="pr-kw num">{m.id === "FIRE" ? "Normal" : m.id === "ROOMS" ? `${n0(snap.monitored.ROOMS)} kW` : `${n0(snap.monitored[m.id])} kW`}</div>
                  <div className="pr-small muted">{m.why}</div>
                </div>
              ))}
            </div>
          </div>
          <FaultPanel faults={faults.map((f) => f.type)} busy={busy} hasAhu={!!ahuStep} t={tc} ahuOff={ahuStep ? t1(ahuStep.end) : null}
                      onFault={(type) => act({ event: "fault", type }, `${FAULTS[type].label}: injected at ${hhmm(tc)}. Watch the Saffron app's Today page.`)}
                      onClear={() => act({ event: "clearFault" }, "Fault cleared.")}
                      onReset={() => { if (window.confirm("Reset the simulation for this day? All applied steps and faults are removed (logged).")) act({ event: "reset", reason: "rehearsal reset" }, "Simulation reset."); }} />
        </div>
        <aside className="pr-panel pr-queue">
          <div className="pr-lbl">Approved steps to apply</div>
          {!steps.length && <p className="pr-small muted">No approved steps for {dayLabel(date)}. Approve them on Tomorrow's plan.</p>}
          <ol>{steps.map((a) => <QueueStep key={a.id} a={a} view={view} busy={busy} faults={faults.map((f) => f.type)}
              onApply={() => act({ event: "apply", stepId: a.id }, `Applied: ${a.setting}.`)}
              onOverride={(value, reason) => act({ event: "override", stepId: a.id, value, reason }, "Override logged.")} />)}</ol>
          <p className="pr-small muted">Before a step is applied its equipment follows habit (how last year ran on matched days); after Apply it follows the plan. Nothing is applied automatically.</p>
        </aside>
      </section>

      {sel && <SidePanel id={sel} day={day} st={st} t={tc} view={view} onClose={() => setSel(null)} />}

      <section className="pr-panel pr-audit">
        <div className="pr-lbl">Audit log · latest 10 · storage: {view.storage === "gist" ? "shared (gist)" : view.storage === "device" ? "this device only" : view.storage}</div>
        <table className="num"><tbody>
          {view.audit.slice(-10).reverse().map((r, i) => (
            <tr key={i} className={r.event.includes("refused") ? "bad" : r.event.includes("fault injected") ? "warn" : ""}>
              <td>{r.at.slice(11)}</td><td>sim {r.simHour !== undefined ? hhmm(r.simHour) : "—"}</td><td>{r.by}</td><td><b>{r.event}</b></td><td>{r.what}{r.why ? ` — ${r.why}` : ""}</td>
            </tr>
          ))}
          {!view.audit.length && <tr><td colSpan={5} className="muted">Nothing yet. Every Apply, Override, fault and reset appears here with who, when and why.</td></tr>}
        </tbody></table>
      </section>
      <footer className="pr-foot pr-small muted">
        SIMULATION. Curves: {loaded?.source}; habit per equipment from {day.profile.matched_days.length} matched days last year; reading = curve × (1 ± up to 2.5 %).
        The Saffron app checks the last {CHECK_WINDOW_H} simulated hours with the plan API's /check. Recommend only: the real plant is never controlled from here.
      </footer>
    </Shell>
  );
}

function Shell({ date, t, user, setUser, children }: { date: string; t: number; user: string; setUser: (u: string) => void; children: React.ReactNode }) {
  return (
    <div className="pr-shell">
      <header className="pr-head">
        <div className="pr-sim" data-testid="sim-banner"><span className="pr-dot" />SIMULATION · Gurugram · Sim time {dayLabel(date)} {hhmm(t)}</div>
        <div className="pr-brand">Saffron Plant Room <small>not live data</small></div>
        <label className="pr-user">Signed in as
          <select value={user} onChange={(e) => setUser(e.target.value)} aria-label="Signed in as">{USERS.map((u) => <option key={u}>{u}</option>)}</select>
        </label>
      </header>
      {children}
    </div>
  );
}

function Gauge({ pct, kva }: { pct: number; kva: number }) {
  const p = Math.max(0, Math.min(1.2, pct));
  const col = pct > 1 ? "var(--pr-red)" : pct >= 0.85 ? "var(--pr-amber)" : "var(--pr-green)";
  const a = Math.PI * (1 - p / 1.2), x = 100 + 80 * Math.cos(a), y = 100 - 80 * Math.sin(a);
  const lim = Math.PI * (1 - 1 / 1.2), lx = 100 + 80 * Math.cos(lim), ly = 100 - 80 * Math.sin(lim);
  return (
    <svg viewBox="0 0 200 118" className="pr-gauge" role="img" aria-label={`${Math.round(kva)} kVA, ${Math.round(pct * 100)} % of the 1,000 kVA contract`}>
      <path d="M20 100 A80 80 0 0 1 180 100" fill="none" stroke="var(--pr-line)" strokeWidth="14" strokeLinecap="round" />
      <path d={`M20 100 A80 80 0 0 1 ${x.toFixed(1)} ${y.toFixed(1)}`} fill="none" stroke={col} strokeWidth="14" strokeLinecap="round" />
      <line x1={100 + 66 * Math.cos(lim)} y1={100 - 66 * Math.sin(lim)} x2={lx + 8 * Math.cos(lim)} y2={ly - 8 * Math.sin(lim)} stroke="var(--pr-red)" strokeWidth="3" />
      <text x="100" y="86" textAnchor="middle" className="pr-gv" fill={col}>{Math.round(kva)}</text>
      <text x="100" y="106" textAnchor="middle" className="pr-gu">kVA · {Math.round(pct * 100)} % of limit</text>
    </svg>
  );
}

function Spark({ xs }: { xs: number[] }) {
  if (xs.length < 2) return <svg className="pr-spark" viewBox="0 0 100 24" />;
  const hi = Math.max(...xs, 1), lo = Math.min(...xs, 0);
  const pts = xs.map((v, i) => `${((i / 23) * 100).toFixed(1)},${(22 - ((v - lo) / (hi - lo || 1)) * 20).toFixed(1)}`).join(" ");
  return <svg className="pr-spark" viewBox="0 0 100 24" preserveAspectRatio="none"><polyline points={pts} fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>;
}

const valOf = (id: EquipId, s: ReturnType<typeof snapshot>) => (id === "CHW" ? s.setpoint : s.equip[id].kw);

function Tile({ id, name, sub, day, st, t, snap, selected, onClick }: { id: EquipId; name: string; sub: string; day: SimDay; st: SimState; t: number;
  snap: ReturnType<typeof snapshot>; selected: boolean; onClick: () => void }) {
  const e = snap.equip[id];
  const hist = useMemo(() => Array.from({ length: Math.floor(t) }, (_, h) => valOf(id, snapshot(day, st, h + 0.5))), [day, st, Math.floor(t), id]);
  const oos = e.status === "OUT OF SERVICE";
  return (
    <button className={`pr-tile ${oos ? "oos" : ""} ${selected ? "sel" : ""} f-${e.following}`} onClick={oos ? undefined : onClick} disabled={oos} data-testid={`tile-${id}`}>
      <div className="pr-trow"><span className="pr-tname">{name}</span><span className={`pr-st s-${e.status.replace(/ /g, "-")}`}>{e.status}</span></div>
      <div className="pr-small muted">{sub}</div>
      {id === "CHW" ? <div className="pr-kw num">{snap.setpoint.toFixed(1)} °C</div> : <div className="pr-kw num">{oos ? "—" : `${n0(e.kw)} kW`}</div>}
      <div className="pr-small">{oos ? "Out of service (equipment register)" : id === "CHW" ? `supply ${snap.supply_c.toFixed(1)} °C · ${e.following}` : `${e.setting} · ${e.following}`}</div>
      {!oos && <Spark xs={[...hist, valOf(id, snap)]} />}
    </button>
  );
}

function QueueStep({ a, view, busy, faults, onApply, onOverride }: { a: SavedAction; view: PlantView; busy: boolean; faults: FaultType[];
  onApply: () => void; onOverride: (value: string | number, reason: string) => void }) {
  const ap = view.applied[a.id];
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState<string>(a.group === "chw" ? String(a.setpoint_c ?? 7) : a.group === "chillers" ? "CH-1" : a.group === "ahu" ? a.end : "habit");
  const [reason, setReason] = useState("");
  const fixes = faults.filter((f) => FAULTS[f].fixGroup === a.group);
  return (
    <li className={`pr-step ${ap ? "applied" : ""} ${fixes.length ? "needs-fix" : ""}`} data-testid={`step-${a.group}-${a.start.slice(0, 2)}`}>
      <div className="pr-trow"><b className="num">{t1(a.start)}–{t1(a.end)}</b><span className="pr-money num">{a.saving_inr >= 1 ? inr(a.saving_inr) : "—"}</span></div>
      <div className="pr-sset">{a.setting}</div>
      <div className="pr-small muted">{a.equipment} → {equipOf(a).join(", ")}</div>
      <div className="pr-small pr-guard">🛡 {a.guardrail}</div>
      {ap && <div className={`pr-small ${ap.kind === "override" ? "warn" : "ok"}`}>{ap.kind === "override" ? `Overridden to ${ap.value} by ${ap.by} at ${ap.at.slice(11)} (sim ${hhmm(ap.simHour)}): ${ap.reason}` : `Applied by ${ap.by} at ${ap.at.slice(11)} (sim ${hhmm(ap.simHour)})`}</div>}
      {fixes.length > 0 && <div className="pr-small warn">Fault active: {fixes.map((f) => FAULTS[f].label).join(", ")}. Apply this step again to fix it.</div>}
      <div className="pr-row">
        <button className="pr-btn" disabled={busy || (!!ap && ap.kind === "apply" && !fixes.length)} onClick={onApply}>{fixes.length ? "Apply fix" : ap?.kind === "apply" ? "Applied" : "Apply"}</button>
        <button className="pr-btn ghost" disabled={busy} aria-pressed={open} onClick={() => setOpen(!open)}>Override…</button>
      </div>
      {open && (
        <div className="pr-ovr">
          {a.group === "chw" ? <label>Setpoint °C <input type="number" step="0.1" value={value} onChange={(e) => setValue(e.target.value)} aria-label="Override setpoint" /></label>
            : a.group === "chillers" ? <label>Stage <select value={value} onChange={(e) => setValue(e.target.value)}>{["CH-3", "CH-1", "CH-1+CH-3"].map((s) => <option key={s}>{s}</option>)}</select></label>
            : a.group === "ahu" ? <label>Off at <select value={value} onChange={(e) => setValue(e.target.value)}>{Array.from({ length: 10 }, (_, i) => hourOf(a.start) + 1 + i).filter((h) => h <= 26).map((h) => { const v = `${String(h % 24).padStart(2, "0")}:00${h >= 24 ? " (next day)" : ""}`; return <option key={h} value={v}>{t1(v)}</option>; })}</select></label>
            : <span className="pr-small">Keep running as usual (habit)</span>}
          <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (needed for the log)" aria-label="Override reason" />
          <button className="pr-btn" disabled={busy || !reason.trim()} onClick={() => { onOverride(a.group === "chw" ? Number(value) : value, reason); setOpen(false); setReason(""); }}>Log override</button>
        </div>
      )}
    </li>
  );
}

function FaultPanel({ faults, busy, hasAhu, t, ahuOff, onFault, onClear, onReset }: { faults: FaultType[]; busy: boolean; hasAhu: boolean; t: number; ahuOff: string | null;
  onFault: (f: FaultType) => void; onClear: () => void; onReset: () => void }) {
  return (
    <div className="pr-panel pr-faults">
      <div className="pr-lbl">Simulate a fault (demo)</div>
      <div className="pr-row wrap">
        {(Object.keys(FAULTS) as FaultType[]).map((f, i) => {
          const off = f === "ahu_left_on" && !hasAhu;
          return <button key={f} className={`pr-btn warn ${faults.includes(f) ? "on" : ""}`} disabled={busy || off || faults.includes(f)} onClick={() => onFault(f)}
                         title={off ? "No banquet booking in the approved plan, so there is no AHU off step to break." : FAULTS[f].what}>{i + 1}. {FAULTS[f].label}</button>;
        })}
        <button className="pr-btn" disabled={busy || !faults.length} onClick={onClear}>Clear fault</button>
        <button className="pr-btn ghost" disabled={busy} onClick={onReset}>Reset simulation</button>
      </div>
      <div className="pr-small muted">
        {faults.length ? `Active: ${faults.map((f) => FAULTS[f].label).join(", ")}.` : "No fault active."}
        {hasAhu && ahuOff ? ` Fault 1 runs the AHU on from its planned off time (${ahuOff}).` : ""} Fault 3 acts only inside 18:00–22:00{t < 18 ? " (from 18:00)" : ""}.
        The alert needs 2 of the last {CHECK_WINDOW_H} simulated hours to differ from the approved plan (the plan check's own rule).
      </div>
    </div>
  );
}

function SidePanel({ id, day, st, t, view, onClose }: { id: EquipId; day: SimDay; st: SimState; t: number; view: PlantView; onClose: () => void }) {
  const name = CONTROLLED.find((c) => c.id === id)!.name;
  const snap = snapshot(day, st, t);
  const planned: SimState = useMemo(() => ({ applied: Object.fromEntries(day.steps.map((a) => [a.id, { stepId: a.id, kind: "apply" as const, by: "", at: "", simHour: 0 }])), faults: [] }), [day]);
  const habit: SimState = { applied: {}, faults: [] };
  const data = useMemo(() => Array.from({ length: 24 }, (_, h) => ({
    h: `${String(h).padStart(2, "0")}:00`,
    habit: valOf(id, snapshot(day, habit, h + 0.5, false)), plan: valOf(id, snapshot(day, planned, h + 0.5, false)),
    reading: h <= Math.floor(t) ? valOf(id, snapshot(day, st, h < Math.floor(t) ? h + 0.5 : t)) : null,
  })), [day, st, Math.floor(t), id]);
  const c = chillersAt(day, st, t);
  const stepIds = new Set(day.steps.filter((a) => equipOf(a).includes(id)).map((a) => a.id));
  const audit = view.audit.filter((r) => r.stepId && stepIds.has(r.stepId)).slice(-8).reverse();
  const isCh = id === "CH-1" || id === "CH-3";
  const kw = snap.equip[id].kw;
  return (
    <section className="pr-panel pr-side" data-testid="side-panel">
      <div className="pr-trow"><b>{name}</b><button className="pr-btn ghost" onClick={onClose}>Close</button></div>
      <dl className="pr-facts num">
        <dt>Live</dt><dd>{id === "CHW" ? `${snap.setpoint.toFixed(1)} °C` : `${n0(kw)} kW`} · {snap.equip[id].following}</dd>
        {isCh && <><dt>kW / TR</dt><dd>{kw > 1 ? (c.total / c.tr).toFixed(3) : "—"} (plant {c.stage}, {n0(c.tr)} TR)</dd></>}
        {(isCh || id === "CHW") && <><dt>CHW supply / return</dt><dd>{snap.supply_c.toFixed(1)} °C / not metered</dd><dt>Setpoint</dt><dd>{snap.setpoint.toFixed(1)} °C ({snap.setpointSource})</dd></>}
      </dl>
      <div style={{ height: 180 }}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 6, right: 8, left: -12, bottom: 0 }}>
            <CartesianGrid stroke="#2a333c" vertical={false} />
            <XAxis dataKey="h" tick={{ fill: "#9aa6b1", fontSize: 10 }} interval={3} />
            <YAxis tick={{ fill: "#9aa6b1", fontSize: 10 }} />
            <Tooltip contentStyle={{ background: "#161b20", border: "1px solid #2a333c", color: "#e8ecef" }} />
            <ReferenceLine x={`${String(Math.floor(t)).padStart(2, "0")}:00`} stroke="#e8613c" strokeDasharray="3 3" />
            <Line dataKey="habit" name="habit (matched days)" stroke="#7b8794" dot={false} strokeDasharray="4 3" isAnimationActive={false} />
            <Line dataKey="plan" name="approved plan" stroke="#3fbf7f" dot={false} isAnimationActive={false} />
            <Line dataKey="reading" name="simulated reading" stroke="#e8613c" dot={false} strokeWidth={2} isAnimationActive={false} connectNulls={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="pr-small muted">Grey: habit · green: approved plan · coral: simulated reading so far.</div>
      <div className="pr-lbl" style={{ marginTop: 8 }}>Audit for this equipment</div>
      {audit.length ? <ul className="pr-small">{audit.map((r, i) => <li key={i}>{r.at.slice(11)} {r.by}: {r.event} — {r.what}{r.why ? ` (${r.why})` : ""}</li>)}</ul> : <p className="pr-small muted">No actions yet.</p>}
    </section>
  );
}
