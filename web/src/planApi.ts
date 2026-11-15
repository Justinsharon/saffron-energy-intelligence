// One source for a day's plan everywhere (Tomorrow's plan, Today's plan card, Ask): the plan API on Cloud Run (POST /api/plan, proxied by
// Netlify; the frozen models run on the actual inputs), with a 4 s timeout. If it can't be reached, the same rules run in the browser on the
// exported per-day inputs (plan.ts) and the result is labelled an offline estimate. Recommend only either way.
import { byTime, planFor, riskFor, type Action, type Booking, type PlanDay, type RiskCal } from "./plan";

export interface PlanRequest { date: string; rooms?: number; guests?: number; covers?: number; bookings?: Booking[] }
export interface PlanRisk { peak: number; upper: number; stack: number; p_exceed: number | null; level: string; hour: number }
export interface PlanResult {
  source: "api" | "offline";
  forecast: { kw: number[]; kva: number[]; tr: number[]; temp: number[] };
  risk: PlanRisk | null;
  actions: Action[];
  total_inr: number;
  notes: string[];                     // how the inputs were read (API), or why this is an offline estimate
  weather: string;
  bookings: Booking[];                 // the bookings as planned (after any combining)
}

export const API_TIMEOUT_MS = 4000;

export async function apiPlan(req: PlanRequest, base = "/api", timeoutMs = API_TIMEOUT_MS): Promise<PlanResult> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(`${base}/plan`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(req), signal: ctrl.signal });
    if (!(r.headers.get("content-type") ?? "").includes("json")) throw new Error("plan service not reachable");
    const j = await r.json();
    if (!r.ok) throw Object.assign(new Error(j.error ?? `plan service error ${r.status}`), { status: r.status, notes: j.notes });
    const k = j.risk;
    return { source: "api", forecast: { kw: j.forecast.kw, kva: j.forecast.kva, tr: j.forecast.tr, temp: j.forecast.temp_c },
             risk: { peak: k.peak_kva, upper: k.upper_kva, stack: k.stack_kva, p_exceed: k.p_exceed, level: k.level, hour: k.hour },
             actions: byTime(j.actions as Action[]), total_inr: j.total_saving_inr, notes: j.notes ?? [], weather: j.inputs_used?.weather ?? "",
             bookings: j.inputs_used?.bookings ?? req.bookings ?? [] };
  } finally {
    clearTimeout(t);
  }
}

export function offlinePlan(day: PlanDay, req: PlanRequest, temps: number[] | null, cal: RiskCal | null, why: string): PlanResult {
  const bookings = req.bookings ?? [];
  const res = planFor(day, { rooms: req.rooms, guests: req.guests, covers: req.covers, bookings, temps });
  const r = cal ? riskFor(res.forecast.kva, cal) : null;
  return { source: "offline", forecast: res.forecast, risk: r && { peak: r.peak, upper: r.upper, stack: r.stack, p_exceed: r.p_exceed, level: r.level, hour: r.hour },
           actions: byTime(res.actions), total_inr: res.total_inr, notes: [why],
           weather: temps ? "Open-Meteo hourly forecast (in the browser)" : "typical temperatures for this date", bookings };
}

/** The API's plan, else the offline estimate. A 422 (e.g. a date outside the plan range) is not retried offline: its message is the answer. */
export async function getPlan(req: PlanRequest, offline: { day: PlanDay | null; temps: number[] | null; cal: RiskCal | null }): Promise<PlanResult> {
  try {
    return await apiPlan(req);
  } catch (e) {
    const err = e as Error & { status?: number };
    if (!offline.day) throw err;
    const why = err.name === "AbortError" ? "The planning service did not answer within 4 seconds, so this is an offline estimate worked out in your browser."
      : err.status === 422 ? `The planning service could not plan this: ${err.message}`
      : "The planning service could not be reached, so this is an offline estimate worked out in your browser.";
    return offlinePlan(offline.day, req, offline.temps, offline.cal, why);
  }
}
