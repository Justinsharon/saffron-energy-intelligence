import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useClock } from "../App";
import { Gauge, KVA } from "../components/parts";
import { load, SITE_NAME, useData, type ForecastDay } from "../data";
import { useWeather } from "../live";
import { useFeeds } from "../feed";
import { addMs, DAY_MS, fmtD, inr, istNow, n, parse } from "../format";
import { LOAD } from "../copy";
import { actionId, hh, TAG, type Booking, type PlanDay, type PlanSite, type RiskCal } from "../plan";
import { apiPlan, checkPlan, getPlan, type CheckResult, type CheckStep, type PlanResult } from "../planApi";
import { checkActions, type PlanView, type SavedAction } from "../planlog";
import { loadPlan, plannerName, postPlan, setPlannerName } from "../planStore";

const HEAD: Record<string, string> = {
  "BREACH RISK": "Risk of going over the power limit", WARNING: "Close to the power limit", "STACKING WATCH": "Watch the afternoon", OK: "Comfortably under the limit",
};
const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const dow = (d: string) => DAYS[parse(d).getUTCDay()];
const addDays = (d: string, k: number) => addMs(`${d}T00:00`, k * DAY_MS).slice(0, 10);
// each hotel's venues (Gurugram's halls; Jaipur / Goa from their events calendars, as the plan API validates them)
const VENUES: Record<PlanSite, { v: string; label: string }[]> = {
  GGN: [{ v: "A", label: "Hall A" }, { v: "B", label: "Hall B" }, { v: "A+B", label: "Halls A + B" }],
  JAI: [{ v: "Palace Lawns", label: "Palace Lawns" }, { v: "Durbar Hall", label: "Durbar Hall" }],
  GOA: [{ v: "Sunset Deck + Ballroom", label: "Sunset Deck + Ballroom" }],
};
const NEW_BOOKING: Record<PlanSite, Booking> = { GGN: { hall: "A", start: "09:00", end: "18:00", guests: 150 },
  JAI: { hall: "Palace Lawns", start: "18:00", end: "23:00", guests: 300 }, GOA: { hall: "Sunset Deck + Ballroom", start: "18:00", end: "23:00", guests: 200 } };
// what the charts mark per hotel: contract limit, warning line, and the chiller lines (Gurugram: CH-3 / CH-1; Jaipur / Goa: one chiller
// with its 10 % margin, both chillers) - from each hotel's register
const LIMITS: Record<PlanSite, { cd: number; warn: number; chillers: { y: number; label: string }[]; chillerNote: string }> = {
  GGN: { cd: 1000, warn: 920, chillers: [{ y: 130, label: "CH-3 limit" }, { y: 280, label: "CH-1 limit" }], chillerNote: "One small chiller (CH-3) up to 130 TR · one large (CH-1) up to 280 TR" },
  JAI: { cd: 700, warn: 644, chillers: [{ y: 180, label: "one chiller" }, { y: 400, label: "both chillers" }], chillerNote: "One chiller (200 TR) up to 180 TR with a 10 % margin · both up to 400 TR" },
  GOA: { cd: 600, warn: 552, chillers: [{ y: 135, label: "one chiller" }, { y: 300, label: "both chillers" }], chillerNote: "One chiller (150 TR) up to 135 TR with a 10 % margin · both up to 300 TR" },
};
const PLAN_SITES: PlanSite[] = ["GGN", "JAI", "GOA"];
const siteStore = { get: (): PlanSite => { try { const s = localStorage.getItem("plan_site"); return s === "JAI" || s === "GOA" ? s : "GGN"; } catch { return "GGN"; } },
  set: (s: PlanSite) => { try { localStorage.setItem("plan_site", s); } catch { /* private window */ } } };
const START_H = Array.from({ length: 33 }, (_, i) => 6 + i / 2);       // 06:00 .. 22:00 in half hours
const END_H = Array.from({ length: 34 }, (_, i) => 7 + i / 2);         // 07:00 .. 23:30, plus "past midnight"
const hm = (h: number) => `${String(Math.floor(h)).padStart(2, "0")}:${h % 1 ? "30" : "00"}`;

interface PlanIndex { days: Record<string, { tmax: number; rooms: number; covers: number }>; cooling_model: Record<string, number | string>; risk: RiskCal }
interface Form { rooms: number; guests: number; covers: number; bookings: Booking[]; notes: string; touched: Record<string, boolean> }

function usePlanDay(date: string): PlanDay | null | undefined {
  const [v, setV] = useState<PlanDay | null | undefined>(undefined);
  useEffect(() => { let on = true; setV(undefined); load<PlanDay>(`plan/${date}.json`).then((x) => on && setV(x)).catch(() => on && setV(null)); return () => { on = false; }; }, [date]);
  return v;
}

