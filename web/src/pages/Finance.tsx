import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ComposedChart, Line, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis, Cell, LabelList } from "recharts";
import { Status } from "../components/parts";
import { SITES, SITE_NAME, useData, type Bills, type Recon, type Savings, type Site } from "../data";
import { fmtMonth, inr, n } from "../format";
import { SiteSwitch } from "./Shift";
import { CATEGORY, CONFIDENCE, measureGroup, measureName } from "../copy";

const LINES: [string, string][] = [
  ["bill_energy_charge_inr", "Energy"], ["bill_tod_net_inr", "Time-of-day adjustment"], ["bill_demand_charge_inr", "Peak-demand charge"],
  ["bill_excess_demand_penalty_inr", "Over-limit penalty"], ["bill_fsa_inr", "Fuel surcharge"], ["bill_electricity_duty_inr", "Electricity duty"],
  ["bill_municipal_tax_inr", "Municipal tax"], ["bill_dg_cost_inr", "Diesel generator"], ["bill_total_energy_cost_inr", "Total"],
];

export default function Finance() {
  const bills = useData<Bills>("bills.json");
  const sv = useData<Savings>("savings.json");
  const [site, setSite] = useState<Site>("GGN");
  const [sel, setSel] = useState<string | null>(null);
  const rows = bills ? bills.recon.filter((r) => r.site === site).sort((a, b) => a.month.localeCompare(b.month)) : [];
  const pick: Recon | undefined = rows.find((r) => r.month === sel) ?? rows.find((r) => r.status !== "Reconciled") ?? rows[0];
  const all = bills?.recon ?? [];
  const counts = { rec: all.filter((r) => r.status === "Reconciled").length, fault: all.filter((r) => r.status === "Meter fault").length, prov: all.filter((r) => r.status === "Provisional").length };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Bills and savings</h1>
          <p className="lead">Every bill is checked line by line against the tariff and our own meter. Of the last {all.length} bills, {counts.rec} match, {counts.fault} were issued on faulty meter readings and {counts.prov} is an estimate worth disputing.</p>
        </div>
        <SiteSwitch value={site} onChange={(s) => { setSite(s as Site); setSel(null); }} all={false} />
      </div>

      <div className="split">
        <div className="panel scroll-x">
          <table className="t">
            <thead><tr><th>Month</th><th>Check</th><th className="r">Billed</th><th className="r">vs our meter</th><th className="r">Peak demand</th></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.month} className={`click ${pick?.month === r.month ? "sel" : ""}`} onClick={() => setSel(r.month)}>
                <td className="nw">{fmtMonth(r.month)}</td><td className="nw"><Status s={r.status} /></td><td className="r">{inr(r.billed_total, { exact: true })}</td>
                <td className="r" style={{ color: Math.abs(r.billed_minus_corrected) > 1000 ? "var(--red)" : "var(--ink-3)" }}>{Math.abs(r.billed_minus_corrected) < 1 ? "—" : (r.billed_minus_corrected > 0 ? "+" : "−") + inr(Math.abs(r.billed_minus_corrected), { exact: true })}</td>
                <td className="r">{n(r.md_kva)} kVA</td>
              </tr>
            ))}</tbody>
          </table>
          <p className="muted small" style={{ marginBottom: 0 }}>Peak-demand charges: the hotel pays for its highest power draw of the month, but never less than 75% of its contracted limit. Anything above the limit is charged again as a penalty.</p>
        </div>
        {pick && (
          <div className="panel">
            <h3>{fmtMonth(pick.month)} <Status s={pick.status} /></h3>
            <div className="grid g2" style={{ margin: "6px 0 10px" }}>
              <div className="stat"><span>Billed</span><b>{inr(pick.billed_total, { exact: true })}</b></div>
              <div className="stat"><span>On our meter</span><b>{inr(pick.corrected_total, { exact: true })}</b></div>
            </div>
            <p className="small" style={{ color: "var(--ink-2)" }}>{pick.status === "Reconciled" ? "This bill matches our meter and the tariff line by line." :
              pick.status === "Provisional" ? `The utility estimated this reading. It charges for ${pick.meter_gap_pct.toFixed(0)}% more energy than our meter recorded. Ask for a bill on the actual reading: about ${inr(pick.billed_minus_corrected)} too high.` :
              pick.status === "Meter fault" ? `The utility's meter sent bad readings for some hours this month, and the bill used them. On our corrected reading the bill would be ${inr(Math.abs(pick.billed_minus_corrected), { exact: true })} ${pick.billed_minus_corrected > 0 ? "lower" : "higher"}. Raise it with the utility if it matters.` : pick.note}</p>
            <table className="t">
              <thead><tr><th>Line on the bill</th><th className="r">Amount</th></tr></thead>
              <tbody>{LINES.map(([k, l]) => (
                <tr key={k} style={{ fontWeight: k.includes("total") ? 700 : 400 }}><td>{l}</td><td className="r">{inr(pick[k] as number, { exact: true })}</td></tr>
              ))}</tbody>
            </table>
            <p className="muted small" style={{ marginBottom: 0 }}>We recalculated every line from the tariff, and each one matches to within ₹{n(pick.tariff_check_max_gap)}.</p>
          </div>
        )}
      </div>
      {bills && bills.unused_demand[site].months_on_floor > 0 && (
        <div className="guard note-warn" style={{ marginTop: 14 }}>
          <span aria-hidden>₹</span>
          <span>{SITE_NAME[site]} is paying for power capacity it never uses. Its highest draw stayed below the minimum it is billed for ({n(bills.unused_demand[site].floor)} kVA, 75% of its {n(bills.unused_demand[site].cd)} kVA contract) in {bills.unused_demand[site].months_on_floor} of 12 months. That cost {inr(bills.unused_demand[site].paid_for_unused_inr)} this year. A lower contract is in the savings plan below.</span>
        </div>
      )}

      {sv && <SavingsBlock sv={sv} />}
      {sv && <OptionC sv={sv} />}
    </>
  );
}

