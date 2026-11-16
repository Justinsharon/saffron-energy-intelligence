// Finance controller's Savings page: the two headline figures, where they come from (never counted twice), and how each saving will be
// proven (IPMVP Option C). Every number is read from savings.json (original year) and live_feed/savings.json (live year), as on Bills & savings.
import { useData, type Measure, type Savings } from "../data";
import { inr } from "../format";
import { OptionC } from "./Finance";

const SOURCES: { k: string; label: string; test: (m: Measure) => boolean }[] = [
  { k: "alerts", label: "Alerts acted on (waste fixed, capacitor faults repaired)", test: (m) => m.measure.startsWith("Act on detected") || m.measure.startsWith("Keep PF") },
  { k: "plan", label: "Daily plan: lower peak demand (the part the alerts don't already count)", test: (m) => m.measure.startsWith("Daily operating plan") },
  { k: "capital", label: "Capital: pump speed controls (VFDs)", test: (m) => m.category === "Capital" },
];
const other = (m: Measure) => !SOURCES.some((s) => s.test(m));
const sum = (ms: Measure[], f: (m: Measure) => boolean) => ms.filter(f).reduce((x, m) => x + m.inr, 0);

export default function SavingsPage() {
  const sv = useData<Savings>("savings.json");
  const lv = useData<Savings>("live_feed/savings.json");
  if (!sv) return <p className="muted">Loading…</p>;
  const t = sv.totals;
  const rows = [
    SOURCES[0],
    { k: "other", label: "Other operating changes (tariff timing, power factor, contracted limit, chilled water)", test: other },
    SOURCES[1], SOURCES[2],
  ];
  return (
    <>
      <div className="page-head"><div>
        <h1>Savings</h1>
        <p className="lead">What the three hotels can save a year, from the original year's data (Oct 2025 – Sep 2026), and how each rupee will be proven.</p>
      </div></div>

      <div className="grid g2">
        <div className="stat big-stat"><span>From operations</span><b>{t.operations_pct.toFixed(1)}%</b><em>{inr(t.operations_inr)} a year of the {inr(sv.group_bill)} electricity bill</em></div>
        <div className="stat big-stat"><span>With one capital item (pump VFDs)</span><b>{t.with_capital_pct.toFixed(1)}%</b><em>{inr(t.with_capital_inr)} a year; the VFDs need investment</em></div>
      </div>
      {lv?.totals && <p className="small muted" style={{ margin: "8px 0 0" }}>Checked on the live year (Oct 2026 – Sep 2027, simulated meters): {lv.totals.operations_pct.toFixed(1)}% · {lv.totals.with_capital_pct.toFixed(1)}%.</p>}

      <h2>Where the savings come from</h2>
      <div className="panel scroll-x">
        <table className="t">
          <thead><tr><th>Source</th><th className="r">Original year</th><th className="r">Live year (check)</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.k}><td>{r.label}</td><td className="r">{r.k === "plan" ? "—" : inr(sum(sv.measures, r.test))}</td><td className="r">{lv ? inr(sum(lv.measures, r.test)) : "…"}</td></tr>
            ))}
            <tr style={{ fontWeight: 700 }}><td>From operations</td><td className="r">{inr(t.operations_inr)}</td><td className="r">{lv ? inr(lv.totals.operations_inr) : "…"}</td></tr>
            <tr style={{ fontWeight: 700 }}><td>With one capital item</td><td className="r">{inr(t.with_capital_inr)}</td><td className="r">{lv ? inr(lv.totals.with_capital_inr) : "…"}</td></tr>
          </tbody>
        </table>
        <p className="small" style={{ marginBottom: 0 }}><strong>Never counted twice.</strong> The daily plan prevents the same waste the alerts catch, so only its extra peak-demand saving is added (live year only).
          The plan's verified savings from approved steps are shown on the plan pages and the monthly report, never added here.
          {sv.not_sized.filter((x) => x.startsWith("CH-1")).map((x) => ` Not counted: ${x}.`)}</p>
      </div>

      <OptionC sv={sv} />

      <h2>Method</h2>
      <p style={{ maxWidth: "80ch" }}>Each saving is measured against an adjusted baseline: what the hotel would have used for the actual weather, guests and events (IPMVP Option C, whole-site meter).
        Only savings that hold up after that adjustment are claimed; tariff rates are illustrative.</p>
    </>
  );
}
