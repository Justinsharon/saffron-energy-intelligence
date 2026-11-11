// Live inputs: the real weather forecast (Open-Meteo, no key needed) and the precomputed day-ahead scenarios per future date.
import { useEffect, useState } from "react";
import { load, type Site, type ForecastDay } from "./data";

export const COORDS: Record<Site, [number, number]> = { GGN: [28.46, 77.03], JAI: [26.91, 75.79], GOA: [15.5, 73.83] };

export interface Weather { now: Record<Site, number | null>; daily: Record<Site, Record<string, { tmax: number; tmin: number }>> }

let wx: Promise<Weather | null> | null = null;
function fetchWeather(): Promise<Weather | null> {
  const sites = Object.keys(COORDS) as Site[];
  const url = "https://api.open-meteo.com/v1/forecast?" + new URLSearchParams({
    latitude: sites.map((s) => COORDS[s][0]).join(","), longitude: sites.map((s) => COORDS[s][1]).join(","),
    current: "temperature_2m", daily: "temperature_2m_max,temperature_2m_min", timezone: "Asia/Kolkata", forecast_days: "16",
  });
  return fetch(url).then((r) => (r.ok ? r.json() : null)).then((j) => {
    if (!j) return null;
    const arr = Array.isArray(j) ? j : [j];
    const out: Weather = { now: { GGN: null, JAI: null, GOA: null }, daily: { GGN: {}, JAI: {}, GOA: {} } };
    sites.forEach((s, i) => {
      const x = arr[i]; if (!x) return;
      out.now[s] = x.current?.temperature_2m ?? null;
      (x.daily?.time ?? []).forEach((d: string, k: number) => { out.daily[s][d] = { tmax: x.daily.temperature_2m_max[k], tmin: x.daily.temperature_2m_min[k] }; });
    });
    return out;
  }).catch(() => null);
}
/** undefined while loading, null if the weather service can't be reached. */
export function useWeather(): Weather | null | undefined {
  const [w, setW] = useState<Weather | null | undefined>(undefined);
  useEffect(() => { let live = true; (wx ??= fetchWeather()).then((x) => live && setW(x)); return () => { live = false; }; }, []);
  return w;
}

export interface LiveDay { date: string; template: string; template_tmax: number; hours: number[]; temps: number[]; guests: number[];
  grid: Record<string, { pred: number[]; risk: ForecastDay["risk"]; plan: ForecastDay["plan"] }>; stack_table: ForecastDay["stack_table"] }

export function useLiveIndex() {
  const [v, setV] = useState<Record<string, string> | null>(null);
  useEffect(() => { load<Record<string, string>>("live/index.json").then(setV).catch(() => setV({})); }, []);
  return v;
}
export function useLiveDay(date: string | null): LiveDay | null | undefined {
  const [v, setV] = useState<LiveDay | null | undefined>(undefined);
  useEffect(() => {
    let live = true; setV(undefined);
    if (date) load<LiveDay>(`live/${date}.json`).then((x) => live && setV(x)).catch(() => live && setV(null));
    return () => { live = false; };
  }, [date]);
  return v;
}
/** Pick the scenario for a temperature and guest count (nearest cell; temperatures outside the range are clamped and flagged). */
export function pickCell(d: LiveDay, tmax: number, guests: number): { f: ForecastDay; t: number; clamped: boolean } {
  const t = Math.round(tmax);
  const tt = Math.min(Math.max(t, d.temps[0]), d.temps[d.temps.length - 1]);
  const g = d.guests.reduce((b, x) => (Math.abs(x - guests) < Math.abs(b - guests) ? x : b), d.guests[0]);
  const c = d.grid[`${tt}|${g}`];
  return { f: { hours: d.hours, pred: c.pred, risk: c.risk, plan: c.plan, stack_table: d.stack_table }, t: tt, clamped: tt !== t };
}
