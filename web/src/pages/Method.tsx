import { useData, type Quality } from "../data";
import { pct } from "../format";

export default function Method() {
  const q = useData<Quality>("quality.json");
  return (
    <>
      <div className="page-head">
        <div>
          <h1>How it works, and how well</h1>
          <p className="lead">For each hotel a baseline model predicts what every hour should use, given the weather, rooms sold, restaurant covers, the events calendar and the day of the week. Alerts fire only where load departs from that, on a named piece of equipment, for long enough to matter.</p>
        </div>
      </div>
      {q && (
        <div className="grid g2">
          <div className="panel">
            <h3>Results against the brief's targets</h3>
            <table className="t">
              <thead><tr><th>Measure</th><th className="r">Target</th><th className="r">Result</th></tr></thead>
              <tbody>
                <tr><td>Alerts that are real waste</td><td className="r">≥ 70%</td><td className="r"><strong>{pct(q.frozen.precision_any, 1)}</strong></td></tr>
                <tr><td>High + Medium waste caught</td><td className="r">≥ 75%</td><td className="r"><strong>{pct(q.frozen.recall_HM, 1)}</strong></td></tr>
                <tr><td>Time to detect, High</td><td className="r">&lt; 2 h</td><td className="r"><strong>1.0 h</strong></td></tr>
                <tr><td>Baseline error, hourly / monthly</td><td className="r">&lt; 30% / 15%</td><td className="r"><strong>5–8% / 1–3%</strong></td></tr>
                <tr><td>Day-ahead peak, mean error</td><td className="r">± 5%</td><td className="r"><strong>{q.forecast.mape}%</strong></td></tr>
                <tr><td>Identified savings</td><td className="r">8–12%</td><td className="r"><strong>5.9%</strong> (7.1% with capital)</td></tr>
                <tr><td>Engineer trust</td><td className="r">≥ 4 / 5</td><td className="r">pending real raters</td></tr>
              </tbody>
            </table>
            <p className="muted small">Scored on {q.frozen.n_labels} labelled anomalies from 1 Apr 2026, after the detector was frozen on earlier months. Including the three rules added later (contract demand, EV charger, kW/TR staging): {pct(q.full.precision_any, 1)} precision, {pct(q.full.recall_HM, 0)} recall — post-hoc, not a clean test.</p>
          </div>
          <div className="panel">
            <h3>Acceptance scenarios</h3>
            <table className="t"><tbody>{q.tests.map((t) => (
              <tr key={t.id}><td><strong>{t.id}</strong></td><td><span className={`chip ${t.result === "PASS" ? "c-ok" : "c-med"}`}>{t.result === "PASS" ? "Pass" : "Check"}</span></td><td className="small">{t.detail}</td></tr>
            ))}</tbody></table>
          </div>
        </div>
      )}
      <div className="panel" style={{ marginTop: 16 }}>
        <h3>Rules the product keeps</h3>
        <ul style={{ margin: 0, paddingLeft: 18 }}>
          <li>It recommends; a person approves every action. Kitchen exhaust, guest-room thermostats, lifts and life-safety systems are never automated, and the chilled-water setpoint is never taken below 6.5 °C.</li>
          <li>No alert for load that weather, bookings or events explain. Every alert shows its evidence.</li>
          <li>Meter data faults are flagged and kept out of alerts and savings. Bills are never altered.</li>
          <li>The assistant only repeats numbers the models produced; an answer with an unverified number is replaced.</li>
          <li>Savings are claimed only against an adjusted baseline (IPMVP Option C), never against last year's bill.</li>
        </ul>
        <h3 style={{ marginTop: 16 }}>What it cannot see</h3>
        <ul style={{ margin: 0, paddingLeft: 18 }}>
          <li>Faults smaller than the noise of the meter they sit on (for example 6 kW on a 600 kW hotel meter) unless a sub-meter isolates them.</li>
          <li>Next-day laundry and water-heating schedules, so demand breaches show as a stacking scenario rather than a forecast.</li>
          <li>The unmetered "other" load (8–14% of energy); that needs a walk-through audit.</li>
        </ul>
      </div>
    </>
  );
}