function SavingsBlock({ sv }: { sv: Savings }) {
  const core = sv.measures.filter((m) => m.category !== "Capital (note)");
  const capx = sv.measures.filter((m) => m.category === "Capital (note)");
  const total = core.reduce((s, m) => s + m.inr, 0);
  const groups = useMemo(() => {
    const g: Record<string, number> = {};
    for (const m of core) {
      const k = measureGroup(m.measure);
      g[k] = (g[k] ?? 0) + m.inr;
    }
    let run = 0;
    const rows = Object.entries(g).sort((a, b) => b[1] - a[1]).map(([k, v]) => { const r = { k, base: run / sv.group_bill * 100, v: v / sv.group_bill * 100, inr: v }; run += v; return r; });
    const cap = capx.reduce((s, m) => s + m.inr, 0);
    rows.push({ k: "Pump speed controls (investment)", base: run / sv.group_bill * 100, v: cap / sv.group_bill * 100, inr: cap });
    return rows;
  }, [sv]);
  return (
    <>
      <h2>Where to save: {inr(total)} a year ({(total / sv.group_bill * 100).toFixed(1)}% of the electricity bill)</h2>
      <div className="split">
        <div className="panel">
          <ResponsiveContainer width="100%" height={330}>
            <BarChart data={groups} layout="vertical" margin={{ top: 4, right: 70, bottom: 4, left: 8 }}>
              <CartesianGrid stroke="#e8ecee" horizontal={false} />
              <XAxis type="number" domain={[0, 12]} tickFormatter={(v) => `${v}%`} tick={{ fontSize: 11, fill: "#7b8792" }} />
              <YAxis type="category" dataKey="k" width={170} tick={{ fontSize: 12, fill: "#4a5763" }} />
              <ReferenceArea x1={8} x2={12} fill="#2f7a57" fillOpacity={0.08} label={{ value: "Goal 8–12%", position: "insideTop", fontSize: 11, fill: "#2f7a57" }} />
              <Tooltip formatter={(_v: number, _k: string, p: any) => [`${inr(p.payload.inr)} (${p.payload.v.toFixed(2)}% of bill)`, ""]} />
              <Bar dataKey="base" stackId="s" fill="transparent" isAnimationActive={false} />
              <Bar dataKey="v" stackId="s" isAnimationActive={false}>
                {groups.map((g) => <Cell key={g.k} fill={g.k.includes("investment") ? "#c9d1d5" : g.k === "Night lighting" ? "#efc77f" : "#e3a23b"} />)}
                <LabelList dataKey="inr" content={(p: any) => <text x={(p.x ?? 0) + (p.width ?? 0) + 6} y={(p.y ?? 0) + (p.height ?? 0) / 2 + 4} fontSize={11} fill="#4a5763">{inr(p.value)}</text>} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <p className="muted small" style={{ marginBottom: 0 }}>Each step adds to the one before. Light saffron is a rough estimate. Grey needs investment and is not counted in the total.</p>
        </div>
        <div className="panel">
          <h3>Getting to the 8–12% goal</h3>
          <p className="small" style={{ marginTop: 0 }}>Day-to-day waste is only about 3% of the bill, so fixing waste alone won't reach 8%. Most of the rest comes from how the hotels are billed: the capacitor panel and the contracted power limit. Two more steps could close the gap:</p>
          <ul className="small" style={{ paddingLeft: 18 }}>
            <li>A walk-through of the night-time base load at Gurugram (about 330 kW between 1 and 5 am), much of it not on a sub-meter.</li>
            <li>Investments such as pump speed controls, with payback worked out case by case.</li>
          </ul>
        </div>
      </div>
      <div className="panel scroll-x" style={{ marginTop: 14 }}>
        <table className="t">
          <thead><tr><th>Hotel</th><th>What to do</th><th>Kind</th><th className="r">Saves a year</th><th>How sure</th><th>Safety</th></tr></thead>
          <tbody>{[...sv.measures].sort((a, b) => b.inr - a.inr).map((m, i) => (
            <tr key={i}><td>{m.hotel}</td><td><strong>{measureName(m.measure)}</strong><details className="more-info"><summary>How we worked it out</summary><p className="tech">{m.basis}</p></details></td>
              <td>{CATEGORY[m.category] ?? m.category}</td><td className="r">{inr(m.inr)}</td><td className="small">{CONFIDENCE(m.confidence)}</td><td className="small">{m.safety}</td></tr>
          ))}</tbody>
        </table>
      </div>
    </>
  );
}

