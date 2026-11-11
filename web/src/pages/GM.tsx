import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useClock } from "../App";
import { Waterfall } from "../components/parts";
import { SITE_NAME, useData, type Alert, type BillChange, type Bills, type Site } from "../data";
import { fmtMonth, inr, n } from "../format";
import { SiteSwitch } from "./Shift";
import { DRIVER } from "../copy";

const COMP_COLORS: Record<string, string> = {
  "Energy (kVAh)": "#151515", "Demand charge": "#a8a8a8", "Excess-demand penalty": "#c93a1c", "Fuel surcharge": "#9b9b9b",
  "Electricity duty": "#c4c4c4", "Municipal tax": "#dcdcdc", "ToD net": "#e8613c", "Diesel (DG)": "#7d64a8",
};

const COMP_NAME: Record<string, string> = {
  "Energy (kVAh)": "Energy", "Demand charge": "Peak-demand charge", "Excess-demand penalty": "Over-limit penalty", "Fuel surcharge": "Fuel surcharge",
  "Electricity duty": "Electricity duty", "Municipal tax": "Municipal tax", "ToD net": "Time-of-day adjustment", "Diesel (DG)": "Diesel generator",
};

function sentence(group: string, v: number, c: BillChange["context"], d: BillChange): string {
  const s = `${v >= 0 ? "added" : "saved"} ${inr(Math.abs(v))}`;
  switch (group) {
    case "Weather": return `Hotter or cooler weather ${s}. The hottest hour went from ${c.tmax_A.toFixed(0)} °C to ${c.tmax_B.toFixed(0)} °C, and the hotel needed ${c.cdh_B > c.cdh_A ? `${(c.cdh_B / Math.max(c.cdh_A, 1)).toFixed(1)}× as much` : "less"} cooling.`;
    case "Occupancy": return `Guests ${s}: rooms sold went from ${n(c.rooms_A)} to ${n(c.rooms_B)} room-nights.`;
    case "Events": return `Events ${s}: event guests went from ${n(c.event_guests_A)} to ${n(c.event_guests_B)}.`;
    case "Demand": return `Peak-demand charges ${s}. The month's highest power draw went from ${n(c.md_A)} to ${n(c.md_B)} kVA${c.md_B > 1000 ? ", over the 1,000 kVA contract, which triggered a penalty" : ""}.`;
    case "Anomalies": return `Equipment waste and faults ${s}${Math.abs(c.pf_B - c.pf_A) > 0.01 ? `, mostly from the capacitor panel fault that raised the bill by about ${Math.abs((1 / c.pf_B - 1 / c.pf_A) * c.pf_A * 100).toFixed(0)}%` : ""}.`;
    case "Calendar": return `The number of days in the month ${s}.`;
    case "Diesel": return `Running the diesel generator ${s}; diesel power costs about three times grid power.`;
    case "Tariff mix": return `Using more or less power in the expensive evening hours ${s}.`;
    default: return `About ${inr(Math.abs(v))} (${Math.abs(v / d.bill_a * 100).toFixed(1)}% of the bill) is not explained by weather, guests, events or known waste.`;
  }
}

function addMonth(m: string) { const [y, mo] = m.split("-").map(Number); return mo === 12 ? `${y + 1}-01` : `${y}-${String(mo + 1).padStart(2, "0")}`; }

export default function GM() {
  const { now } = useClock();
  const bills = useData<Bills>("bills.json");
  const changes = useData<Record<string, BillChange>>("bill_changes.json");
  const alerts = useData<Alert[]>("alerts.json");
  const [site, setSite] = useState<Site>("GGN");
  const months = useMemo(() => bills ? bills.recon.filter((r) => r.site === site).map((r) => r.month).sort() : [], [bills, site]);
  const nowM = now.slice(0, 7);
  const lastM = months[months.length - 1];
  const pending = !!lastM && nowM > lastM;
  const defB = months.includes(nowM) && months.indexOf(nowM) > 0 ? nowM : pending ? lastM : "2026-05";
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
          <h1>Why the electricity bill changed</h1>
          <p className="lead">Pick two months to see where the difference came from: weather, guests, events, wasted energy, peak-demand charges or the diesel generator. The pieces add up exactly to the two bills.{pending ? ` The latest bill is ${fmtMonth(lastM)}; bills from ${fmtMonth(addMonth(lastM))} onward have not been received yet.` : ""}</p>
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
                       steps={steps.map(([k, v]) => ({ label: DRIVER[k] ?? k, value: v }))} />
          </div>
          <div>
            <p style={{ fontSize: 19, lineHeight: 1.4, margin: "4px 0 12px" }}>
              {SITE_NAME[site]}'s {fmtMonth(y)} bill was <strong>{inr(ch.bill_b)}</strong>, {inr(Math.abs(ch.delta))} {ch.delta >= 0 ? "more" : "less"} than {fmtMonth(x)}.
            </p>
            <ol style={{ paddingLeft: 20, margin: 0, display: "grid", gap: 8 }}>
              {steps.slice(0, 4).map(([k, v]) => <li key={k}>{sentence(k, v, ch.context, ch)}</li>)}
            </ol>
            <p className="muted small">Waste spotted in {fmtMonth(y)}: {inr(waste)}. For more detail on any line, use Ask.</p>
          </div>
        </div>
      )}

      <h2>The last twelve bills, {SITE_NAME[site]}</h2>
      <div className="panel">
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={monthly} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
            <CartesianGrid stroke="#efefef" vertical={false} />
            <XAxis dataKey="month" tick={{ fontSize: 11, fill: "#9b9b9b" }} />
            <YAxis tickFormatter={(v) => inr(v)} tick={{ fontSize: 11, fill: "#9b9b9b" }} width={70} />
            <Tooltip formatter={(v: number) => inr(v, { exact: true })} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {Object.keys(COMP_COLORS).map((k) => <Bar key={k} dataKey={k} name={COMP_NAME[k]} stackId="b" fill={COMP_COLORS[k]} isAnimationActive={false} />)}
          </BarChart>
        </ResponsiveContainer>
        <p className="muted small" style={{ marginBottom: 0 }}>About 80% of every bill is the energy charge, so using less, and keeping the capacitor panel healthy, matters most.</p>
      </div>
    </>
  );
}
