// Browser side of the Plant Room link, used by the Plant Room screen and by the Saffron app (Today, Tomorrow's plan).
// State: the plant function (shared gist) when reachable; otherwise this device only (same rules, web/src/plant/store.ts), and the
// screen says so. Check: the REAL plan API /check with the simulated meter rows (`meters`, additive); if it fails, takes longer than 8 s,
// or is an older build that ignores `meters`, the same rules run in the browser (web/src/plant/check.ts). The path used is logged.
// Simulated readings never feed savings, bills or the live feed: nothing here writes anywhere but plant_state.
import { useEffect, useRef, useState } from "react";
import type { Alert } from "../data";
import { istStamp, type SavedAction } from "../planlog";
import { loadPlan, postPlan } from "../planStore";
import { checkActions } from "../planlog";
import type { PlanDay } from "../plan";
import { checkDay } from "./check";
import { applyPlantEvent, empty, plantKey, type PlantEntry, type PlantView } from "./store";

const LOCAL = "plant_local";
const localAll = (): Record<string, PlantEntry> => { try { return JSON.parse(localStorage.getItem(LOCAL) || "{}"); } catch { return {}; } };
const localSave = (a: Record<string, PlantEntry>) => { try { localStorage.setItem(LOCAL, JSON.stringify(a)); } catch { /* private window */ } };

async function deviceView(date: string): Promise<PlantView> {
  const v = await loadPlan(date, "GGN").catch(() => null);
  const plan = v?.plan ? { version: v.plan.n, by: v.plan.by, at: v.plan.at, inputs: v.plan.inputs, steps: checkActions(v).filter((a) => a.decision === "approve"), duty: v.duty } : null;
  const e = localAll()[plantKey(date)];
  return { date, site: "GGN", exists: !!e && (e.audit.length > 0 || !!e.readings), storage: "device", plan, ...(e ?? empty()) };
}

/** Several days in one call (one gist read); this device's copies when the function is unavailable. */
export async function getPlants(dates: string[]): Promise<PlantView[]> {
  try {
    const r = await fetch(`/.netlify/functions/plant?dates=${dates.join(",")}&site=GGN`, { cache: "no-store" });
    if ((r.headers.get("content-type") ?? "").includes("json") && r.ok) return (await r.json()).views as PlantView[];
  } catch { /* fall back to this device */ }
  return Promise.all(dates.map(deviceView));
}

export async function getPlant(date: string): Promise<PlantView> {
  try {
    const r = await fetch(`/.netlify/functions/plant?date=${date}&site=GGN`, { cache: "no-store" });
    if ((r.headers.get("content-type") ?? "").includes("json") && r.status !== 503) {
      const j = await r.json();
      if (r.ok) return j as PlantView;
    }
  } catch { /* fall back to this device */ }
  return deviceView(date);
}

/** Post one event. Returns the new view, and `error` when the event was refused (e.g. an override below 6.5 °C). */
export async function postPlant(body: Record<string, unknown>): Promise<{ view: PlantView; error?: string }> {
  try {
    const r = await fetch("/.netlify/functions/plant", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ site: "GGN", ...body }) });
    if ((r.headers.get("content-type") ?? "").includes("json") && r.status !== 503) {
      const j = await r.json();
      if (r.ok || r.status === 400) return { view: j as PlantView, error: j.error };
      throw new Error(j.error ?? `Error ${r.status}`);
    }
  } catch (e) { if (!(e instanceof TypeError)) throw e; }
  const date = String(body.date);
  const v = await deviceView(date);
  const all = localAll();
  const res = applyPlantEvent(all[plantKey(date)], body, istStamp(), (v.plan?.steps ?? []) as SavedAction[], v.plan?.duty);
  all[plantKey(date)] = res.entry; localSave(all);
  return { view: { ...v, ...res.entry, exists: true }, error: res.error };
}

// ---- the check: real API first, browser rules as the fallback ----
export interface PlantCheck { alerts: Alert[]; path: "api" | "local"; ms: number; why?: string; asOf: string }
const CHECK_TIMEOUT_MS = 8000;
const dayCache: Record<string, PlanDay> = {};
async function planDay(date: string): Promise<PlanDay> {
  if (!dayCache[date]) dayCache[date] = await (await fetch(`/data/plan/${date}.json`)).json();
  return dayCache[date];
}
export const simAsOf = (date: string, simHour: number) => `${date}T${String(Math.min(23, Math.floor(simHour))).padStart(2, "0")}:${String(Math.floor((simHour % 1) * 60)).padStart(2, "0")}`;

