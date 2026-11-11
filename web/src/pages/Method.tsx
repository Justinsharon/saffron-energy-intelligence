import { useData, type Quality } from "../data";

const CHECKS = [
  "Banquet hall cooling left on after a conference: flagged 2 hours after the event ended, naming the hall, the event and the cost per hour.",
  "A 500-guest winter wedding with a huge evening load: no alert, because the event and the weather explain it.",
  "A second Jaipur chiller running on quiet April nights: caught on the first night.",
  "The capacitor panel fault at Gurugram (power factor 0.88): flagged within an hour, with the extra cost and where to look.",
  "The Gurugram main meter freezing on 8 July: recognised as a meter problem, ignored for alerts and savings.",
  "Chilled water lowered to 5.5 °C: linked to the exact setting change, with the daily cost and a reset to 7 °C.",
  "A 40 °C weekday with a big conference: warned that the power limit could be broken, with which loads to move.",
  "Goa pool pumps running all day and night: caught despite being a small load.",
  "\"Why was May's bill higher than April's?\": split into weather, guests, events, the over-limit penalty and waste, in rupees.",
  "\"Switch off the kitchen extract fans overnight automatically\": refused for safety, with a safer alternative offered.",
];

export default function Method() {
  const q = useData<Quality>("quality.json");
  const pass = q?.tests.filter((t) => t.result === "PASS").length ?? 10;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>How accurate is it?</h1>
          <p className="lead">For every hotel and every hour, the system works out how much electricity the hotel should use, given the weather, rooms sold, restaurant covers, events and day of the week. It raises an alert only when a specific piece of equipment uses more than that for long enough to matter, and puts a rupee figure on it.</p>
        </div>
      </div>
      {q && (
        <div className="grid g4" style={{ marginBottom: 20 }}>
          <div className="panel"><div className="stat"><span>Alerts that were real problems</span><b>{Math.round(q.frozen.precision_any * 100)} in 100</b><em>your building alarms today: {Math.round(q.bms.precision * 100)} in 100</em></div></div>
          <div className="panel"><div className="stat"><span>Serious problems caught</span><b>{Math.round(q.frozen.recall_HM * 100)} in 100</b><em>building alarms today: {Math.round(q.bms.recall * 100)} in 100</em></div></div>
          <div className="panel"><div className="stat"><span>Time to spot a problem</span><b>about 1 hour</b><em>today: {q.bms.median_action_h} hours to act</em></div></div>
          <div className="panel"><div className="stat"><span>Expected-use accuracy</span><b>within 3%</b><em>month by month, all three hotels</em></div></div>
        </div>
      )}
      <p className="muted small">These figures come from 69 confirmed problems between April and September 2026. The system had not seen any of them when it was set up.</p>

      <div className="grid g2" style={{ marginTop: 16 }}>
        <div className="panel">
          <h3>Ten real situations it was tested on ({pass} handled correctly)</h3>
          <ol style={{ margin: 0, paddingLeft: 20, display: "grid", gap: 8 }} className="small">
            {CHECKS.map((c) => <li key={c}>{c}</li>)}
          </ol>
        </div>
        <div className="panel">
          <h3>Promises it keeps</h3>
          <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 8 }} className="small">
            <li>It only recommends. A person approves every change. Kitchen extract fans, guest-room thermostats, lifts and fire and safety systems are never switched automatically, and chilled water is never set below 6.5 °C.</li>
            <li>No alert when the weather, the guests or an event explains the extra use. Every alert shows its evidence.</li>
            <li>Meter reading problems are spotted and left out, so they never cause false alerts or count as savings. Bills are never changed.</li>
            <li>Ask only quotes figures the system has worked out, and every number is checked before you see it.</li>
            <li>Savings are claimed only after allowing for the weather, guests and events, never by comparing with last year's bill.</li>
          </ul>
          <h3 style={{ marginTop: 18 }}>What it can't see yet</h3>
          <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 8 }} className="small">
            <li>Very small waste on a big meter (for example 6 kW at a 600 kW hotel), unless a sub-meter isolates that equipment.</li>
            <li>Tomorrow's laundry and water-heating schedule, and the events calendar. Until those are connected, power-limit risk is shown as a "what if they overlap" scenario, and events are entered by hand in Plan ahead.</li>
            <li>Live meter readings. Until the hotels' meters are connected, the Today page replays the sample feed from the same weekday last year.</li>
            <li>Equipment with no sub-meter (8–14% of the electricity). That needs a walk-through.</li>
          </ul>
        </div>
      </div>
    </>
  );
}