/** Electricity and peak power demand, then cooling load, for the planned day. */
function ForecastCharts({ kw, kva, tr, site }: { kw: number[]; kva: number[]; tr: number[]; site: PlanSite }) {
  const rows = kw.map((_, h) => ({ h, kw: Math.round(kw[h]), kva: Math.round(kva[h]), tr: Math.round(tr[h]) }));
  const L = LIMITS[site];
  const top = Math.max(L.cd + 100, ...kva.map((x) => x + 60));
  return (
    <div className="grid g2 charts2">
      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Electricity and peak demand</h3>
        <div className="legend" style={{ marginBottom: 4 }}>
          <span><i style={{ background: "#151515" }} />Electricity used (kW)</span>
          <span><i style={{ background: "#e8613c" }} />Peak power demand (kVA)</span>
          <span><i style={{ background: "#c93a1c" }} />Contracted limit {n(L.cd)} kVA</span>
          <span><i style={{ background: "#e2a04a" }} />{site === "GGN" ? "Early-warning" : "Demand step line (8 % below)"} {n(L.warn)} kVA</span>
        </div>
        <ResponsiveContainer width="100%" height={240}>
          <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -10 }}>
            <CartesianGrid stroke="#efefef" vertical={false} />
            <XAxis dataKey="h" tickFormatter={(h) => `${h}:00`} tick={{ fontSize: 11, fill: "#9b9b9b" }} minTickGap={18} />
            <YAxis domain={[0, top]} tick={{ fontSize: 11, fill: "#9b9b9b" }} width={46} />
            <Tooltip labelFormatter={(h) => `${h}:00`} formatter={(v: number, k: string) => [n(v) + (k === "kw" ? " kW" : " kVA"), k === "kw" ? "Electricity" : "Peak demand"]} />
            <ReferenceLine y={L.cd} stroke="#c93a1c" strokeDasharray="5 3" />
            <ReferenceLine y={L.warn} stroke="#e2a04a" strokeDasharray="2 3" />
            <Line dataKey="kw" stroke="#151515" strokeWidth={1.6} dot={false} isAnimationActive={false} />
            <Line dataKey="kva" stroke="#e8613c" strokeWidth={2.4} dot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Cooling load</h3>
        <div className="legend" style={{ marginBottom: 4 }}>
          <span><i style={{ background: "#3f6fa8" }} />Cooling the hotel needs (tons, TR)</span>
          <span><i style={{ background: "#9b9b9b" }} />{L.chillerNote}</span>
        </div>
        <ResponsiveContainer width="100%" height={240}>
          <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -10 }}>
            <CartesianGrid stroke="#efefef" vertical={false} />
            <XAxis dataKey="h" tickFormatter={(h) => `${h}:00`} tick={{ fontSize: 11, fill: "#9b9b9b" }} minTickGap={18} />
            <YAxis domain={[0, Math.max(L.chillers[0].y + 60, ...tr.map((x) => x + 30))]} tick={{ fontSize: 11, fill: "#9b9b9b" }} width={46} />
            <Tooltip labelFormatter={(h) => `${h}:00`} formatter={(v: number) => [n(v) + " TR", "Cooling load"]} />
            {L.chillers.map((c) => <ReferenceLine key={c.y} y={c.y} stroke="#9b9b9b" strokeDasharray="4 3" label={{ value: c.label, position: "insideTopRight", fontSize: 10, fill: "#9b9b9b" }} />)}
            <Line dataKey="tr" stroke="#3f6fa8" strokeWidth={2.2} dot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function Field({ label, value, suggested, touched, onChange, min = 0, max }: { label: string; value: number; suggested: number; touched: boolean; onChange: (v: number) => void; min?: number; max?: number }) {
  return (
    <label className="field">
      <span className="small muted">{label}</span>
      <input type="number" inputMode="numeric" min={min} max={max} value={value} onChange={(e) => onChange(Math.max(min, Math.min(max ?? 1e9, Number(e.target.value) || 0)))} />
      <span className={`hint ${touched ? "" : "sugg"}`}>{touched ? (value === suggested ? "same as suggested" : `suggested ${n(suggested)}`) : "suggested from the usual pattern"}</span>
    </label>
  );
}

function BookingRow({ b, venues, onChange, onRemove }: { b: Booking; venues: { v: string; label: string }[]; onChange: (b: Booking) => void; onRemove: () => void }) {
  const sh = Number(b.start.slice(0, 2)) + (b.start.slice(3, 5) === "30" ? 0.5 : 0);
  return (
    <div className="booking">
      <select aria-label="Venue" value={b.hall} onChange={(e) => onChange({ ...b, hall: e.target.value })}>{venues.map((h) => <option key={h.v} value={h.v}>{h.label}</option>)}</select>
      <select aria-label="Start" value={b.start} onChange={(e) => onChange({ ...b, start: e.target.value })}>{START_H.map((h) => <option key={h} value={hm(h)}>from {hm(h)}</option>)}</select>
      <select aria-label="End" value={b.end} onChange={(e) => onChange({ ...b, end: e.target.value })}>
        {END_H.filter((h) => h > sh).map((h) => <option key={h} value={hm(h)}>to {hm(h)}</option>)}
        <option value="23:59">to past midnight</option>
      </select>
      <label className="guests"><input type="number" inputMode="numeric" min={10} max={1000} step={10} value={b.guests} aria-label="Guests"
             onChange={(e) => onChange({ ...b, guests: Math.max(0, Math.min(1000, Number(e.target.value) || 0)) })} /> guests</label>
      <button className="btn ghost" onClick={onRemove} aria-label="Remove booking">Remove</button>
    </div>
  );
}

