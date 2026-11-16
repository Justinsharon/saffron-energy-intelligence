// Browser side of plan storage: the plans function (shared, in the gist) when it is reachable; otherwise this device only, with the
// same log rules (planlog.ts), and the page says so. The planner's name is entered once and kept on this device.
import { applyEvent, checkActions, istStamp, planKey, view, type Entry, type PlanView } from "./planlog";
import type { PlanSite } from "./plan";

const LOCAL = "plans_local";
export function plannerName(): string {
  try { return localStorage.getItem("planner") ?? localStorage.getItem("rater") ?? ""; } catch { return ""; }
}
export function setPlannerName(n: string) { try { localStorage.setItem("planner", n.trim()); } catch { /* private window */ } }

function localAll(): Record<string, Entry> { try { return JSON.parse(localStorage.getItem(LOCAL) || "{}"); } catch { return {}; } }
function localSave(a: Record<string, Entry>) { try { localStorage.setItem(LOCAL, JSON.stringify(a)); } catch { /* ignore */ } }

async function viaFunction(init?: RequestInit, date?: string, site: PlanSite = "GGN"): Promise<PlanView | { error: string } | null> {
  try {
    const r = await fetch(`/.netlify/functions/plans${date ? `?date=${date}&site=${site}` : ""}`, init);
    if (!(r.headers.get("content-type") ?? "").includes("json")) return null;          // dev server / no functions
    const j = await r.json();
    if (r.status === 503) return null;                                              // storage not configured
    if (!r.ok) return { error: j.error ?? `Error ${r.status}` };
    return j as PlanView;
  } catch { return null; }
}

export async function loadPlan(date: string, site: PlanSite = "GGN"): Promise<PlanView> {
  const r = await viaFunction(undefined, date, site);
  if (r && !("error" in r)) return r;
  return view(date, localAll()[planKey(date, site)], "device");
}

/** Submit a plan or a decision. Returns the new view, or throws with the reason it was refused. */
export async function postPlan(body: Record<string, unknown>): Promise<PlanView> {
  const r = await viaFunction({ method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  if (r && "error" in r) throw new Error(r.error);
  if (r) return r;
  const all = localAll();
  const date = String(body.date), key = planKey(date, (body.site as PlanSite) ?? "GGN");
  all[key] = applyEvent(all[key], body, istStamp());
  localSave(all);
  return view(date, all[key], "device");
}

/** Every saved plan in a month, ready to check (edited times, decisions attached): shared storage, else this device. */
export async function loadMonthPlans(month: string, site: PlanSite = "GGN"): Promise<Record<string, unknown[]>> {
  try {
    const r = await fetch(`/.netlify/functions/plans?month=${month}&site=${site}`);
    if ((r.headers.get("content-type") ?? "").includes("json") && r.ok) return (await r.json()).plans ?? {};
  } catch { /* fall back to this device */ }
  const out: Record<string, unknown[]> = {};
  for (const [k, e] of Object.entries(localAll())) {
    const d = k.slice(0, 10);
    if (d.startsWith(month) && k === planKey(d, site)) { const a = checkActions(view(d, e, "device")); if (a.length) out[d] = a; }
  }
  return out;
}
