// Savings for one month, split so nothing is counted twice (used by Bills & savings and the monthly report, so they always agree):
//   from the daily plan  - verified ₹ of followed plan steps (POST /api/savings; saved plans where they exist, else the suggested plan);
//   from acting on alerts - ₹ of waste the alerts caught in the month; for Gurugram, hours where a followed plan step covers the same
//                          equipment are dropped (that saving is the plan's, not the alert's);
//   Option C             - adjusted baseline (weather, occupancy, events) minus actual kWh per hotel, up to the hour shown: the total effect
//                          however it is split. Meter-fault hours are excluded (T5).
import { useEffect, useMemo, useState } from "react";
import { SITES, useAlertsAt, useBillsAt, useHourlyAll, type Alert, type Hourly, type Recon, type Site } from "./data";
import { LIVE_START } from "./feedcore";
import { monthSavings, type SavingsResult } from "./planApi";
import { loadMonthPlans } from "./planStore";

const RULE_GROUP: Record<string, string> = { CHILLER_STAGING_LOW_LOAD: "chillers", STAGING_KWTR: "chillers", CHW_SETPOINT_LOW: "chw", AHU_HAND_MODE: "ahu",
  LAUNDRY_IN_PEAK: "laundry", EV_CHARGER_NIGHT_ON: "ev" };
const ms = (t: string) => Date.parse(`${t.slice(0, 16)}:00Z`);

/** kWh of the live year's built-in growth in a month, per hotel: tools/make_live_year.py scales load by 1.012^(1 + (d - 182.5)/365)
 *  (d = days since 1 Oct 2026), which the adjusted baseline trained on the original year cannot know about. */
export function growthKwh(hr: Record<Site, Hourly | null>, month: string, asOf: string): Record<Site, number> {
  const out = { GGN: 0, JAI: 0, GOA: 0 } as Record<Site, number>;
  const t0 = Date.parse("2026-10-01T00:00:00Z"), key = asOf.slice(0, 13);
  for (const s of SITES) {
    const h = hr[s];
    if (!h) continue;
    h.t.forEach((t, i) => {
      if (t.slice(0, 7) !== month || t > key || h.f[i]) return;
      const d = Math.floor((Date.parse(`${t.slice(0, 10)}T00:00:00Z`) - t0) / 864e5);
      if (d >= 0) out[s] += h.a[i] * (1 - 1 / 1.012 ** (1 + (d - 182.5) / 365));
    });
  }
  return out;
}

/** Alert ₹ in the month (by alert start), less the hours a followed plan step already covers for that equipment (Gurugram). */
export function alertRupees(alerts: Alert[], month: string, covered: Record<string, Record<string, number[]>>) {
  let total = 0, dropped = 0, n = 0;
  for (const a of alerts) {
    if (a.start.slice(0, 7) !== month || a.cost <= 0 || a.rule === "PLAN_DEVIATION") continue;
    n++;
    const g = a.site === "GGN" ? RULE_GROUP[a.rule] : undefined;
    let keep = a.cost;
    if (g) {
      const hrs = Math.max(1, Math.round((ms(a.end) - ms(a.start)) / 3.6e6));
      let overlap = 0;
      for (let t = ms(a.start); t < ms(a.end); t += 3.6e6) {
        const iso = new Date(t).toISOString(), d = iso.slice(0, 10), h = Number(iso.slice(11, 13));
        if (covered[d]?.[g]?.includes(h)) overlap++;
      }
      keep = a.cost * (1 - overlap / hrs);
      dropped += a.cost - keep;
    }
    total += keep;
  }
  return { inr: total, dropped_inr: dropped, alerts: n };
}

export interface MonthSavings {
  month: string; asOf: string;
  plan: SavingsResult | null | undefined;                 // undefined = loading, null = service unavailable or no live days
  alerts: { inr: number; dropped_inr: number; alerts: number } | null;
  optionC: { bySite: Record<Site, { actual: number; baseline: number; kwh: number; inr: number; hours: number; rate: number }>; kwh: number; inr: number } | null;
  hourly: Record<Site, Hourly | null>;
}

function rateOf(recon: Recon[], site: Site, month: string): number {
  const rs = recon.filter((r) => r.site === site).sort((a, b) => a.month.localeCompare(b.month));
  const r = rs.find((x) => x.month === month) ?? rs.filter((x) => x.month <= month).at(-1) ?? rs.at(-1);
  return r ? r.billed_total / Math.max(r.billed_kvah * r.pf, 1) : 0;          // average ₹ per kWh on that bill
}

export function useMonthSavings(month: string, asOf: string): MonthSavings {
  const alerts = useAlertsAt(asOf);
  const bills = useBillsAt(asOf);
  const hr = { GGN: useHourlyAll("GGN"), JAI: useHourlyAll("JAI"), GOA: useHourlyAll("GOA") };
  const [plan, setPlan] = useState<SavingsResult | null | undefined>(undefined);
  const live = month >= LIVE_START.slice(0, 7);
  useEffect(() => {
    let on = true;
    setPlan(undefined);
    if (!live || `${month}-02` > asOf.slice(0, 10)) { setPlan(null); return; }
    loadMonthPlans(month).then((saved) => monthSavings(month, `${asOf.slice(0, 13)}:00`, saved)).then((r) => on && setPlan(r));
    return () => { on = false; };
  }, [month, asOf.slice(0, 13), live]);
  const covered = useMemo(() => Object.fromEntries((plan?.days ?? []).map((d) => [d.date, d.covered])), [plan]);
  const al = useMemo(() => (alerts && plan !== undefined ? alertRupees(alerts, month, covered) : null), [alerts, covered, month, plan]);
  const optionC = useMemo(() => {
    if (!bills || SITES.some((s) => !hr[s])) return null;
    const key = asOf.slice(0, 13);
    const bySite = {} as NonNullable<MonthSavings["optionC"]>["bySite"];
    for (const s of SITES) {
      const h = hr[s]!;
      let a = 0, b = 0, n = 0;
      h.t.forEach((t, i) => { if (t.slice(0, 7) === month && t <= key && !h.f[i]) { a += h.a[i]; b += h.b[i]; n++; } });
      const rate = rateOf(bills.recon, s, month);
      bySite[s] = { actual: a, baseline: b, kwh: b - a, inr: (b - a) * rate, hours: n, rate };
    }
    return { bySite, kwh: SITES.reduce((x, s) => x + bySite[s].kwh, 0), inr: SITES.reduce((x, s) => x + bySite[s].inr, 0) };
  }, [bills, hr.GGN, hr.JAI, hr.GOA, month, asOf.slice(0, 13)]);
  return { month, asOf, plan, alerts: al, optionC, hourly: hr };
}