/** One timed action with Approve / Skip with a reason / Edit time. */
const BADGE: Record<string, string> = { Followed: "c-ok", Partly: "c-med", "Not followed": "c-high", "Not yet due": "c-low", Skipped: "c-low", "Can't tell (no meter)": "c-dq",
  "Not approved": "c-low", "Suggested, not approved": "c-low" };
const UNCOUNTED = new Set(["Not approved", "Suggested, not approved"]);

/** Plan vs actual for one step: badge, hours that differed, ₹ verified or missed. */
function CheckLine({ c }: { c: CheckStep }) {
  const money = c.status === "Followed" || c.status === "Partly" ? (c.verified_inr >= 1 ? ` · ${inr(c.verified_inr)} saved so far` : "") : "";
  const miss = c.extra_inr >= 1 ? ` · ${inr(c.extra_inr)} missed` : c.extra_kwh >= 1 ? ` · ${n(c.extra_kwh)} kWh more than planned` : "";
  if (UNCOUNTED.has(c.status))                                     // only approved steps of a saved plan are checked or counted
    return (
      <div className="check-line grey">
        <span className="chip c-low">{c.status}</span>
        <span className="small">{c.would_have_saved_inr >= 1 ? `Would have saved ${inr(c.would_have_saved_inr)} if followed. ` : ""}Not checked and not counted: {c.status === "Not approved" ? "the step was never approved" : "no plan was saved for this day"}.</span>
      </div>
    );
  return (
    <div className="check-line">
      <span className={`chip ${BADGE[c.status] ?? "c-low"}`}>{c.status}</span>
      <span className="small">{c.status === "Not yet due" ? "Not reached yet." : c.status === "Skipped" ? `Skipped by the team${c.reason ? `: ${c.reason}` : ""}.`
        : `Checked ${c.hours_checked} h: ${c.what_was_checked}.`}{c.hours_differed.length ? ` Differed at ${c.hours_differed.slice(0, 6).join(", ")}${c.hours_differed.length > 6 ? "…" : ""}.` : ""}{money}{miss}</span>
    </div>
  );
}

