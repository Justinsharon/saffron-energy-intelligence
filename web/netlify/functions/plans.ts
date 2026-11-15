// Operating-plan storage and audit log (Gurugram): GET /.netlify/functions/plans?date=YYYY-MM-DD returns the latest saved plan for that
// date with each action's latest decision and edit; POST {date, by, event: submit | approve | skip | edit, ...} appends to the log.
// Stored in the existing private gist as plans.json: { "<date>": { versions: [...], log: [...] } }. Nothing is ever deleted.
// The server stamps the time (IST) and re-checks the guardrails on every submitted plan and edit. Recommend only: no equipment is
// controlled from here; approving an action records that a person will carry it out.
import { configured, readJSON, writeJSON } from "../lib/gist";
import { applyEvent, istStamp, view, type Entry } from "../../src/planlog";

const FILE = "plans.json";
const DATE = /^\d{4}-\d{2}-\d{2}$/;

export default async (req: Request) => {
  if (!configured()) return Response.json({ error: "Shared plan storage is not set up (GITHUB_TOKEN, RATINGS_GIST_ID).", storage: "not configured" }, { status: 503 });
  try {
    if (req.method === "GET") {
      const date = new URL(req.url).searchParams.get("date") ?? "";
      if (!DATE.test(date)) return Response.json({ error: "date=YYYY-MM-DD" }, { status: 400 });
      const all = await readJSON<Record<string, Entry>>(FILE, {});
      return Response.json(view(date, all[date], "gist"));
    }
    if (req.method !== "POST") return new Response("Method not allowed", { status: 405 });
    const b = await req.json();
    if (!DATE.test(String(b.date ?? ""))) return Response.json({ error: "date=YYYY-MM-DD" }, { status: 400 });
    const all = await readJSON<Record<string, Entry>>(FILE, {});
    let next: Entry;
    try { next = applyEvent(all[b.date], b, istStamp()); } catch (e) { return Response.json({ error: String((e as Error).message ?? e) }, { status: 400 }); }
    all[b.date] = next;
    await writeJSON(FILE, all);
    return Response.json(view(b.date, next, "gist"));
  } catch (e) {
    return Response.json({ error: String((e as Error).message ?? e) }, { status: 502 });
  }
};
