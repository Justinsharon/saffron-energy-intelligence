// One source for a day's plan everywhere (Tomorrow's plan, Today's plan card, Ask): the plan API on Cloud Run (POST /api/plan, proxied by
// Netlify; the frozen models run on the actual inputs), with a 4 s timeout. If it can't be reached, Gurugram's rules run in the browser on
// the exported per-day inputs (plan.ts) and the result is labelled an offline estimate; Jaipur and Goa are planned by the API only (their
// models and per-hotel rules are not shipped to the browser). Recommend only either way.
import { byTime, planFor, riskFor, type Action, type Booking, type PlanDay, type PlanSite, type RiskCal } from "./plan";

export interface PlanRequest { date: string; site?: PlanSite; rooms?: number; guests?: number; covers?: number; bookings?: Booking[] }
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
  site: PlanSite;
  contract_kva: number;
  defaults?: { rooms: number; guests: number; covers: number };      // the inputs the API used (the usual pattern where none were given)
  not_counted_inr?: number;            // Jaipur / Goa: CHW setpoint estimate, not verifiable, never in a total
  cv_rmse_pct?: { kw: number; tr: number; kva: number };
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
             bookings: j.inputs_used?.bookings ?? req.bookings ?? [], site: (j.site ?? "GGN") as PlanSite, contract_kva: j.contract_kva ?? 1000,
             defaults: j.inputs_used && { rooms: j.inputs_used.rooms, guests: j.inputs_used.guests, covers: j.inputs_used.covers },
             not_counted_inr: j.not_counted_inr, cv_rmse_pct: j.models?.cv_rmse_pct };
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
           weather: temps ? "Open-Meteo hourly forecast (in the browser)" : "typical temperatures for this date", bookings, site: "GGN", contract_kva: 1000 };
}

/** The API's plan, else the offline estimate. A 422 (e.g. a date outside the plan range) is not retried offline: its message is the answer. */
export async function getPlan(req: PlanRequest, offline: { day: PlanDay | null; temps: number[] | null; cal: RiskCal | null }): Promise<PlanResult> {
  try {
    return await apiPlan(req);
  } catch (e) {
    const err = e as Error & { status?: number };
    if (!offline.day || (req.site ?? "GGN") !== "GGN") throw err;              // Jaipur / Goa: no offline estimate
    const why = err.name === "AbortError" ? "The planning service did not answer within 4 seconds, so this is an offline estimate worked out in your browser."
      : err.status === 422 ? `The planning service could not plan this: ${err.message}`
      : "The planning service could not be reached, so this is an offline estimate worked out in your browser.";
    return offlinePlan(offline.day, req, offline.temps, offline.cal, why);
  }
}

// ---- plan vs actual and plan savings (API only: the sub-meter readings are not shipped to the browser) ----
import type { Alert } from "./data";

export interface CheckStep {
  id: string; group: string; start: string; end: string; setting: string; equipment: string; status: string; reason?: string;
  hours_checked: number; hours_differed: string[]; extra_kwh: number; extra_inr: number; planned_inr: number; verified_inr: number; what_was_checked: string;
  would_have_saved_inr: number;          // steps not approved / suggested only: shown in grey, never counted
}
export interface CheckSummary { steps: number; approved: number; due: number; not_approved: number; suggested: number; would_have_saved_inr: number;
  followed: number; partly: number; not_followed: number; not_yet_due: number; cant_tell: number;
  skipped?: number; planned_inr: number; verified_inr: number; missed_inr: number }
export interface CheckResult { date: string; as_of: string; source: string; honesty: string; notes: string[]; steps: CheckStep[]; alerts: Alert[];
  covered: Record<string, number[]>; summary: CheckSummary }
export interface SavingsDay { date: string; site?: PlanSite; source: string; planned_inr: number; verified_inr: number; missed_inr: number; followed: number; partly: number;
  not_followed: number; due: number; steps: number; covered: Record<string, number[]>; deviations: number }
export interface SavingsResult { month: string; as_of: string; honesty: string; days: SavingsDay[]; method: string;
  totals: { planned_inr: number; verified_inr: number; missed_inr: number; days: number; saved_days: number; would_have_saved_inr: number; approved_steps: number } }

async function post<T>(path: string, body: unknown, timeoutMs: number): Promise<T | null> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(`/api/${path}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body), signal: ctrl.signal });
    if (!r.ok || !(r.headers.get("content-type") ?? "").includes("json")) return null;
    return (await r.json()) as T;
  } catch { return null; } finally { clearTimeout(t); }
}

/** Plan vs actual for a day, up to `asOf` (the server never goes past the current IST hour). actions: the saved plan's steps
 *  (checkActions) or the suggested plan shown on the page (planSource "suggested"); omitted = the API's own suggested plan. */
export function checkPlan(date: string, asOf: string, actions?: unknown[], planSource?: "saved" | "suggested", site: PlanSite = "GGN") {
  return post<CheckResult>("check", { date, site, as_of: asOf, actions, plan_source: planSource }, 8000);
}
/** Planned vs verified plan ₹ for a month, day by day up to `asOf`; saved: {date: steps} for days with a saved plan. */
export function monthSavings(month: string, asOf: string, saved: Record<string, unknown[]> = {}, site: PlanSite = "GGN") {
  return post<SavingsResult>("savings", { month, site, as_of: asOf, saved }, 20000);
}
