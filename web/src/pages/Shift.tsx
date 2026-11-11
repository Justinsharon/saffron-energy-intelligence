import { useEffect, useMemo, useState } from "react";
import { useClock } from "../App";
import { Ticket, type Ack } from "../components/parts";
import { SITES, SITE_NAME, useData, type Alert, type Fault, type ForecastDay, type Site } from "../data";
import { fmtD, fmtDT, inr, n, parse, iso } from "../format";

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

export default function Shift() {
  const { now, go } = useClock();
  const alerts = useData<Alert[]>("alerts.json");
  const faults = useData<Fault[]>("faults.json");
  const days = useData<Record<string, ForecastDay>>("forecast_days.json");
  const [site, setSite] = useState<Site | "ALL">("ALL");
  const [acks, setAcks] = useState<Record<string, Ack>>(loadAcks);
  const [showDigest, setShowDigest] = useState(false);
  useEffect(() => saveAcks(acks), [acks]);

  const v = useMemo(() => {
    if (!alerts) return null;
    const mine = alerts.filter((a) => site === "ALL" || a.site === site);
    const open = mine.filter((a) => a.alert_time <= now && a.end > now && a.channel === "Alert")
      .sort((x, y) => (y.cost_basis === "per_day" ? y.per_day : y.cost) - (x.cost_basis === "per_day" ? x.per_day : x.cost));
    const dayAgo = iso(new Date(parse(now).getTime() - 864e5));
    const closed = mine.filter((a) => a.channel === "Alert" && a.end <= now && a.end > dayAgo);
    const digest = mine.filter((a) => a.channel === "Daily digest" && a.alert_time <= now && a.alert_time > dayAgo);
    const atStake = open.filter((a) => a.cost_basis === "per_day").reduce((s, a) => s + a.per_day, 0);
    return { open, closed, digest, atStake };
  }, [alerts, site, now]);

  const tomorrow = iso(new Date(parse(now).getTime() + 864e5)).slice(0, 10);
  const fc = days?.[tomorrow];
  const faultNow = faults?.filter((f) => f.start <= now && f.end > now && (site === "ALL" || f.site === site)) ?? [];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>On shift, {fmtDT(now)}</h1>
          <p className="lead">
            {v ? (v.open.length === 0 ? "Nothing needs you right now." :
              <>{v.open.length} {v.open.length === 1 ? "thing needs" : "things need"} attention, about <strong>{inr(v.atStake)} a day</strong> while they run. Largest first.</>) : "Loading alerts…"}
          </p>
        </div>
        <SiteSwitch value={site} onChange={setSite} />
      </div>

      {faultNow.map((f) => (
        <div key={f.start} className="guard note-warn" style={{ marginBottom: 12 }}>
          <span aria-hidden>⚠</span>
          <span><strong>{f.hotel} main meter: data fault since {fmtDT(f.start)}.</strong> {f.evidence}. Those hours are left out of alerts and savings; no waste alert will fire on them.</span>
        </div>
      ))}

      {v && v.open.map((a, i) => (
        <Ticket key={a.id} a={a} now={now} defaultOpen={i === 0} acked={acks[a.id]} onAck={(x) => setAcks({ ...acks, [x.id]: x })} />
      ))}
      {v && v.open.length === 0 && (
        <div className="panel flat">
          <h3>All quiet</h3>
          <p className="muted" style={{ margin: 0 }}>Load is where the weather, bookings and events say it should be. Move the clock in the top bar to replay any moment of the year, for example 16 Apr 20:00 or 13 May 10:00.</p>
        </div>
      )}

      {fc && site !== "JAI" && site !== "GOA" && (
        <>
          <h2>Tomorrow at Gurugram</h2>
          <div className={`banner ${fc.risk.level === "BREACH RISK" ? "breach" : fc.risk.level === "WARNING" ? "warn" : fc.risk.level === "OK" ? "ok" : ""}`}>
            <div>
              <strong>{fc.risk.level === "OK" ? "No demand risk" : fc.risk.level.charAt(0) + fc.risk.level.slice(1).toLowerCase()}</strong>{" "}
              <span className="muted">· {fmtD(tomorrow)}</span>
              <div className="small" style={{ color: "var(--ink-2)", marginTop: 2 }}>
                Peak about <strong className="num">{n(fc.risk.peak)} kVA</strong> at {fc.risk.hour}:00
                {fc.risk.p_exceed != null && <> · {Math.round(fc.risk.p_exceed * 100)}% chance above 1,000 kVA</>}
                {fc.risk.level !== "OK" && <> · {fc.risk.why}</>}
              </div>
            </div>
            <button className="btn ghost" onClick={() => go("demand")}>Open demand plan</button>
          </div>
        </>
      )}

      {v && v.closed.length > 0 && (
        <>
          <h2>Ended in the last 24 hours</h2>
          {v.closed.map((a) => <Ticket key={a.id} a={a} acked={acks[a.id]} />)}
        </>
      )}

      {v && (
        <>
          <h2>Daily digest</h2>
          <p className="muted small" style={{ marginTop: -4 }}>Small or schedule-only items from the last 24 hours. They do not interrupt the shift; the laundry and front-office leads see them in the morning.</p>
          {v.digest.length === 0 ? <p className="muted">Nothing in the digest.</p> : (
            <>
              <button className="btn ghost" onClick={() => setShowDigest(!showDigest)}>{showDigest ? "Hide" : "Show"} {v.digest.length} digest {v.digest.length === 1 ? "item" : "items"}</button>
              {showDigest && <div style={{ marginTop: 10 }}>{v.digest.map((a) => <Ticket key={a.id} a={a} />)}</div>}
            </>
          )}
        </>
      )}
    </>
  );
}
