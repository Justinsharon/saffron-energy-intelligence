// Live feed: GET /.netlify/functions/feed?site=GGN&hours=48
// Readings (used vs expected, temperature, kVA), today's totals and peak, open and recent alerts, current meter faults and the latest
// bill issued, all as of the current hour in India. Rows after that hour are never returned. The live year (Oct 2026 - Sep 2027) comes
// from simulated meters (tools/make_live_year.py -> tools/run_live_year.py -> tools/export_web_data.py --live), bundled with this function.
import alerts from "./data/live_feed/alerts.json";
import faults from "./data/live_feed/faults.json";
import liveBills from "./data/live_feed/bills.json";
import origBills from "./data/bills.json";
import hGGN from "./data/live_feed/hourly_GGN.json";
import hJAI from "./data/live_feed/hourly_JAI.json";
import hGOA from "./data/live_feed/hourly_GOA.json";
import { feedFor, istNow } from "../../src/feedcore";
import type { Alert, Fault, Hourly, Recon, Site } from "../../src/data";

const HOURLY: Record<Site, Hourly> = { GGN: hGGN as Hourly, JAI: hJAI as Hourly, GOA: hGOA as Hourly };
const RECON = [...(origBills as { recon: Recon[] }).recon, ...(liveBills as { recon: Recon[] }).recon];

export default async (req: Request) => {
  if (req.method !== "GET") return Response.json({ error: "GET only." }, { status: 405 });
  const u = new URL(req.url);
  const site = (u.searchParams.get("site") ?? "GGN").toUpperCase() as Site;
  if (!HOURLY[site]) return Response.json({ error: "site must be GGN, JAI or GOA" }, { status: 400 });
  const hours = Math.min(168, Math.max(1, Math.round(Number(u.searchParams.get("hours") ?? 48)) || 48));
  const now = istNow();                                   // the server's clock, not the caller's: no peeking ahead
  const f = feedFor(site, now, hours, { hourly: HOURLY[site], alerts: alerts as unknown as Alert[], faults: faults as unknown as Fault[], recon: RECON });
  return Response.json(f, { headers: { "cache-control": "public, max-age=60" } });
};
