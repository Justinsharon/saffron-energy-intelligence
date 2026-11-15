// Browser side of plan storage: the plans function (shared, in the gist) when it is reachable; otherwise this device only, with the
// same log rules (planlog.ts), and the page says so. The planner's name is entered once and kept on this device.
import { applyEvent, istStamp, view, type Entry, type PlanView } from "./planlog";

const LOCAL = "plans_local";
export function plannerName(): string {
  try { return localStorage.getItem("planner") ?? localStorage.getItem("rater") ?? ""; } catch { return ""; }
}
export function setPlannerName(n: string) { try { localStorage.setItem("planner", n.trim()); } catch { /* private window */ } }

function localAll(): Record<string, Entry> { try { return JSON.parse(localStorage.getItem(LOCAL) || "{}"); } catch { return {}; } }
function localSave(a: Record<string, Entry>) { try { localStorage.setItem(LOCAL, JSON.stringify(a)); } catch { /* ignore */ } }

async function viaFunction(init?: RequestInit, date?: string): Promise<PlanView | { error: string } | null> {
  try {
    const r = await fetch(`/.netlify/functions/plans${date ? `?date=${date}` : ""}`, init);
    if (!(r.headers.get("content-type") ?? "").includes("json")) return null;          // dev server / no functions
    const j = await r.json();
    if (r.status === 503) return null;                                              // storage not configured
    if (!r.ok) return { error: j.error ?? `Error ${r.status}` };
    return j as PlanView;
  } catch { return null; }
}

export async function loadPlan(date: string): Promise<PlanView> {
  const r = await viaFunction(undefined, date);
  if (r && !("error" in r)) return r;
  return view(date, localAll()[date], "device");
}

/** Submit a plan or a decision. Returns the new view, or throws with the reason it was refused. */
export async function postPlan(body: Record<string, unknown>): Promise<PlanView> {
  const r = await viaFunction({ method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  if (r && "error" in r) throw new Error(r.error);
  if (r) return r;
  const all = localAll();
  const date = String(body.date);
  all[date] = applyEvent(all[date], body, istStamp());
  localSave(all);
  return view(date, all[date], "device");
}
