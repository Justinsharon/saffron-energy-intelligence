import { useEffect, useMemo, useState } from "react";
import { Line, LineChart, ResponsiveContainer } from "recharts";
import { useClock } from "../App";
import { Ticket, type Ack } from "../components/parts";
import { SITES, SITE_NAME, useData, type Alert, type Fault, type ForecastDay, type Hotel, type Hourly, type Site } from "../data";
import { addMs, fmtD, fmtDT, inr, n, parse, iso } from "../format";
import { pickCell, useLiveDay, useWeather } from "../live";

/** Move an alert from the sample feed's dates to the dates on screen (no-op when looking back). */
export function shiftAlert(a: Alert, ms: number): Alert {
  if (!ms) return a;
  const f = (t: string) => addMs(t, ms);
  return { ...a, start: f(a.start), end: f(a.end), alert_time: f(a.alert_time), chart: { ...a.chart, t: a.chart.t.map((t) => f(t + ":00").slice(0, 13)) } };
}

function loadAcks(): Record<string, Ack> {
  try { return JSON.parse(localStorage.getItem("acks") || "{}"); } catch { return {}; }
}
function saveAcks(a: Record<string, Ack>) {
  try { localStorage.setItem("acks", JSON.stringify(a)); } catch { /* private window: keep in memory */ }
}

export function SiteSwitch({ value, onChange, all = true }: { value: Site | "ALL"; onChange: (s: Site | "ALL") => void; all?: boolean }) {
  return (
    <div className="seg" role="group" aria-label="Hotel">
      {all && <button aria-pressed={value === "ALL"} onClick={() => onChange("ALL")}>All hotels</button>}
      {SITES.map((s) => <button key={s} aria-pressed={value === s} onClick={() => onChange(s)}>{SITE_NAME[s]}</button>)}
    </div>
  );
}

