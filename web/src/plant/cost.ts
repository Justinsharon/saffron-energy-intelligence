// What a plan-deviation alert's ₹ is made of, for the alert card and its evidence: every number comes from the plan check (/check, or the
// browser port), which priced the extra kWh with the plan's tariff. Nothing is estimated here; this only lays the figures out.
import type { Alert } from "../data";

export interface CostRow { t: string; signal: number | null; kwh: number; inr: number }
export function costBreakdown(a: Alert) {
  const col = Object.keys(a.chart.signals)[0] ?? "";
  const sig = a.chart.signals[col] ?? [];
  const rate = a.excess_kwh > 0 ? a.cost / a.excess_kwh : 0;                 // ₹ per extra kWh as the check priced it
  const rows: CostRow[] = [];
  a.chart.t.forEach((t, i) => {
    if (t < a.start.slice(0, 13) || t >= a.end.slice(0, 13)) return;
    const kwh = Math.round((a.chart.actual[i] - a.chart.baseline[i]) * 10) / 10;   // the hour's extra kWh (actual minus the plan)
    rows.push({ t: t.slice(11, 13) + ":00", signal: sig[i] ?? null, kwh, inr: kwh * rate });
  });
  return { col, rows, hours: a.flagged_h, kwh: a.excess_kwh, soFar: a.cost, perHour: a.per_hour, allDay: Math.round(a.per_hour * 24), rate };
}