function Step({ a, edit, decision, canDecide, busy, onDecide, chk }: {
  a: SavedAction; edit?: PlanView["edits"][string]; decision?: PlanView["decisions"][string]; canDecide: boolean; busy: boolean; chk?: CheckStep;
  onDecide: (ev: "approve" | "skip" | "edit", extra?: Record<string, string>) => void;
}) {
  const [mode, setMode] = useState<"" | "skip" | "edit">("");
  const [reason, setReason] = useState("");
  const h = (t: string) => Number(t.slice(0, 2)) + (t.includes("next day") ? 24 : 0);
  const [s, setS] = useState(h(edit?.start ?? a.start)), [e, setE] = useState(h(edit?.end ?? a.end));
  const start = edit?.start ?? a.start, end = edit?.end ?? a.end;
  const state = decision?.event === "approve" ? "ok" : decision?.event === "skip" ? "skip" : "";
  const minStart = a.group === "ahu" && a.start_h != null ? Math.max(0, a.start_h - 2) : 0;
  const t = (x: string) => x.replace(" (next day)", "⁺¹");
  return (
    <li className={`step ${state}`}>
      <div className="stime"><b>{t(start)}</b><span>to {t(end)}</span>{edit && <em>edited</em>}</div>
      <div className="body">
        <div className="row1"><span className="tag">{TAG[a.group]}</span><strong>{edit && (a.group === "ahu" || a.group === "lighting") ? `On at ${start}, off at ${end}` : a.setting}</strong><span className="money">{a.saving_inr >= 1 ? `${inr(a.saving_inr)} vs last year` : a.counted === false ? "not verifiable, not counted" : a.group === "demand" ? "watch only, no ₹ claimed" : "no saving, keeps it safe"}</span></div>
        <div className="small muted">{a.equipment}</div>
        <p className="why">{a.reason}</p>
        {edit && <p className="small" style={{ margin: "0 0 8px", color: "var(--coral)" }}>Time changed from {a.start}–{a.end} to {start}–{end} by {edit.by} at {edit.at.slice(11)}{edit.reason ? `: ${edit.reason}` : ""}.</p>}
        <div className="guard small"><span aria-hidden>🛡</span><span>{a.guardrail}</span></div>
        {chk && <CheckLine c={chk} />}
        {decision && <div className={`small status ${state}`}>{decision.event === "approve" ? `Approved by ${decision.by} at ${decision.at.slice(11)}` : `Skipped by ${decision.by} at ${decision.at.slice(11)}: ${decision.reason}`}</div>}
        {canDecide && (
          <div className="btn-row" style={{ marginTop: 8 }}>
            <button className="btn" disabled={busy || state === "ok"} onClick={() => onDecide("approve")}>Approve</button>
            <button className="btn ghost" disabled={busy} aria-pressed={mode === "skip"} onClick={() => setMode(mode === "skip" ? "" : "skip")}>Skip…</button>
            <button className="btn ghost" disabled={busy} aria-pressed={mode === "edit"} onClick={() => setMode(mode === "edit" ? "" : "edit")}>Edit time</button>
          </div>
        )}
        {mode === "skip" && (
          <div className="inline-form">
            <input value={reason} onChange={(x) => setReason(x.target.value)} placeholder="Why skip? (needed for the log)" />
            <button className="btn" disabled={!reason.trim() || busy} onClick={() => { onDecide("skip", { reason }); setMode(""); }}>Skip this action</button>
          </div>
        )}
        {mode === "edit" && (
          <div className="inline-form">
            <select aria-label="New start" value={s} onChange={(x) => setS(Number(x.target.value))}>{Array.from({ length: 30 - minStart }, (_, i) => i + minStart).map((k) => <option key={k} value={k}>from {hh(k)}</option>)}</select>
            <select aria-label="New end" value={e} onChange={(x) => setE(Number(x.target.value))}>{Array.from({ length: 30 }, (_, i) => i + 1).filter((k) => k > s).map((k) => <option key={k} value={k}>to {hh(k)}</option>)}</select>
            <button className="btn" disabled={busy || e <= s} onClick={() => { onDecide("edit", { start: hh(s), end: hh(e) }); setMode(""); }}>Save new time</button>
          </div>
        )}
      </div>
    </li>
  );
}

const LIVE_FIRST = "2026-10-02";            // first live-year day with a plan (look back)

