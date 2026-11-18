// Operating-plan storage and audit log (Gurugram, Jaipur, Goa; ?site=GGN|JAI|GOA, default GGN): GET /.netlify/functions/plans?date=YYYY-MM-DD returns the latest saved plan for that
// date with each action's latest decision and edit; POST {date, by, event: submit | approve | skip | edit, ...} appends to the log.
// Stored in the existing private gist as plans.json: { "<date>": { versions: [...], log: [...] } }. Nothing is ever deleted.
// The server stamps the time (IST) and re-checks the guardrails on every submitted plan and edit. Recommend only: no equipment is
// controlled from here; approving an action records that a person will carry it out.
import { configured, readJSON, withRetry, writeJSON } from "../lib/gist";
import { applyEvent, checkActions, isScenario, istStamp, planKey, view, type Entry } from "../../src/planlog";

const FILE = "plans.json";
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const SITES = new Set(["GGN", "JAI", "GOA"]);
const siteOf = (x: unknown) => { const s = String(x ?? "GGN").toUpperCase(); return SITES.has(s) ? s : null; };

export default async (req: Request) => {
  if (!configured()) return Response.json({ error: "Shared plan storage is not set up (GITHUB_TOKEN, RATINGS_GIST_ID).", storage: "not configured" }, { status: 503 });
  try {
    if (req.method === "GET" && new URL(req.url).searchParams.get("month")) {
      // every saved plan in a month, as it should be checked (edited times, approve / skip attached): for verified plan savings
      const month = new URL(req.url).searchParams.get("month") ?? "";
      const site = siteOf(new URL(req.url).searchParams.get("site"));
      if (!/^\d{4}-\d{2}$/.test(month) || !site) return Response.json({ error: "month=YYYY-MM&site=GGN|JAI|GOA" }, { status: 400 });
      const all = await readJSON<Record<string, Entry>>(FILE, {});
      const plans: Record<string, unknown[]> = {};
      for (const [k, e] of Object.entries(all)) {
        const d = k.slice(0, 10);
        if (d.startsWith(month) && k === planKey(d, site)) {
          const v = view(d, e, "gist");
          if (isScenario(v.plan?.inputs)) continue;                     // weather scenarios are what-ifs: never in plan savings or reports
          const a = checkActions(v); if (a.length) plans[d] = a;
        }
      }
      return Response.json({ month, site, plans, storage: "gist" });
    }
    if (req.method === "GET") {
      const date = new URL(req.url).searchParams.get("date") ?? "";
      const site = siteOf(new URL(req.url).searchParams.get("site"));
      if (!DATE.test(date) || !site) return Response.json({ error: "date=YYYY-MM-DD&site=GGN|JAI|GOA" }, { status: 400 });
      const all = await readJSON<Record<string, Entry>>(FILE, {});
      return Response.json(view(date, all[planKey(date, site)], "gist"));
    }
    if (req.method !== "POST") return new Response("Method not allowed", { status: 405 });
    const b = await req.json();
    const site = siteOf(b.site);
    if (!DATE.test(String(b.date ?? "")) || !site) return Response.json({ error: "date=YYYY-MM-DD, site=GGN|JAI|GOA" }, { status: 400 });
    const key = planKey(b.date, site);
    const res = await withRetry(async () => {
      const all = await readJSON<Record<string, Entry>>(FILE, {});
      let next: Entry;
      try { next = applyEvent(all[key], { ...b, site }, istStamp()); } catch (e) { return { error: String((e as Error).message ?? e) }; }
      all[key] = next;
      await writeJSON(FILE, all);
      return { next };
    });
    if ("error" in res) return Response.json({ error: res.error }, { status: 400 });
    return Response.json(view(b.date, res.next, "gist"));
  } catch (e) {
    return Response.json({ error: String((e as Error).message ?? e) }, { status: 502 });
  }
};
