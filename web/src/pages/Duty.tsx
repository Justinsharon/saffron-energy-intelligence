// The duty engineer's pages, phone first. Today: the steps the chief engineer approved for today (mark each "Done" or "Can't do", logged
// with name and time in the same plans log), then the open problems, most costly first. Needs attention: the full alert list.
// Recommend only: nothing here switches equipment; marking a step done records that a person did it.
import { useEffect, useMemo, useState } from "react";
import { useClock } from "../App";
import { Ticket, type Ack } from "../components/parts";
import { SITES, SITE_NAME, type Alert, type Site } from "../data";
import { useFeeds } from "../feed";
import { useDayCheck } from "../dayCheck";
import { visibleAlerts } from "../feedcore";
import { fmtD, fmtDT, inr, iso, parse } from "../format";
import { TAG } from "../plan";
import { type PlanView, type SavedAction } from "../planlog";
import { loadPlan, plannerName, postPlan, setPlannerName } from "../planStore";
import { useHotel } from "../views";
import { HotelCard, loadAcks, saveAcks, SiteSwitch } from "./Shift";
import { useWeather } from "../live";

const hourOf = (t: string) => Number(t.slice(0, 2)) + (t.includes("next day") ? 24 : 0);
const t1 = (x: string) => x.replace(" (next day)", "⁺¹");
const costOf = (a: Alert) => (a.cost_basis === "per_day" ? a.per_day : a.cost);

function useAcks() {
  const [acks, setAcks] = useState<Record<string, Ack>>(loadAcks);
  useEffect(() => saveAcks(acks), [acks]);
  return [acks, (x: Ack) => setAcks((a) => ({ ...a, [x.id]: x }))] as const;
}

/** Open problems at a hotel (or all), most costly first, plus resolved in the last 24 h. Plan deviations come from the day's plan check. */
function useOpen(site: Site | "ALL") {
  const { now, live } = useClock();
  const feeds = useFeeds(now, live);
  const dc = useDayCheck(now, site === "ALL" ? "GGN" : site);
  return useMemo(() => {
    if (!feeds) return null;
    const dayAgo = iso(new Date(parse(now).getTime() - 864e5));
    const dev = visibleAlerts(dc?.check?.alerts ?? [], now).filter((a) => a.ongoing || a.end > dayAgo);
    const all = [...SITES.flatMap((s) => feeds.feeds[s].recent_alerts), ...dev].filter((a) => site === "ALL" || a.site === site);
    const open = all.filter((a) => a.ongoing && a.channel === "Alert").sort((x, y) => costOf(y) - costOf(x));
    const closed = all.filter((a) => a.channel === "Alert" && !a.ongoing && a.end > dayAgo);
    const digest = all.filter((a) => a.channel === "Daily digest" && a.alert_time <= now && a.alert_time > dayAgo);
    // every hotel's open alerts and ₹ a day at risk, for the hotel cards (whatever hotel is picked)
    const every = SITES.flatMap((s) => feeds.feeds[s].recent_alerts).filter((a) => a.ongoing && a.channel === "Alert");
    const perSite = Object.fromEntries(SITES.map((s) => { const xs = every.filter((a) => a.site === s);
      return [s, { open: xs.length, stake: xs.filter((a) => a.cost_basis === "per_day").reduce((x, a) => x + a.per_day, 0) }]; })) as Record<Site, { open: number; stake: number }>;
    return { open, closed, digest, perSite, feeds, faults: SITES.filter((s) => site === "ALL" || s === site).flatMap((s) => feeds.feeds[s].faults_now),
             updated: feeds.updated, stake: open.filter((a) => a.cost_basis === "per_day").reduce((s, a) => s + a.per_day, 0) };
  }, [feeds, dc, now, site]);
}

