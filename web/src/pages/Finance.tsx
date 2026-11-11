import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ComposedChart, Line, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis, Cell, LabelList } from "recharts";
import { Status } from "../components/parts";
import { SITES, SITE_NAME, useData, type Bills, type Recon, type Savings, type Site } from "../data";
import { fmtMonth, inr, n } from "../format";
import { SiteSwitch } from "./Shift";

const LINES: [string, string][] = [
  ["bill_energy_charge_inr", "Energy (kVAh)"], ["bill_tod_net_inr", "ToD net"], ["bill_demand_charge_inr", "Demand charge"],
  ["bill_excess_demand_penalty_inr", "Excess-demand penalty"], ["bill_fsa_inr", "Fuel surcharge"], ["bill_electricity_duty_inr", "Electricity duty"],
  ["bill_municipal_tax_inr", "Municipal tax"], ["bill_dg_cost_inr", "Diesel"], ["bill_total_energy_cost_inr", "Total"],
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
          <p className="lead">Every bill rebuilt line by line from the tariff and the meter. {counts.rec} of {all.length} reconcile; {counts.fault} were issued on faulty meter readings; {counts.prov} is an estimate.</p>
        </div>
        <SiteSwitch value={site} onChange={(s) => { setSite(s as Site); setSel(null); }} all={false} />
      </div>

      <div className="split">
        <div className="panel scroll-x">
          <table className="t">
            <thead><tr><th>Month</th><th>Status</th><th className="r">Billed</th><th className="r">Meter-based</th><th className="r">Difference</th><th className="r">Peak kVA</th><th className="r">PF</th></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.month} className={`click ${pick?.month === r.month ? "sel" : ""}`} onClick={() => setSel(r.month)}>
                <td className="nw">{fmtMonth(r.month)}</td><td className="nw"><Status s={r.status} /></td><td className="r">{inr(r.billed_total, { exact: true })}</td>
                <td className="r">{inr(r.corrected_total, { exact: true })}</td>
                <td className="r" style={{ color: Math.abs(r.billed_minus_corrected) > 1000 ? "var(--red)" : "var(--ink-3)" }}>{Math.abs(r.billed_minus_corrected) < 1 ? "—" : (r.billed_minus_corrected > 0 ? "+" : "−") + inr(Math.abs(r.billed_minus_corrected), { exact: true })}</td>
                <td className="r">{n(r.md_kva)}</td><td className="r" title={r.pf_source}>{r.pf.toFixed(3)}{r.pf_source !== "bill" ? "*" : ""}</td>
              </tr>
            ))}</tbody>
          </table>
          <p className="muted small" style={{ marginBottom: 0 }}>Billing demand = max(peak, 75% of contract demand), charged up to contract demand; peak above contract is charged again at 2× as a penalty. * PF from the meter where the bill's kVAh was estimated.</p>
        </div>
        {pick && (
          <div className="panel">
            <h3>{fmtMonth(pick.month)} <Status s={pick.status} /></h3>
            <p className="small" style={{ color: "var(--ink-2)" }}>{pick.note}</p>
            <table className="t">
              <thead><tr><th>Line</th><th className="r">Issued bill</th></tr></thead>
              <tbody>{LINES.map(([k, l]) => (
                <tr key={k} style={{ fontWeight: k.includes("total") ? 700 : 400 }}><td>{l}</td><td className="r">{inr(pick[k] as number, { exact: true })}</td></tr>
              ))}</tbody>
            </table>
            <p className="muted small" style={{ marginBottom: 0 }}>Rebuilt from the tariff, every line matches within ₹{n(pick.tariff_check_max_gap)}. Billed kVAh {n(pick.billed_kvah)} vs meter {n(pick.meter_kvah)} ({pick.meter_gap_pct >= 0 ? "+" : ""}{pick.meter_gap_pct.toFixed(2)}%). Bills are never altered.</p>
          </div>
        )}
      </div>
      {bills && bills.unused_demand[site].months_on_floor > 0 && (
        <div className="guard note-warn" style={{ marginTop: 14 }}>
          <span aria-hidden>₹</span>
          <span>{SITE_NAME[site]} paid for demand it never used: peak stayed below 75% of the {n(bills.unused_demand[site].cd)} kVA contract ({n(bills.unused_demand[site].floor)} kVA) in {bills.unused_demand[site].months_on_floor} of 12 months, costing {inr(bills.unused_demand[site].paid_for_unused_inr)} this year. Right-sizing the contract is in the savings plan below.</span>
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
      const k = m.measure.startsWith("Act on detected") ? "Act on alerts" : m.measure.startsWith("Hold PF") ? "PF held at 0.99" :
        m.measure.startsWith("Keep PF") ? "Repair PF drops" : m.measure.startsWith("Right-size") ? "Right-size contract demand" :
        m.measure.startsWith("Dim") ? "Night lighting (assumed)" : m.measure.startsWith("Avoid contract") ? "Avoid demand penalties" :
        m.measure.startsWith("Shift flexible") ? "Shift loads off-peak" : "CHW reset to 8 °C";
      g[k] = (g[k] ?? 0) + m.inr;
    }
    let run = 0;
    const rows = Object.entries(g).sort((a, b) => b[1] - a[1]).map(([k, v]) => { const r = { k, base: run / sv.group_bill * 100, v: v / sv.group_bill * 100, inr: v }; run += v; return r; });
    const cap = capx.reduce((s, m) => s + m.inr, 0);
    rows.push({ k: "Pump VFDs (capital)", base: run / sv.group_bill * 100, v: cap / sv.group_bill * 100, inr: cap });
    return rows;
  }, [sv]);
  return (
    <>
      <h2>Savings plan: {(total / sv.group_bill * 100).toFixed(1)}% of the bill identified, target 8–12%</h2>
      <div className="split">
        <div className="panel">
          <ResponsiveContainer width="100%" height={330}>
            <BarChart data={groups} layout="vertical" margin={{ top: 4, right: 70, bottom: 4, left: 8 }}>
              <CartesianGrid stroke="#e8ecee" horizontal={false} />
              <XAxis type="number" domain={[0, 12]} tickFormatter={(v) => `${v}%`} tick={{ fontSize: 11, fill: "#7b8792" }} />
              <YAxis type="category" dataKey="k" width={170} tick={{ fontSize: 12, fill: "#4a5763" }} />
              <ReferenceArea x1={8} x2={12} fill="#2f7a57" fillOpacity={0.08} label={{ value: "Target 8–12%", position: "insideTop", fontSize: 11, fill: "#2f7a57" }} />
              <Tooltip formatter={(_v: number, _k: string, p: any) => [`${inr(p.payload.inr)} (${p.payload.v.toFixed(2)}% of bill)`, ""]} />
              <Bar dataKey="base" stackId="s" fill="transparent" isAnimationActive={false} />
              <Bar dataKey="v" stackId="s" isAnimationActive={false}>
                {groups.map((g) => <Cell key={g.k} fill={g.k.includes("capital") ? "#c9d1d5" : g.k.includes("assumed") ? "#efc77f" : "#e3a23b"} />)}
                <LabelList dataKey="inr" position="right" formatter={(v: number) => inr(v)} style={{ fontSize: 11, fill: "#4a5763" }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <p className="muted small" style={{ marginBottom: 0 }}>Each bar starts where the previous one ends, so the last bar reaches the running total. Light saffron rests on an assumed share; grey is capital, shown as a note and outside the headline.</p>
        </div>
        <div className="panel">
          <h3>Why it stops short of 8%</h3>
          <p className="small" style={{ marginTop: 0 }}>The labelled waste in this data is itself about 2.9% of the bill, so catching waste alone cannot reach 8%. The rest of the plan comes from tariff levers (power factor, contract demand) and operating changes.</p>
          <ul className="small" style={{ paddingLeft: 18 }}>{sv.not_sized.map((t) => <li key={t}>{t}</li>)}</ul>
        </div>
      </div>
      <div className="panel scroll-x" style={{ marginTop: 14 }}>
        <table className="t">
          <thead><tr><th>Hotel</th><th>Measure</th><th>Type</th><th className="r">₹ / year</th><th>Basis</th><th>Safety check</th><th>Confidence</th></tr></thead>
          <tbody>{[...sv.measures].sort((a, b) => b.inr - a.inr).map((m, i) => (
            <tr key={i}><td>{m.hotel}</td><td><strong>{m.measure}</strong></td><td>{m.category}</td><td className="r">{inr(m.inr)}</td>
              <td className="small">{m.basis}</td><td className="small">{m.safety}</td><td className="small">{m.confidence}</td></tr>
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
      <h2>How savings will be proven (IPMVP Option C)</h2>
      <p className="lead" style={{ marginTop: -4 }}>Savings are claimed only as adjusted baseline minus actual, with the baseline driven by the reporting month's real weather, bookings and events. No measure was implemented in the data year, so no verified saving is claimed yet; this is the model finance would rely on.</p>
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
          <p className="muted small" style={{ marginBottom: 0 }}>Grey bars: what the model expected for each month, never having seen that month. Line: what the meter recorded.</p>
        </div>
        <div className="panel">
          <table className="t">
            <tbody>
              <tr><td>Hourly CV(RMSE)</td><td className="r"><strong>{s.cv_rmse_hourly.toFixed(1)}%</strong></td><td className="muted small">limit 30%</td></tr>
              <tr><td>Monthly CV(RMSE)</td><td className="r"><strong>{s.cv_rmse_monthly.toFixed(1)}%</strong></td><td className="muted small">limit 15%</td></tr>
              <tr><td>Bias (NMBE)</td><td className="r"><strong>{s.nmbe >= 0 ? "+" : ""}{s.nmbe.toFixed(2)}%</strong></td><td className="muted small">limit ±5%</td></tr>
              <tr><td>Uncertainty on an 8% saving</td><td className="r"><strong>±{s.fsu_at_8pct.toFixed(0)}%</strong></td><td className="muted small">of the saving, 90% confidence</td></tr>
              <tr><td>Smallest provable saving</td><td className="r"><strong>{s.min_verifiable_pct?.toFixed(1)}%</strong></td><td className="muted small">of {SITE_NAME[site]}'s use</td></tr>
            </tbody>
          </table>
          <p className="muted small" style={{ marginBottom: 0 }}>ASHRAE Guideline 14 limits. Meter-fault hours are excluded; faults are never counted as savings.</p>
        </div>
      </div>
    </>
  );
}