export async function checkPlant(v: PlantView, apiBase = "/api"): Promise<PlantCheck | null> {
  const r = v.readings;
  if (!r || !v.plan || !r.recent.length) return null;
  const asOf = simAsOf(v.date, r.simHour);
  const actions = v.plan.steps;
  const t0 = performance.now();
  let why = "";
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), CHECK_TIMEOUT_MS);
  try {
    const res = await fetch(`${apiBase}/check`, { method: "POST", headers: { "content-type": "application/json" }, signal: ctrl.signal,
      body: JSON.stringify({ date: v.date, site: "GGN", as_of: asOf, actions, plan_source: "saved", meters: r.recent }) });
    const j = res.ok && (res.headers.get("content-type") ?? "").includes("json") ? await res.json() : null;
    if (j && j.meters_source === "simulated") {
      const ms = Math.round(performance.now() - t0);
      console.info(`[plant room] /check path: plan API at ${apiBase} (${ms} ms), ${j.alerts.length} alert(s)`);
      return { alerts: j.alerts as Alert[], path: "api", ms, asOf };
    }
    why = j ? "the API answered without checking the simulated readings (older build: redeploy it)" : `the API answered ${res.status}`;
  } catch (e) {
    why = (e as Error).name === "AbortError" ? `the API did not answer within ${CHECK_TIMEOUT_MS / 1000} s` : "the API could not be reached";
  } finally { clearTimeout(timer); }
  const day = await planDay(v.date);
  const local = checkDay(v.date, actions, r.recent, asOf, day.ref, day.tariff, day.pf);
  const ms = Math.round(performance.now() - t0);
  console.info(`[plant room] /check path: local rules in the browser (${why}; ${ms} ms), ${local.alerts.length} alert(s)`);
  return { alerts: local.alerts, path: "local", ms, why, asOf };
}

const addDay = (d: string, k: number) => { const x = new Date(`${d}T00:00:00Z`); x.setUTCDate(x.getUTCDate() + k); return x.toISOString().slice(0, 10); };
export const istToday = () => new Date(Date.now() + 5.5 * 3.6e6).toISOString().slice(0, 10);

/** The app's link: watch today's and tomorrow's Plant Room (every 5 s while a session exists, every 15 s otherwise) and check the
 *  latest simulated readings. Returns null when no Plant Room session exists for either day. */
export function usePlantLink(enabled = true): { view: PlantView; check: PlantCheck | null } | null {
  const [state, setState] = useState<{ view: PlantView; check: PlantCheck | null } | null>(null);
  const last = useRef("");
  useEffect(() => {
    if (!enabled) return;
    let on = true, timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      const today = istToday();
      const views = await getPlants([today, addDay(today, 1)]).catch(() => [] as PlantView[]);
      const live = views.filter((v): v is PlantView => !!v && v.exists).sort((a, b) => (b.updated > a.updated ? 1 : -1))[0];
      if (!on) return;
      if (!live) { setState(null); last.current = ""; }
      else {
        const sig = `${live.date}|${live.readings?.at}|${live.readings?.simHour}|${JSON.stringify(live.readings?.recent ?? [])}|${live.plan?.version}`;
        if (sig !== last.current) {
          last.current = sig;
          const c = await checkPlant(live).catch(() => null);
          if (on) setState({ view: live, check: c });
        } else setState((s) => (s ? { ...s, view: live } : { view: live, check: null }));
      }
      if (on) timer = setTimeout(tick, live ? 5000 : 15000);
    };
    tick();
    return () => { on = false; clearTimeout(timer); };
  }, [enabled]);
  return state;
}

/** Tomorrow's plan page: which steps were applied in the Plant Room for this date (polled every 10 s). */
export function usePlantApplied(date: string, site: string): PlantView["applied"] {
  const [applied, setApplied] = useState<PlantView["applied"]>({});
  useEffect(() => {
    setApplied({});
    if (site !== "GGN") return;
    let on = true, timer: ReturnType<typeof setTimeout>;
    const tick = async () => { const v = await getPlant(date).catch(() => null); if (on && v) setApplied(v.applied); if (on) timer = setTimeout(tick, 10000); };
    tick();
    return () => { on = false; clearTimeout(timer); };
  }, [date, site]);
  return applied;
}

/** "Reset demo for this day" on the simulator (same rules as tools/demo_reset.mjs): withdraw the saved plan only if a TEST name saved it,
 *  set aside a weather-scenario plan, and clear the simulator (fault, readings, Done steps; audit kept, marked superseded). Nothing is
 *  deleted and a plan saved under a real name is never touched. Returns one line per action for the page. */
export const DEMO_RESET_BY = "demo reset (presenter)";
export async function resetDemo(date: string, simHour: number): Promise<{ lines: string[]; view?: PlantView }> {
  const lines: string[] = [];
  const v = await loadPlan(date, "GGN");
  const p = v.plan;
  if (!p) lines.push("No saved plan for this day.");
  else if (p.inputs?.weather_mode && p.inputs.weather_mode !== "live") {
    await postPlan({ date, site: "GGN", event: "supersede", by: DEMO_RESET_BY, reason: "demo reset: the demo uses the live forecast" });
    lines.push(`Weather-scenario plan v${p.n} (${p.by}) set aside.`);
  } else if (/^TEST/i.test(p.by)) {
    await postPlan({ date, site: "GGN", event: "withdraw", by: DEMO_RESET_BY, reason: "demo reset from the meter simulator" });
    lines.push(`TEST plan v${p.n} (${p.by}) withdrawn, with its Done marks.`);
  } else lines.push(`Plan v${p.n} saved by ${p.by} kept (not a TEST name).`);
  const r = await postPlant({ date, event: "demoReset", by: DEMO_RESET_BY, simHour, reason: "Reset demo for this day (meter simulator)" });
  if (r.error) throw new Error(r.error);
  lines.push("Simulator cleared: no fault, no readings, every channel back on habit.");
  return { lines, view: await getPlant(date) };
}