/** One approved step: time, equipment, setting, safety note; Done or Can't do (with a reason), logged. */
function DutyStep({ a, rep, now, busy, onReport }: { a: SavedAction; rep?: PlanView["duty"][string]; now: number; busy: boolean;
  onReport: (ev: "done" | "cant", reason?: string) => void }) {
  const [cant, setCant] = useState(false);
  const [reason, setReason] = useState("");
  const on = hourOf(a.start) <= now && now < hourOf(a.end);
  const st = rep?.event === "done" ? "ok" : rep?.event === "cant" ? "skip" : "";
  return (
    <li className={`step duty-step ${st}`}>
      <div className="stime"><b>{t1(a.start)}</b><span>to {t1(a.end)}</span>{on && <em className="now">now</em>}</div>
      <div className="body">
        <div className="row1"><span className="tag">{TAG[a.group]}</span><strong>{a.setting}</strong></div>
        <div className="small muted">{a.equipment}</div>
        <div className="guard small"><span aria-hidden>🛡</span><span>{a.guardrail}</span></div>
        {rep && <div className={`small status ${st}`}>{rep.event === "done" ? `Done: ${rep.by} at ${rep.at.slice(11)}` : `Can't do: ${rep.reason} (${rep.by} at ${rep.at.slice(11)})`}</div>}
        <div className="btn-row duty-btns">
          <button className="btn big" disabled={busy || rep?.event === "done"} onClick={() => onReport("done")}>Done</button>
          <button className="btn ghost big" disabled={busy} aria-pressed={cant} onClick={() => setCant(!cant)}>Can't do…</button>
        </div>
        {cant && (
          <div className="inline-form">
            <input value={reason} onChange={(x) => setReason(x.target.value)} placeholder="Why not? (needed for the log)" aria-label="Why it can't be done" />
            <button className="btn" disabled={busy || !reason.trim()} onClick={() => { onReport("cant", reason); setCant(false); }}>Save</button>
          </div>
        )}
      </div>
    </li>
  );
}

/** Today's steps from the approved plan for the hotel. With no approved step, nothing to act on. */
function ApprovedToday({ site }: { site: Site }) {
  const { now } = useClock();
  const date = now.slice(0, 10);
  const [v, setV] = useState<PlanView | null | undefined>(undefined);
  const [name, setName] = useState(plannerName());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => { let on = true; setV(undefined); loadPlan(date, site).then((x) => on && setV(x)).catch(() => on && setV(null)); return () => { on = false; }; }, [date, site]);
  const steps = useMemo(() => {
    if (!v?.plan) return [];
    return v.plan.actions.filter((a) => v.decisions[a.id]?.event === "approve")
      .map((a) => ({ ...a, start: v.edits[a.id]?.start ?? a.start, end: v.edits[a.id]?.end ?? a.end }))
      .sort((x, y) => hourOf(x.start) - hourOf(y.start));
  }, [v]);
  const h = Number(now.slice(11, 13));
  async function report(a: SavedAction, ev: "done" | "cant", reason?: string) {
    if (!name.trim()) { setErr("Enter your name first: every report is logged with who made it."); return; }
    setPlannerName(name); setBusy(true); setErr("");
    try { setV(await postPlan({ date, site, by: name.trim(), event: ev, action_id: a.id, reason })); }
    catch (e) { setErr(String((e as Error).message ?? e)); }
    finally { setBusy(false); }
  }
  const done = steps.filter((a) => v?.duty[a.id]?.event === "done").length;
  return (
    <section className="duty-plan">
      <div className="section-title" style={{ marginTop: 0 }}><h2>Today's plan from the chief engineer</h2></div>
      {v === undefined ? <p className="muted">Loading today's plan…</p> : !steps.length ? (
        <div className="panel flat"><p style={{ margin: 0 }}><strong>No plan approved for today; ask the chief engineer.</strong></p></div>
      ) : (
        <>
          <p className="small" style={{ margin: "0 0 8px" }}><strong>{done} of {steps.length} done</strong> · approved by {v!.decisions[steps[0].id].by}{v!.storage === "device" ? " (this device only)" : ""}
            {v!.plan!.inputs.notes ? <> · <strong>Notes:</strong> {v!.plan!.inputs.notes}</> : null}</p>
          <label className="field duty-name"><span className="small muted">Your name (kept on this device)</span>
            <input value={name} onChange={(e) => setName(e.target.value)} onBlur={() => name.trim() && setPlannerName(name)} placeholder="Your name" /></label>
          {err && <div className="guard note-warn" style={{ margin: "8px 0" }}><span aria-hidden>⚠</span><span>{err}</span></div>}
          <ol className="timeline">
            {steps.map((a) => <DutyStep key={a.id} a={a} rep={v!.duty?.[a.id]} now={h} busy={busy} onReport={(ev, r) => report(a, ev, r)} />)}
          </ol>
        </>
      )}
    </section>
  );
}

