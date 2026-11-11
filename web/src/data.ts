// Static data exported by tools/export_web_data.py. Every number shown in the UI comes from these files.
import { useEffect, useState } from "react";

export type Site = "GGN" | "JAI" | "GOA";
export const SITES: Site[] = ["GGN", "JAI", "GOA"];
export const SITE_NAME: Record<Site, string> = { GGN: "Gurugram", JAI: "Jaipur", GOA: "Goa" };

export interface Alert {
  id: string; site: Site; hotel: string; rule: string; title: string; severity: "High" | "Medium" | "Low";
  equipment: string; start: string; end: string; alert_time: string; flagged_h: number; duration_h: number; detect_lag_h: number;
  excess_kwh: number; cost: number; per_hour: number; per_day: number; cost_basis: "per_day" | "per_occurrence"; cost_note: string;
  channel: "Alert" | "Daily digest"; repeat_30d: number; inferred_note: string; evidence: string; cause: string; action: string;
  guardrail: string; guard_text: string; post_hoc: boolean; text: string;
  chart: { t: string[]; actual: number[]; baseline: number[]; signals: Record<string, (number | null)[]> };
}
export interface Fault { site: Site; hotel: string; start: string; end: string; kind: string; detected_at: string; evidence: string; duration_h: number; handling: string }
export interface Hotel {
  code: Site; name: string; rooms: number; contract_kva: number; annual_cost: number;
  daily: { date: string; actual: number; baseline: number; tmax: number; rooms: number; guests: number; peak_kva: number }[];
}
export interface Hourly { t: string[]; a: number[]; b: number[]; temp: number[]; kva: number[]; ev: number[]; f: number[] }
export interface Recon {
  site: Site; month: string; status: string; note: string; billed_total: number; tariff_check_total: number; tariff_check_max_gap: number;
  meter_kvah: number; billed_kvah: number; meter_gap_pct: number; corrected_total: number; billed_minus_corrected: number; md_kva: number;
  billing_demand_kva: number; pf: number; pf_source: string; [k: string]: number | string;
}
export interface Bills { recon: Recon[]; components: Record<Site, { billing_month: string; component: string; inr: number }[]>; unused_demand: Record<Site, { cd: number; floor: number; max_md: number; months_on_floor: number; paid_for_unused_inr: number }> }
export interface BillChange {
  site: Site; a: string; b: string; bill_a: number; bill_b: number; delta: number; groups: Record<string, number>;
  lines: { driver: string; group: string; kwh: number | null; inr: number }[];
  context: { cdh_A: number; cdh_B: number; tmax_A: number; tmax_B: number; rooms_A: number; rooms_B: number; event_guests_A: number; event_guests_B: number; md_A: number; md_B: number; pf_A: number; pf_B: number };
  waste_kwh_b: Record<string, number>;
}
export interface Risk { raw_peak: number; bias: number; peak: number; hour: number; upper: number; p_exceed: number | null; stack_increment: number; stack_peak: number; stack_basis: string; level: "OK" | "STACKING WATCH" | "WARNING" | "BREACH RISK"; why: string }
export interface PlanRow { load: string; action: string; basis: string; kw_moved: number; relief_kva: number; demand_after_kva: number; reaches_target: boolean }
export interface StackRow { load: string; actual_kw?: number; typical_kw?: number; extra_kw: number }
export interface ForecastDay { hours: number[]; pred: number[]; actual?: number[]; risk: Risk; plan: PlanRow[] | null; stack_table: StackRow[] }
export interface WhatIf { template: string; temps: number[]; guests: number[]; grid: Record<string, ForecastDay> }
export interface Measure { site: Site; hotel: string; measure: string; category: string; inr: number; pct_of_site_bill: number; basis: string; safety: string; confidence: string }
export interface OptionC { cv_rmse_hourly: number; nmbe: number; cv_rmse_monthly: number; fsu_at_8pct: number; min_verifiable_pct: number; monthly: { month: string; actual: number; baseline: number }[] }
export interface Savings { measures: Measure[]; not_sized: string[]; option_c: Record<Site, OptionC>; group_bill: number; target: [number, number] }
export interface Quality {
  frozen: Record<string, number>; full: Record<string, number>; tests: { id: string; result: string; detail: string }[];
  bms: { alarms: number; precision: number; recall: number; closed_no_action: number; median_action_h: number };
  baseline: Record<Site, [number, number]>; forecast: { mape: number; within5: number; within10: number };
}

const cache = new Map<string, Promise<unknown>>();
export function load<T>(name: string): Promise<T> {
  if (!cache.has(name)) cache.set(name, fetch(`/data/${name}`).then((r) => { if (!r.ok) throw new Error(`${name}: ${r.status}`); return r.json(); }));
  return cache.get(name) as Promise<T>;
}
export function useData<T>(name: string | null): T | null {
  const [v, setV] = useState<T | null>(null);
  useEffect(() => { let live = true; setV(null); if (name) load<T>(name).then((x) => live && setV(x)); return () => { live = false; }; }, [name]);
  return v;
}