function OptionC({ sv }: { sv: Savings }) {
  const [site, setSite] = useState<Site>("GGN");
  const s = sv.option_c[site];
  const rows = s.monthly.map((m) => ({ ...m, month: m.month.slice(2).replace("-", "/") }));
  return (
    <>
      <h2>How savings will be proven</h2>
      <p className="lead" style={{ marginTop: -4 }}>A saving only counts if it holds up after allowing for the weather, guests and events. Each month we compare what the hotel actually used with what it would have used for those conditions. That is the international standard (IPMVP) that auditors accept. No changes have been made yet, so there are no savings to claim so far. This is the yardstick they will be measured with.</p>
      <div style={{ margin: "12px 0" }}><SiteSwitch value={site} onChange={(x) => setSite(x as Site)} all={false} /></div>
      <div className="split">
        <div className="panel">
          <ResponsiveContainer width="100%" height={240}>
            <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
              <CartesianGrid stroke="#e8ecee" vertical={false} />
              <XAxis dataKey="month" tick={{ fontSize: 11, fill: "#7b8792" }} />
              <YAxis tickFormatter={(v) => `${Math.round(v / 1000)}k`} tick={{ fontSize: 11, fill: "#7b8792" }} width={48} />
              <Tooltip formatter={(v: number, k: string) => [`${n(v)} kWh`, k === "baseline" ? "Adjusted baseline" : "Actual"]} />
              <Bar dataKey="baseline" fill="#d5dcdf" isAnimationActive={false} />
              <Line dataKey="actual" stroke="#17212a" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
          <p className="muted small" style={{ marginBottom: 0 }}>Grey bars show what each month should have used, worked out without looking at that month. The line shows what the meter recorded. The closer they are, the smaller the saving that can be proven.</p>
        </div>
        <div className="panel">
          <div className="grid g2">
            <div className="stat"><span>Monthly accuracy</span><b>within {s.cv_rmse_monthly.toFixed(1)}%</b><em>typical gap, month by month</em></div>
            <div className="stat"><span>Smallest saving it can prove</span><b>{s.min_verifiable_pct?.toFixed(1)}%</b><em>of {SITE_NAME[site]}'s electricity use</em></div>
          </div>
          <details className="more-info"><summary>For auditors</summary>
            <table className="t" style={{ marginTop: 8 }}>
              <tbody>
                <tr><td>Hourly CV(RMSE)</td><td className="r">{s.cv_rmse_hourly.toFixed(1)}%</td><td className="muted small">ASHRAE G14 limit 30%</td></tr>
                <tr><td>Monthly CV(RMSE)</td><td className="r">{s.cv_rmse_monthly.toFixed(1)}%</td><td className="muted small">limit 15%</td></tr>
                <tr><td>NMBE</td><td className="r">{s.nmbe >= 0 ? "+" : ""}{s.nmbe.toFixed(2)}%</td><td className="muted small">limit ±5%</td></tr>
                <tr><td>Uncertainty on an 8% saving</td><td className="r">±{s.fsu_at_8pct.toFixed(0)}%</td><td className="muted small">90% confidence</td></tr>
              </tbody>
            </table>
            <p className="tech">IPMVP Option C, whole-building adjusted baseline; meter-fault hours excluded.</p>
          </details>
        </div>
      </div>
    </>
  );
}
