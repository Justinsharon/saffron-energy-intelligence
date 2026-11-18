// Plant Room (simulation) shared state: GET /.netlify/functions/plant?date=YYYY-MM-DD&site=GGN returns the day's approved plan (from the
// plans log), the steps applied in the Plant Room, the active / fixed demo faults, the latest readings snapshot and the audit log.
// POST {date, site, event: sync (take in Done / Can't do from the plans log) | fault | clearFault | readings | reset, by, simHour, ...} records one event (web/src/plant/store.ts).
// Stored in Netlify Blobs (store "saffron", key plant_state.json), next to the plan log (netlify/lib/gist.ts): { "<date>@GGN": {...} }. SIMULATION ONLY: nothing here controls
// equipment, and simulated readings never feed savings, bills or the live feed.
import { configured, readFiles, withRetry, writeJSON } from "../lib/gist";
import { checkActions, planKey, view, type Entry } from "../../src/planlog";
import { applyPlantEvent, empty, plantKey, type PlantEntry, type PlantView } from "../../src/plant/store";
import { istStamp } from "../../src/planlog";

const FILE = "plant_state.json";
const DATE = /^\d{4}-\d{2}-\d{2}$/;

async function both() {
  const f = await readFiles({ [FILE]: {} as Record<string, PlantEntry>, "plans.json": {} as Record<string, Entry> });
  return { all: f[FILE] as Record<string, PlantEntry>, plans: f["plans.json"] as Record<string, Entry> };
}
function approvedPlan(plans: Record<string, Entry>, date: string) {
  const v = view(date, plans[planKey(date, "GGN")], "gist");
  if (!v.plan) return null;
  return { version: v.plan.n, by: v.plan.by, at: v.plan.at, inputs: v.plan.inputs, steps: checkActions(v).filter((a) => a.decision === "approve"), duty: v.duty };
}

function out(date: string, e: PlantEntry | undefined, plan: PlantView["plan"]): PlantView {
  return { date, site: "GGN", exists: !!e && (e.audit.length > 0 || !!e.readings), storage: process.env.SAFFRON_MEMORY_STORE === "1" ? "memory (dev)" : "blobs",
           plan, ...(e ?? empty()) };
}

export default async (req: Request) => {
  if (!configured()) return Response.json({ error: "Shared storage is not set up (GITHUB_TOKEN, RATINGS_GIST_ID).", storage: "not configured" }, { status: 503 });
  try {
    const u = new URL(req.url);
    if (req.method === "GET") {
      // ?date=D (one view) or ?dates=D1,D2 (several views from one gist read: the app watches today and tomorrow)
      const many = u.searchParams.get("dates");
      const dates = (many ?? u.searchParams.get("date") ?? "").split(",").slice(0, 3);
      if (!dates.every((d) => DATE.test(d)) || (u.searchParams.get("site") ?? "GGN").toUpperCase() !== "GGN")
        return Response.json({ error: "date=YYYY-MM-DD (or dates=D1,D2)&site=GGN (the Plant Room is Gurugram only)" }, { status: 400 });
      const { all, plans } = await both();
      const views = dates.map((d) => out(d, all[plantKey(d)], approvedPlan(plans, d)));
      return Response.json(many ? { views } : views[0], { headers: { "cache-control": "no-store" } });
    }
    if (req.method !== "POST") return new Response("Method not allowed", { status: 405 });
    const b = await req.json();
    if (!DATE.test(String(b.date ?? "")) || String(b.site ?? "GGN").toUpperCase() !== "GGN")
      return Response.json({ error: "date=YYYY-MM-DD, site=GGN" }, { status: 400 });
    const key = plantKey(b.date);
    const { all, plan, r } = await withRetry(async () => {
      const { all, plans } = await both();
      const plan = approvedPlan(plans, b.date);
      const r = applyPlantEvent(all[key], b, istStamp(), plan?.steps ?? [], plan?.duty);
      if (r.entry !== all[key]) { all[key] = r.entry; await writeJSON(FILE, all); }
      return { all, plan, r };
    });
    const body = out(b.date, all[key], plan);
    return r.error ? Response.json({ ...body, error: r.error }, { status: 400 }) : Response.json(body);
  } catch (e) {
    return Response.json({ error: String((e as Error).message ?? e) }, { status: 502 });
  }
};
