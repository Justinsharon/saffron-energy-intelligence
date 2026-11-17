// Today page: alerts raised by the plan check on the Plant Room's SIMULATED readings, shown as normal costed alert cards with a tag.
// Appears only while a Plant Room session exists for today or tomorrow. Never feeds savings, bills or the alert totals.
import { useState } from "react";
import { Ticket } from "../components/parts";
import { plannerName, setPlannerName } from "../planStore";
import { postPlant, usePlantLink } from "./client";
import { hhmm } from "./store";

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"], MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const label = (d: string) => { const x = new Date(`${d}T00:00:00Z`); return `${DOW[x.getUTCDay()]} ${x.getUTCDate()} ${MON[x.getUTCMonth()]}`; };

export default function PlantAlerts() {
  const link = usePlantLink();
  const [fixMsg, setFixMsg] = useState("");
  if (!link) return null;
  // the duty engineer's fix on site, logged with their name in the simulator's audit log; the meters follow at the next reading
  async function fixed() {
    const by = plannerName() || (window.prompt("Your name (for the log)") ?? "").trim();
    if (!by) return;
    setPlannerName(by);
    const r = await postPlant({ date: link!.view.date, event: "clearFault", by, simHour: link!.view.readings?.simHour ?? 0 }).catch((e) => ({ error: String(e) }));
    setFixMsg("error" in r && r.error ? r.error : `Logged: fixed on site by ${by}. The alert clears with the next meter reading.`);
  }
  const { view, check } = link;
  const sim = view.readings ? hhmm(view.readings.simHour) : null;
  return (
    <section className="card plant-link" data-testid="plant-alerts" aria-live="polite">
      <div className="plant-link-head">
        <span className="plant-tag">From Plant Room simulation</span>
        <span className="small muted">Gurugram · {label(view.date)}{sim ? ` · sim time ${sim}` : ""} · checked {check ? (check.path === "api" ? `by the plan API (${check.ms} ms)` : "in the browser (plan API unavailable)") : "…"}</span>
      </div>
      {check && check.alerts.length === 0 && <p className="small" style={{ margin: "6px 0 0" }} data-testid="plant-no-alert">No problems in the simulated readings: the plant follows the approved plan.</p>}
      {check?.alerts.map((a) => (
        <div key={a.id} className="plant-alert" data-testid="plant-alert">
          {/* ₹ a day while it continues = the check's ₹ per deviating hour × 24 (the cost so far is in the card's details) */}
          <Ticket a={{ ...a, cost_basis: "per_day", per_day: Math.round(a.per_hour * 24), channel: "Alert" }} now={a.end} defaultOpen={false} />
        </div>
      ))}
      {!!check?.alerts.length && view.faults.some((f) => f.fixedAt === undefined) && (
        <div className="btn-row" style={{ marginTop: 8, alignItems: "center" }}>
          <button className="btn" onClick={fixed} data-testid="plant-fixed">Fixed on site</button>
          <span className="small muted">Duty engineer: press when the equipment has been put right (logged with your name).</span>
        </div>
      )}
      {fixMsg && <p className="small" style={{ margin: "6px 0 0" }}>{fixMsg}</p>}
      <p className="small muted" style={{ margin: "6px 0 0" }}>Simulated readings for the demo: they never feed savings, bills or the alert totals.</p>
    </section>
  );
}