function TomorrowPlan() {
  const { now: clockNow, live } = useClock();
  const realToday = istNow().slice(0, 10);
  const today = live ? realToday : clockNow.slice(0, 10);        // looking back: plan and check that day
  const tomorrow = addDays(today, 1);
  const idx = useData<PlanIndex>("plan/index.json");
  const [date, setDate] = useState(live ? tomorrow : today);
  useEffect(() => setDate(live ? tomorrow : today), [live, today]);
  const asOf = live ? istNow() : clockNow;
  const past = date <= today;
  const [site, setSiteState] = useState<PlanSite>(siteStore.get);
  const setSite = (s: PlanSite) => { siteStore.set(s); setSiteState(s); };
  const ggnDay = usePlanDay(date);
  // Jaipur / Goa: the usual inputs for the date come from the plan API (their models are not shipped to the browser)
  const [siteBase, setSiteBase] = useState<{ rooms: number; guests: number; covers: number } | null | undefined>(undefined);
  useEffect(() => {
    if (site === "GGN") return;
    let on = true;
    setSiteBase(undefined);
    apiPlan({ date, site }).then((r) => on && setSiteBase(r.defaults ?? null)).catch(() => on && setSiteBase(null));
    return () => { on = false; };
  }, [site, date]);
  const day = site === "GGN" ? ggnDay : undefined;
  const base = site === "GGN" ? (ggnDay ? ggnDay.defaults : ggnDay) : siteBase;
  const wx = useWeather();
  const feeds = useFeeds(istNow(), true);
  const g = feeds?.feeds[site].today;
  const L = LIMITS[site];
  const [name, setName] = useState(plannerName());
  const [form, setForm] = useState<Form | null>(null);
  const [saved, setSaved] = useState<PlanView | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const last = useMemo(() => { const ds = Object.keys(idx?.days ?? {}).filter((d) => d >= addDays(realToday, 1)).sort(); return ds[Math.min(13, ds.length - 1)] ?? addDays(realToday, 14); }, [idx, realToday]);

  // a saved plan for the date pre-fills the form; otherwise the day's suggested values
  const baseKey = base ? `${site}|${date}|${base.rooms}|${base.guests}|${base.covers}` : "";
  useEffect(() => {
    if (!base) return;
    let on = true;
    setForm(null); setSaved(null); setErr("");
    loadPlan(date, site).then((v) => {
      if (!on) return;
      setSaved(v);
      const i = v.plan?.inputs;
      setForm(i ? { rooms: i.rooms, guests: i.guests, covers: i.covers, bookings: i.bookings, notes: i.notes, touched: { rooms: true, guests: true, covers: true } }
                : { rooms: base.rooms, guests: base.guests, covers: base.covers, bookings: [], notes: "", touched: {} });
    });
    return () => { on = false; };
  }, [baseKey]);

  const hourly = site === "GGN" ? wx?.hourly.GGN[date] : undefined;
  const temps = hourly && hourly.length === 24 ? hourly : null;
  // the plan API (models on the actual inputs), 600 ms after the last change; offline estimate in the browser if it fails or is slow
  const [res, setRes] = useState<PlanResult | null>(null);
  const [planning, setPlanning] = useState(false);
  const reqKey = form ? JSON.stringify([site, date, form.rooms, form.guests, form.covers, form.bookings]) : "";
  const [planErr, setPlanErr] = useState("");
  useEffect(() => {
    if (!base || !form) return;
    let on = true;
    setPlanning(true);
    const t = setTimeout(() => {
      getPlan({ date, site, rooms: form.rooms, guests: form.guests, covers: form.covers, bookings: form.bookings }, { day: day ?? null, temps, cal: idx?.risk ?? null })
        .then((r) => { if (on) { setRes(r); setPlanErr(""); } })
        .catch((e) => { if (on) { setRes(null); setPlanErr(String((e as Error).message ?? e)); } }).finally(() => on && setPlanning(false));
    }, 600);
    return () => { on = false; clearTimeout(t); };
  }, [reqKey, baseKey, temps, idx]);
  useEffect(() => setRes(null), [date, site]);
  const actions: SavedAction[] = useMemo(() => (res ? res.actions.map((a) => ({ ...a, id: actionId(a) })) : []), [res]);
  const risk = res?.risk ?? null;

  // plan vs actual: today or a past day - the saved plan (edited times, decisions) or, if none was saved, the suggested plan shown
  const [chk, setChk] = useState<CheckResult | null | undefined>(undefined);
  const savedSig = saved?.plan ? `${saved.plan.n}|${saved.log.length}` : "";
  const shownSig = actions.map((a) => a.id + a.setting).join(";");
  useEffect(() => {
    setChk(undefined);
    if (!past || !res) return;
    let on = true;
    const acts = saved?.plan ? checkActions(saved) : actions;
    checkPlan(date, asOf.slice(0, 13) + ":00", acts, saved?.plan ? "saved" : "suggested", site).then((r) => on && setChk(r));
    return () => { on = false; };
  }, [past, site, date, savedSig, saved?.plan ? "" : shownSig, asOf.slice(0, 13)]);
  const chkBy = useMemo(() => Object.fromEntries((chk?.steps ?? []).map((x) => [x.id, x])), [chk]);
  const sig = (xs: { id: string; setting: string; end: string }[]) => xs.map((a) => `${a.id}=${a.setting}@${a.end}`).join(";");
  const dirty = !saved?.plan || sig(saved.plan.actions) !== sig(actions);
  const approved = actions.filter((a) => saved?.decisions[a.id]?.event === "approve").length;
  const set = (k: keyof Form, v: unknown) => form && setForm({ ...form, [k]: v, touched: { ...form.touched, [k]: true } });

  async function send(body: Record<string, unknown>) {
    setBusy(true); setErr("");
    try { setSaved(await postPlan({ date, site, by: name.trim(), ...body })); }
    catch (e) { setErr(String((e as Error).message ?? e)); }
    finally { setBusy(false); }
  }
  const submit = () => form && res && send({ event: "submit", inputs: { rooms: form.rooms, guests: form.guests, covers: form.covers, bookings: form.bookings, notes: form.notes,
    temps_source: res?.weather ?? "", plan_source: res?.source === "api" ? "plan API" : "offline estimate (browser)" }, actions });
  async function decide(a: SavedAction, ev: "approve" | "skip" | "edit", extra: Record<string, string> = {}) {
    if (!name.trim()) { setErr("Enter your name first: every decision is logged with who made it."); return; }
    setPlannerName(name);
    if (dirty) await submit();
    await send({ event: ev, action_id: a.id, ...extra });
  }

  const title = `${dow(date)} ${fmtD(date)}`;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{past ? `Plan vs actual, ${date === today ? "today" : fmtD(date)}` : "Tomorrow's plan"}, {SITE_NAME[site]}</h1>
          <div className="btn-row" role="group" aria-label="Hotel" style={{ margin: "6px 0 8px" }}>
            {PLAN_SITES.map((s) => <button key={s} className={`btn ${s === site ? "accent" : "ghost"}`} aria-pressed={s === site} onClick={() => setSite(s)}>{SITE_NAME[s]}</button>)}
          </div>
          <p className="lead">{past ? "Each step of the day's plan, checked against the meters up to " + (live ? "now" : "the hour you are looking back at") + ". Followed steps count as verified savings; steps not followed show what they cost."
            : "Enter tomorrow's bookings. The forecast and the operating plan update as you type. Each step is a recommendation: approve it, skip it with a reason, or change its time. Nothing is switched automatically, and every decision is logged."}</p>
          {g && g.peak_kva != null && <span className="feed-note">Today so far: peak {n(g.peak_kva)} kVA at {String(g.peak_hour).padStart(2, "0")}:00 (live feed, simulated meters)</span>}
        </div>
        <label className="field" style={{ minWidth: 200 }}>
          <span className="small muted">Plan for</span>
          <input type="date" min={LIVE_FIRST} max={live ? last : today} value={date} onChange={(e) => e.target.value && setDate(e.target.value)} />
          <span className="hint">{date === tomorrow ? "tomorrow" : date === today ? "today: plan vs actual so far" : date < today ? "past day: plan vs actual" : `${Math.round((parse(date).getTime() - parse(today).getTime()) / DAY_MS)} days ahead`}</span>
        </label>
      </div>

      {base === undefined || (base && !form) ? <p className="muted">Loading the forecast…</p> : base === null ? <p className="muted">{site === "GGN" ? `No forecast is prepared for ${fmtD(date)} yet (plans cover the next few weeks).`
        : `The planning service did not answer, and ${SITE_NAME[site]}'s plan comes from it only (its models are not in the browser). Try again in a minute.`}</p> : form && (<>
          <section className="panel" aria-labelledby="bk">
            <h2 id="bk" style={{ marginTop: 0 }}>Bookings for {title}</h2>
            <div className="grid g3 form3">
              <Field label="Rooms occupied" value={form.rooms} suggested={base.rooms} touched={!!form.touched.rooms} max={{ GGN: 220, JAI: 160, GOA: 140 }[site]} onChange={(v) => set("rooms", v)} />
              <Field label="Guests in house" value={form.guests} suggested={base.guests} touched={!!form.touched.guests} max={700} onChange={(v) => set("guests", v)} />
              <Field label="Restaurant covers" value={form.covers} suggested={base.covers} touched={!!form.touched.covers} max={2000} onChange={(v) => set("covers", v)} />
            </div>
            <h3 style={{ margin: "18px 0 8px" }}>{site === "GGN" ? "Banquet bookings" : "Event bookings"}</h3>
            {form.bookings.length === 0 && <p className="muted small" style={{ marginTop: 0 }}>No {site === "GGN" ? "banquet" : "event"} bookings entered. Last year's events on this date are not carried over.</p>}
            {form.bookings.map((b, i) => (
              <BookingRow key={i} b={b} venues={VENUES[site]} onChange={(x) => set("bookings", form.bookings.map((y, k) => (k === i ? x : y)))} onRemove={() => set("bookings", form.bookings.filter((_, k) => k !== i))} />
            ))}
            <button className="btn ghost" style={{ marginTop: 6 }} onClick={() => set("bookings", [...form.bookings, NEW_BOOKING[site]])}>+ Add a booking</button>
            <label className="field" style={{ marginTop: 16 }}>
              <span className="small muted">Notes for the duty team</span>
              <textarea rows={2} value={form.notes} onChange={(e) => set("notes", e.target.value)} placeholder="e.g. VIP arrival 15:00, laundry short-staffed" />
            </label>
            <p className="small muted" style={{ marginBottom: 0 }}>Weather: {res ? `${res.weather || "typical temperatures for this date"}, top ${Math.round(Math.max(...res.forecast.temp))} °C` : "checking…"}. Rooms and covers are suggested from the usual pattern for this time of year.</p>
          </section>

          {!res ? <p className="muted" style={{ marginTop: 18 }}>{planErr && !planning ? `The plan could not be worked out: ${planErr}` : "Working out the plan…"}</p> : (<>

          <h2>Forecast</h2>
          <ForecastCharts kw={res.forecast.kw} kva={res.forecast.kva} tr={res.forecast.tr} site={site} />

          <div className="section-title plan-head">
            <div>
              <h2 style={{ margin: 0 }}>Operating plan {res.source === "offline" && <span className="chip c-med" style={{ verticalAlign: "middle" }}>offline estimate</span>}
                {planning && <span className="small muted" style={{ fontWeight: 500, marginLeft: 8 }}>updating…</span>}</h2>
              <p className="small muted" style={{ margin: "4px 0 0" }}><strong className="plan-total">{inr(res.total_inr)}</strong> planned saving vs how last year ran on similar days · <strong>{approved} of {actions.length}</strong> approved
                {saved?.plan && <> · saved by {saved.plan.by} at {saved.plan.at.slice(11)}{saved.storage === "device" ? " (this device only: shared storage is not set up)" : ""}</>}</p>
              {past && chk && chk.summary.approved === 0 && <p className="small muted" style={{ margin: "4px 0 0" }}>{saved?.plan ? "No step of the saved plan was approved" : "No plan was saved for this day"}: the suggested plan would have saved {inr(chk.summary.would_have_saved_inr)} if followed. Not checked and not counted in any total; no deviation alerts.</p>}
              {past && chk && chk.summary.approved > 0 && <p className="small" style={{ margin: "4px 0 0" }}><strong>{chk.summary.followed} of {chk.summary.due} approved steps followed so far</strong>
                {chk.summary.not_followed ? `, ${chk.summary.not_followed} not followed` : ""} · <strong style={{ color: "var(--green)" }}>{inr(chk.summary.verified_inr)} saved</strong> / <strong style={{ color: "var(--coral)" }}>{inr(chk.summary.missed_inr)} missed</strong> so far (to {chk.as_of.slice(11, 16)}{chk.as_of.slice(0, 10) !== date ? ` on ${chk.as_of.slice(8, 10)}/${chk.as_of.slice(5, 7)}` : ""})</p>}
              {past && chk === null && <p className="small muted" style={{ margin: "4px 0 0" }}>The plan check needs the planning service, which did not answer. Try again in a minute.</p>}
            </div>
            <div className="btn-row" style={{ alignItems: "center" }}>
              <input className="name" value={name} onChange={(e) => setName(e.target.value)} onBlur={() => name.trim() && setPlannerName(name)} placeholder="Your name" aria-label="Your name" />
              <button className="btn accent" disabled={busy || !name.trim() || !dirty} onClick={() => { setPlannerName(name); submit(); }}>{saved?.plan ? (dirty ? "Save the updated plan" : "Plan saved") : "Save plan"}</button>
            </div>
          </div>
          {res.notes.length > 0 && (
            <div className="read-notes">
              <strong>How we read your inputs</strong>
              <ul>{res.notes.map((x, i) => <li key={i}>{x}</li>)}</ul>
            </div>
          )}
          {past && chk && chk.summary.approved > 0 && <div className="guard note-warn" style={{ marginBottom: 10 }}><span aria-hidden>ⓘ</span><span>{chk.honesty} Only approved steps are checked and counted.</span></div>}
          {err && <div className="guard note-warn" style={{ marginBottom: 10 }}><span aria-hidden>⚠</span><span>{err}</span></div>}
          {saved?.plan && dirty && <p className="small" style={{ color: "var(--coral)", marginTop: 0 }}>The plan has changed since it was saved. Approving a step saves the new version first.</p>}
          <ol className="timeline">
            {actions.map((a) => (
              <Step key={a.id + (saved?.plan?.n ?? 0)} a={a} edit={saved?.edits[a.id]} decision={dirty ? undefined : saved?.decisions[a.id]} canDecide={!!name.trim()} busy={busy}
                    onDecide={(ev, x) => decide(a, ev, x)} chk={past ? chkBy[a.id] : undefined} />
            ))}
          </ol>
          {!name.trim() && <p className="small muted">Enter your name above to approve, skip or change steps. It is kept on this device.</p>}
          <p className="small muted">Savings compare this plan with how the hotel ran on matched days last year (same month, same kind of day, similar cooling load), at today's tariff. Plan savings are counted separately from the waste alerts.
            {site !== "GGN" && ` ${SITE_NAME[site]} has no chilled-water setpoint meter or per-chiller meters: the setpoint step is shown but never counted${res.not_counted_inr ? ` (about ${inr(res.not_counted_inr)} by the guide's rule)` : ""}, and staging is checked by total kW per TR.`}
            {res.cv_rmse_pct && ` Model accuracy (hourly CV(RMSE), leave-one-month-out on the original year): kW ${res.cv_rmse_pct.kw} %, cooling ${res.cv_rmse_pct.tr} %, peak kVA ${res.cv_rmse_pct.kva} %.`}</p>

          {risk && (site !== "GGN" || idx) && (
            <>
              <h2>Peak demand risk</h2>
              <div className={`banner compact ${risk.level === "BREACH RISK" ? "breach" : risk.level === "WARNING" ? "warn" : risk.level === "OK" ? "ok" : ""}`}>
                <div className="peak-card">
                  <Gauge value={risk.peak} max={L.cd} label={`${Math.round((risk.peak / L.cd) * 100)}%`} sub="of the limit" />
                  <div>
                    <div style={{ fontSize: 19, fontWeight: 700 }}>{HEAD[risk.level]}</div>
                    <div className="small" style={{ color: "var(--ink-2)", maxWidth: "62ch" }}>Expected peak about {n(risk.peak)} kVA around {risk.hour}:00 (limit {n(L.cd)} kVA).{" "}
                      {site !== "GGN" ? `A demand step is planned only if the forecast comes within 8 % of the limit (${n(L.warn)} kVA).`
                        : risk.stack >= 1000 ? `If laundry, water heating and banquet cooling all run that afternoon, it could reach ${n(risk.stack)} kVA.` : "Even if the flexible loads overlap it stays under the limit."}</div>
                  </div>
                </div>
              </div>
              <div className="grid g4" style={{ margin: "12px 0" }}>
                <div className="stat"><span>Expected peak</span><b>{n(risk.peak)} kVA</b><em>around {risk.hour}:00</em></div>
                <div className="stat"><span>Chance of going over {n(L.cd)} kVA</span><b>{risk.p_exceed == null ? "—" : `${Math.round(risk.p_exceed * 100)}%`}</b><em>from how past forecasts turned out</em></div>
                <div className="stat"><span>On a bad day</span><b>{n(risk.upper)} kVA</b><em>9 days out of 10 stay below this</em></div>
                {site === "GGN" && idx ? <div className="stat"><span>If flexible loads overlap</span><b style={{ color: risk.stack >= 1000 ? "var(--red)" : undefined }}>{n(risk.stack)} kVA</b><em>adds {n(idx.risk.stack_increment)} kVA</em></div>
                  : <div className="stat"><span>Demand step line</span><b>{n(L.warn)} kVA</b><em>8 % below the contract</em></div>}
              </div>
              {site === "GGN" && idx && <details className="more-info"><summary>Why: what piled up on the days the limit was broken</summary>
                <table className="t" style={{ marginTop: 8 }}>
                  <thead><tr><th>Load</th><th className="r">Drew</th><th className="r">Normally</th><th className="r">Extra</th></tr></thead>
                  <tbody>{idx.risk.stack_table.map((s) => (
                    <tr key={s.load}><td>{LOAD[s.load] ?? s.load}</td><td className="r">{n(s.actual_kw)} kW</td><td className="r">{n(s.typical_kw)} kW</td><td className="r">{n(s.extra_kw)} kW</td></tr>
                  ))}</tbody>
                </table>
                <p className="tech">Based on the {idx.risk.stack_basis}. Use "Look back" at the top to see the warning the day before each of those days.</p>
              </details>}
            </>
          )}
        </>)}
      </>)}
    </>
  );
}

/** Looking back: the forecast that was made the day before, with what happened (original year). */
function PastForecast() {
  const { now, setNow } = useClock();
  const days = useData<Record<string, ForecastDay>>("forecast_days.json");
  const [pick, setPick] = useState<string | null>(null);
  const day = pick ?? addMs(now, DAY_MS).slice(0, 10);
  const f = days?.[day];
  return (
    <>
      <div className="page-head"><div>
        <h1>Peak power demand, Gurugram</h1>
        <p className="lead">Looking back: the day-ahead forecast as it was made, next to what happened. Go back to today at the top to plan tomorrow.</p>
      </div></div>
      <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 12, flexWrap: "wrap" }}>
        <label htmlFor="fd" className="small muted">Day</label>
        <input id="fd" type="date" min="2025-10-08" max="2026-09-30" value={day} onChange={(e) => setPick(e.target.value)} style={{ padding: "6px 8px", border: "1px solid var(--rule)", borderRadius: 4 }} />
      </div>
      {!days ? <p className="muted">Loading forecast…</p> : !f ? <p className="muted">No past forecast for {fmtD(day)}. They cover 8 Oct 2025 to 30 Sep 2026.</p> : (
        <>
          <div className="grid g4" style={{ margin: "0 0 14px" }}>
            <div className="stat"><span>Forecast peak</span><b>{n(f.risk.peak)} kVA</b><em>around {f.risk.hour}:00</em></div>
            <div className="stat"><span>Actual peak</span><b>{f.actual ? `${n(Math.max(...f.actual))} kVA` : "—"}</b><em>from the meter</em></div>
            <div className="stat"><span>On a bad day</span><b>{n(f.risk.upper)} kVA</b><em>9 days out of 10 stay below this</em></div>
            <div className="stat"><span>Warning given</span><b>{HEAD[f.risk.level]}</b><em>the day before</em></div>
          </div>
          <div className="panel"><KVA hoursArr={f.hours} pred={f.pred} actual={f.actual} stack={f.risk.stack_peak} /></div>
        </>
      )}
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 18, flexWrap: "wrap" }}>
        <span className="small muted">The day before the limit was broken:</span>
        {["2026-05-12", "2026-06-18", "2026-06-25"].map((d) => (
          <button key={d} className="btn ghost" style={{ padding: "4px 10px" }} onClick={() => { setNow(`${addMs(d + "T10:00", -DAY_MS).slice(0, 10)}T10:00`); setPick(null); }}>{fmtD(d)}</button>
        ))}
      </div>
    </>
  );
}

export default function Demand() {
  const { live, now } = useClock();
  // the original year has past day-ahead forecasts; the live year has saved / suggested plans to check
  return live || now >= "2026-10-02" ? <TomorrowPlan /> : <PastForecast />;
}
