// Today page: alerts raised by the plan check on the Plant Room's SIMULATED readings, shown as normal costed alert cards with a tag.
// Appears only while a Plant Room session exists for today or tomorrow. Never feeds savings, bills or the alert totals.
import { Ticket } from "../components/parts";
import { usePlantLink } from "./client";
import { hhmm } from "./store";

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"], MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const label = (d: string) => { const x = new Date(`${d}T00:00:00Z`); return `${DOW[x.getUTCDay()]} ${x.getUTCDate()} ${MON[x.getUTCMonth()]}`; };

export default function PlantAlerts() {
  const link = usePlantLink();
  if (!link) return null;
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
      <p className="small muted" style={{ margin: "6px 0 0" }}>Simulated readings for the demo: they never feed savings, bills or the alert totals.</p>
    </section>
  );
}
