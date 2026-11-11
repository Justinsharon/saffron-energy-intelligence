import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useClock } from "../App";
import { Waterfall } from "../components/parts";
import { SITE_NAME, useData, type Alert, type BillChange, type Bills, type Site } from "../data";
import { fmtMonth, inr, n } from "../format";
import { SiteSwitch } from "./Shift";

const COMP_COLORS: Record<string, string> = {
  "Energy (kVAh)": "#22323d", "Demand charge": "#2b6c8f", "Excess-demand penalty": "#c4351f", "Fuel surcharge": "#7b8792",
  "Electricity duty": "#a9b4bb", "Municipal tax": "#cdd5d9", "ToD net": "#e3a23b", "Diesel (DG)": "#6b4c9a",
};

function sentence(group: string, v: number, c: BillChange["context"], d: BillChange): string {
  const s = `${v >= 0 ? "added" : "saved"} ${inr(Math.abs(v))}`;
  switch (group) {
    case "Weather": return `Weather ${s}: cooling degree-hours went from ${n(c.cdh_A)} to ${n(c.cdh_B)} and the hottest hour from ${c.tmax_A.toFixed(1)} to ${c.tmax_B.toFixed(1)} °C.`;
    case "Occupancy": return `Occupancy ${s}: room-nights sold went from ${n(c.rooms_A)} to ${n(c.rooms_B)}.`;
    case "Events": return `Events ${s}: event guests went from ${n(c.event_guests_A)} to ${n(c.event_guests_B)}.`;
    case "Demand": return `Demand charges ${s}: the month's peak went from ${n(c.md_A)} to ${n(c.md_B)} kVA${c.md_B > 1000 ? ", above the 1,000 kVA contract, so a penalty applied" : ""}.`;
    case "Anomalies": return `Waste and faults ${s}, including the power factor moving from ${c.pf_A.toFixed(3)} to ${c.pf_B.toFixed(3)}.`;
    case "Calendar": return `The calendar ${s} (days in the month and weekday mix).`;
    case "Diesel": return `Diesel generator hours ${s}.`;
    case "Tariff mix": return `Peak and off-peak timing ${s}.`;
    default: return `Unexplained by the model: ${inr(v)} (about ${Math.abs(v / d.bill_a * 100).toFixed(1)}% of the bill).`;
  }
}

export default function GM() {
  const { now } = useClock();
  const bills = useData<Bills>("bills.json");
  const changes = useData<Record<string, BillChange>>("bill_changes.json");
  const alerts = useData<Alert[]>("alerts.json");
  const [site, setSite] = useState<Site>("GGN");
  const months = useMemo(() => bills ? bills.recon.filter((r) => r.site === site).map((r) => r.month).sort() : [], [bills, site]);
  const nowM = now.slice(0, 7);
  const defB = months.includes(nowM) && months.indexOf(nowM) > 0 ? nowM : "2026-05";
  const [b, setB] = useState(defB);
  const [a, setA] = useState(months[months.indexOf(defB) - 1] ?? "2026-04");
  useEffect(() => { setB(defB); setA(months[months.indexOf(defB) - 1] ?? "2026-04"); }, [site, nowM, months.length]);
  const [x, y] = a < b ? [a, b] : [b, a];
  const ch = changes?.[`${site}|${x}|${y}`];

  const monthly = useMemo(() => {
    if (!bills) return [];
    const rows: Record<string, Record<string, number | string>> = {};
    for (const r of bills.components[site]) {
      rows[r.billing_month] ??= { month: r.billing_month.slice(2).replace("-", "/") };
      rows[r.billing_month][r.component] = r.inr;
    }
    return Object.keys(rows).sort().map((k) => rows[k]);
  }, [bills, site]);
  const waste = useMemo(() => alerts ? alerts.filter((q) => q.site === site && q.start.slice(0, 7) === y).reduce((s, q) => s + q.cost, 0) : 0, [alerts, site, y]);
  const steps = ch ? Object.entries(ch.groups).filter(([, v]) => Math.abs(v) >= 1).sort((p, q) => Math.abs(q[1]) - Math.abs(p[1])) : [];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Why the bill moved</h1>
          <p className="lead">Each change is split by the hotel's own baseline model: what weather, bookings and events explain, and what is waste, demand or diesel. The pieces add up to the two issued bills exactly.</p>
        </div>
        <SiteSwitch value={site} onChange={(s) => setSite(s as Site)} all={false} />
      </div>

      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
        <span className="small muted">Compare</span>
        <select value={a} onChange={(e) => setA(e.target.value)} style={{ padding: "6px 8px", border: "1px solid var(--rule)", borderRadius: 4 }}>
          {months.map((m) => <option key={m} value={m}>{fmtMonth(m)}</option>)}
        </select>
        <span className="small muted">with</span>
        <select value={b} onChange={(e) => setB(e.target.value)} style={{ padding: "6px 8px", border: "1px solid var(--rule)", borderRadius: 4 }}>
          {months.map((m) => <option key={m} value={m}>{fmtMonth(m)}</option>)}
        </select>
      </div>

      {x === y ? <p className="muted">Pick two different months.</p> : !ch ? <p className="muted">Loading…</p> : (
        <div className="split">
          <div className="panel">
            <Waterfall start={ch.bill_a} end={ch.bill_b} startLabel={fmtMonth(x)} endLabel={fmtMonth(y)}
                       steps={steps.map(([k, v]) => ({ label: k, value: v }))} />
          </div>
          <div>
            <p style={{ fontSize: 19, lineHeight: 1.4, margin: "4px 0 12px" }}>
              {SITE_NAME[site]}'s {fmtMonth(y)} bill was <strong>{inr(ch.bill_b)}</strong>, {inr(Math.abs(ch.delta))} {ch.delta >= 0 ? "more" : "less"} than {fmtMonth(x)}.
            </p>
            <ol style={{ paddingLeft: 20, margin: 0, display: "grid", gap: 8 }}>
              {steps.slice(0, 4).map(([k, v]) => <li key={k}>{sentence(k, v, ch.context, ch)}</li>)}
            </ol>
            <p className="muted small">Waste alerts raised in {fmtMonth(y)}: {inr(waste)} flagged. Ask the assistant for detail on any line.</p>
          </div>
        </div>
      )}

      <h2>Twelve months of bills, {SITE_NAME[site]}</h2>
      <div className="panel">
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={monthly} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
            <CartesianGrid stroke="#e8ecee" vertical={false} />
            <XAxis dataKey="month" tick={{ fontSize: 11, fill: "#7b8792" }} />
            <YAxis tickFormatter={(v) => inr(v)} tick={{ fontSize: 11, fill: "#7b8792" }} width={70} />
            <Tooltip formatter={(v: number) => inr(v, { exact: true })} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {Object.keys(COMP_COLORS).map((k) => <Bar key={k} dataKey={k} stackId="b" fill={COMP_COLORS[k]} isAnimationActive={false} />)}
          </BarChart>
        </ResponsiveContainer>
        <p className="muted small" style={{ marginBottom: 0 }}>About 80% of every bill is the kVAh energy charge, which rises with load and falls with a better power factor.</p>
      </div>
    </>
  );
}