function greeting(h: number) { return h < 5 ? "Good night" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening"; }

/** Today so far for one hotel: used vs expected, and the last 24 hours as a sparkline. */
function HotelCard({ s, now, open, atStake, pressed, onClick, temp }: { s: Site; now: string; open: number; atStake: number; pressed: boolean; onClick: () => void; temp?: number | null }) {
  const hr = useData<Hourly>(`hourly_${s}.json`);
  const hotels = useData<Record<Site, Hotel>>("hotels.json");
  const v = useMemo(() => {
    if (!hr) return null;
    const key = now.slice(0, 13);
    const end = hr.t.findIndex((t) => t > key);
    const stop = end < 0 ? hr.t.length : end;
    const dayStart = hr.t.findIndex((t) => t.slice(0, 10) === now.slice(0, 10));
    let a = 0, b = 0;
    for (let i = Math.max(dayStart, 0); i < stop; i++) { a += hr.a[i]; b += hr.b[i]; }
    const spark = [];
    for (let i = Math.max(0, stop - 24); i < stop; i++) spark.push({ a: hr.a[i], b: hr.b[i] });
    return { a, b, pct: b > 0 ? (a / b - 1) * 100 : 0, spark };
  }, [hr, now]);
  return (
    <button className="hotel" aria-pressed={pressed} onClick={onClick}>
      <div className="h-top"><span className="h-name">{SITE_NAME[s]}</span><span className="h-rooms">{temp != null ? `${Math.round(temp)} °C · ` : ""}{hotels?.[s].rooms ?? ""} rooms</span></div>
      <div className={`h-state ${open ? "bad" : "ok"}`}>{open ? `${open} ${open === 1 ? "issue needs" : "issues need"} attention` : "All clear"}</div>
      <div className="h-nums">
        <span><b>{open ? inr(atStake) : "₹0"}</b>a day at risk</span>
        <span><b>{v ? `${v.pct >= 0 ? "+" : "−"}${Math.abs(v.pct).toFixed(0)}%` : "—"}</b>today vs expected</span>
      </div>
      <div style={{ height: 38, marginTop: 2 }} aria-hidden>
        {v && <ResponsiveContainer width="100%" height="100%"><LineChart data={v.spark} margin={{ top: 4, bottom: 2, left: 0, right: 0 }}>
          <Line dataKey="b" stroke="#2b6c8f" strokeDasharray="3 3" dot={false} strokeWidth={1.2} isAnimationActive={false} />
          <Line dataKey="a" stroke={open ? "#c4351f" : "#17212a"} dot={false} strokeWidth={1.6} isAnimationActive={false} />
        </LineChart></ResponsiveContainer>}
      </div>
      <span className="small muted">Last 24 hours: used (solid) vs expected (dashed)</span>
    </button>
  );
}

export default function Shift() {
  const { now: shown, dataNow: now, offset, live, go } = useClock();
  const wx = useWeather();
  const alerts = useData<Alert[]>("alerts.json");
  const faults = useData<Fault[]>("faults.json");
  const days = useData<Record<string, ForecastDay>>("forecast_days.json");
  const [site, setSite] = useState<Site | "ALL">("ALL");
  const [acks, setAcks] = useState<Record<string, Ack>>(loadAcks);
  const [showDigest, setShowDigest] = useState(false);
  useEffect(() => saveAcks(acks), [acks]);

  const per = useMemo(() => {
    const out: Record<Site, { open: Alert[]; stake: number }> = { GGN: { open: [], stake: 0 }, JAI: { open: [], stake: 0 }, GOA: { open: [], stake: 0 } };
    for (const a of alerts ?? []) if (a.alert_time <= now && a.end > now && a.channel === "Alert") {
      out[a.site].open.push(a); if (a.cost_basis === "per_day") out[a.site].stake += a.per_day;
    }
    return out;
  }, [alerts, now]);

  const v = useMemo(() => {
    if (!alerts) return null;
    const mine = alerts.filter((a) => site === "ALL" || a.site === site);
    const open = mine.filter((a) => a.alert_time <= now && a.end > now && a.channel === "Alert")
      .sort((x, y) => (y.cost_basis === "per_day" ? y.per_day : y.cost) - (x.cost_basis === "per_day" ? x.per_day : x.cost));
    const dayAgo = iso(new Date(parse(now).getTime() - 864e5));
    const closed = mine.filter((a) => a.channel === "Alert" && a.end <= now && a.end > dayAgo);
    const digest = mine.filter((a) => a.channel === "Daily digest" && a.alert_time <= now && a.alert_time > dayAgo);
    const stake = open.filter((a) => a.cost_basis === "per_day").reduce((s, a) => s + a.per_day, 0);
    const sh = (xs: Alert[]) => xs.map((a) => shiftAlert(a, offset));
    return { open: sh(open), closed: sh(closed), digest: sh(digest), stake };
  }, [alerts, site, now, offset]);

  const tomorrow = iso(new Date(parse(shown).getTime() + 864e5)).slice(0, 10);
  const liveDay = useLiveDay(live ? tomorrow : null);
  const tmaxT = wx?.daily.GGN[tomorrow]?.tmax;
  const fc = live ? (liveDay && tmaxT != null ? pickCell(liveDay, tmaxT, 0).f : liveDay ? pickCell(liveDay, liveDay.template_tmax, 0).f : undefined) : days?.[tomorrow];
  const faultNow = faults?.filter((f) => f.start <= now && f.end > now && (site === "ALL" || f.site === site)) ?? [];
  const where = site === "ALL" ? "across the three hotels" : `at ${SITE_NAME[site]}`;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{greeting(Number(shown.slice(11, 13)))}</h1>
          <p className="lead">
            {!v ? "Checking the hotels…" : v.open.length === 0 ? `Nothing needs attention ${where} right now.` :
              <>{v.open.length} {v.open.length === 1 ? "issue is" : "issues are"} wasting about <strong>{inr(v.stake)} a day</strong> {where}. Most costly first.</>}
          </p>
          {live && <span className="feed-note">Meter readings: sample feed, replayed from {fmtD(now)}</span>}
        </div>
      </div>

      <div className="hotels">
        {SITES.map((s) => <HotelCard key={s} s={s} now={now} temp={live ? wx?.now[s] : undefined} open={per[s].open.length} atStake={per[s].stake} pressed={site === s} onClick={() => setSite(site === s ? "ALL" : s)} />)}
      </div>

      {faultNow.map((f) => (
        <div key={f.start + f.kind} className="guard note-warn" style={{ marginBottom: 12 }}>
          <span aria-hidden>⚠</span>
          <span><strong>{f.hotel}: the main meter is sending bad readings since {fmtDT(addMs(f.start, offset))}.</strong> We are ignoring those hours, so no false waste alerts will appear. The bill for this month will need checking.</span>
        </div>
      ))}

      <div className="section-title">
        <h2>Needs attention{site !== "ALL" ? ` at ${SITE_NAME[site]}` : ""}</h2>
        {site !== "ALL" && <button className="btn ghost" onClick={() => setSite("ALL")}>Show all hotels</button>}
      </div>
      {v && v.open.map((a, i) => (
        <Ticket key={a.id} a={a} now={shown} defaultOpen={i === 0} acked={acks[a.id]} onAck={(x) => setAcks({ ...acks, [x.id]: x })} />
      ))}
      {v && v.open.length === 0 && (
        <div className="panel flat">
          <h3>All clear</h3>
          <p className="muted" style={{ margin: 0 }}>Every hotel is using what its weather, guests and events call for. To see how problems are shown, look back to a past day at the top right, for example 16 April 2026 at 20:00.</p>
        </div>
      )}

      {fc && site !== "JAI" && site !== "GOA" && (
        <>
          <div className="section-title"><h2>Tomorrow at Gurugram</h2></div>
          <div className={`banner ${fc.risk.level === "BREACH RISK" ? "breach" : fc.risk.level === "WARNING" ? "warn" : fc.risk.level === "OK" ? "ok" : ""}`}>
            <div>
              <strong>{fc.risk.level === "OK" ? "Power demand should stay comfortably under the limit" : fc.risk.level === "BREACH RISK" ? "Risk of going over the contracted power limit" : "Power demand will run close to the limit"}</strong>
              <span className="muted"> · {fmtD(tomorrow)}</span>
              <div className="small" style={{ color: "var(--ink-2)", marginTop: 2 }}>
                Expected peak about <strong className="num">{n(fc.risk.peak)} kVA</strong> around {fc.risk.hour}:00 (limit 1,000 kVA){live && tmaxT != null ? `, with a top of ${Math.round(tmaxT)} °C forecast` : ""}.
                {fc.risk.level === "BREACH RISK" && fc.risk.stack_peak >= 1000 && <> If laundry, water heating and banquet cooling all run that afternoon, it could reach {n(fc.risk.stack_peak)} kVA.</>}
              </div>
            </div>
            <button className="btn ghost" onClick={() => go("demand")}>See the plan</button>
          </div>
        </>
      )}

      {v && v.closed.length > 0 && (
        <>
          <div className="section-title"><h2>Resolved in the last 24 hours</h2></div>
          {v.closed.map((a) => <Ticket key={a.id} a={a} acked={acks[a.id]} />)}
        </>
      )}

      {v && (
        <>
          <div className="section-title"><h2>Morning summary</h2>
            {v.digest.length > 0 && <button className="btn ghost" onClick={() => setShowDigest(!showDigest)}>{showDigest ? "Hide" : `Show ${v.digest.length}`}</button>}</div>
          <p className="muted small" style={{ marginTop: -4 }}>Small items from the last 24 hours, such as a laundry run in the evening peak. They don't interrupt the shift; the department heads see them in the morning.</p>
          {v.digest.length === 0 && <p className="muted">Nothing to report.</p>}
          {showDigest && v.digest.map((a) => <Ticket key={a.id} a={a} />)}
        </>
      )}
    </>
  );
}