export function DutyToday() {
  const { now, go, live } = useClock();
  const { hotel: site, setHotel } = useHotel();
  const o = useOpen(site);
  const wx = useWeather();
  const [acks, ack] = useAcks();
  return (
    <div className="duty duty-wide">
      <div className="page-head">
        <div>
          <h1 style={{ fontSize: 22 }}>Today at {SITE_NAME[site]}</h1>
          <p className="lead">{fmtD(now.slice(0, 10))}, {now.slice(11, 16)}. The plan first, then the problems, most costly first.</p>
        </div>
        <SiteSwitch value={site} onChange={(s) => s !== "ALL" && setHotel(s)} all={false} />
      </div>
      <div className="duty-grid">
      <div className="duty-main">
      <ApprovedToday site={site} />

      <div className="section-title" id="attention"><h2>Needs attention</h2>
        {o && o.open.length > 0 && <span className="small muted">{inr(o.stake)} a day at risk</span>}</div>
      {o?.faults.map((f) => (
        <div key={f.start + f.kind} className="guard note-warn" style={{ marginBottom: 12 }}>
          <span aria-hidden>⚠</span><span><strong>The main meter is sending bad readings since {fmtDT(f.start)}.</strong> Those hours are ignored, so no false alerts.</span>
        </div>
      ))}
      {!o ? <p className="muted">Checking the hotel…</p> : o.open.length === 0 ? <div className="panel flat"><p style={{ margin: 0 }}>All clear: nothing needs attention at {SITE_NAME[site]} right now.</p></div>
        : o.open.map((a, i) => <Ticket key={a.id} a={a} now={now} defaultOpen={i === 0} acked={acks[a.id]} onAck={ack} />)}

      </div>
      <aside className="duty-side" aria-label="Hotels">
        <div className="section-title" style={{ marginTop: 0 }}><h2>Hotels</h2></div>
        <div className="duty-hotels">
          {SITES.map((s) => <HotelCard key={s} s={s} feed={o?.feeds.feeds[s]} temp={live ? wx?.now[s] : undefined} open={o?.perSite[s].open ?? 0}
                                        atStake={o?.perSite[s].stake ?? 0} pressed={site === s} onClick={() => setHotel(s)} />)}
        </div>
        <button className="panel flat shortcut" onClick={() => go("equipment")}>
          <span><strong>Equipment at {SITE_NAME[site]}</strong><br /><span className="small muted">{o && o.open.length ? `${o.open.length} open ${o.open.length === 1 ? "issue" : "issues"}: repeat problems and patterns` : "Repeat problems and patterns"}</span></span>
          <span aria-hidden>→</span>
        </button>
      </aside>
      </div>
    </div>
  );
}

/** Every open problem (filter by hotel), resolved in the last 24 hours, and the small items for the morning summary. */
export function Attention() {
  const { now } = useClock();
  const [site, setSite] = useState<Site | "ALL">("ALL");
  const o = useOpen(site);
  const [acks, ack] = useAcks();
  return (
    <div className="duty attention-wide">
      <div className="page-head">
        <div>
          <h1 style={{ fontSize: 22 }}>Needs attention</h1>
          <p className="lead">{!o ? "Checking the hotels…" : o.open.length === 0 ? "Nothing needs attention right now." : `${o.open.length} open ${o.open.length === 1 ? "problem" : "problems"}, about ${inr(o.stake)} a day. Most costly first.`}</p>
        </div>
        <SiteSwitch value={site} onChange={setSite} />
      </div>
      {o && o.open.map((a, i) => <Ticket key={a.id} a={a} now={now} defaultOpen={i === 0} acked={acks[a.id]} onAck={ack} />)}
      {o && o.closed.length > 0 && (<>
        <div className="section-title"><h2>Resolved in the last 24 hours</h2></div>
        {o.closed.map((a) => <Ticket key={a.id} a={a} acked={acks[a.id]} />)}
      </>)}
      {o && o.digest.length > 0 && (<>
        <div className="section-title"><h2>Morning summary</h2></div>
        <p className="muted small" style={{ marginTop: -4 }}>Small items from the last 24 hours; they go to the department heads in the morning.</p>
        {o.digest.map((a) => <Ticket key={a.id} a={a} />)}
      </>)}
    </div>
  );
}
