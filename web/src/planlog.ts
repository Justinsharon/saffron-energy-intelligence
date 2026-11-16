// The operating-plan audit log (brief: any simulated automation needs an override and an audit log). Pure functions, shared by the
// Netlify function (web/netlify/functions/plans.ts, stored in the GitHub Gist as plans.json) and the browser's device-only fallback.
// Entries are only ever appended: a submitted plan is a new version, and every approve / skip / edit is a log row with who and when.
import { validate, type Action, type Booking } from "./plan";

export interface PlanInputs { rooms: number; guests: number; covers: number; bookings: Booking[]; notes: string; temps_source: string }
export interface SavedAction extends Action { id: string }
export interface Version { n: number; at: string; by: string; inputs: PlanInputs; actions: SavedAction[]; total_inr: number }
export interface LogRow { at: string; by: string; event: "submit" | "approve" | "skip" | "edit" | "done" | "cant"; version?: number; action_id?: string; reason?: string; start?: string; end?: string }
export interface Entry { versions: Version[]; log: LogRow[] }
export interface PlanView { date: string; storage: "gist" | "device"; plan: Version | null; decisions: Record<string, LogRow>;
  duty: Record<string, LogRow>;                         // the duty engineer's latest "done" / "can't do" per approved step (never changes the approval)
  edits: Record<string, { start: string; end: string; by: string; at: string; reason?: string }>; log: LogRow[] }

/** Storage key: Gurugram plans keep their date key (plans saved before Jaipur and Goa had plans); the others are "<date>@<SITE>". */
export const planKey = (date: string, site: string = "GGN") => (site === "GGN" ? date : `${date}@${site}`);
export const istStamp = () => new Date(Date.now() + 5.5 * 3.6e6).toISOString().slice(0, 16).replace("T", " ");
const HH = /^\d{2}:00( \(next day\))?$/;

/** Apply one submitted event to a day's entry. Throws (with a plain message) on anything the guardrails or the log rules forbid. */
export function applyEvent(entry: Entry | undefined, body: Record<string, any>, at: string): Entry {
  const e: Entry = entry ? { versions: [...entry.versions], log: [...entry.log] } : { versions: [], log: [] };
  const by = String(body.by ?? "").trim().slice(0, 80);
  if (!by) throw new Error("Enter your name first: every plan and decision is logged with who made it.");
  const ev = body.event;
  if (ev === "submit") {
    const actions = (body.actions ?? []) as SavedAction[];
    if (!Array.isArray(actions) || !actions.length) throw new Error("The plan has no actions.");
    const site = String(body.site ?? "GGN");
    if (!["GGN", "JAI", "GOA"].includes(site)) throw new Error("Unknown hotel.");
    for (const a of actions) if ((a.site ?? "GGN") !== site) throw new Error("The plan's steps are for another hotel.");
    validate(actions);                                  // the same guardrails as the plan engine: never store a plan that breaks one
    const n = e.versions.length + 1;
    const total = actions.reduce((s, a) => s + (Number(a.saving_inr) || 0), 0);
    e.versions.push({ n, at, by, inputs: body.inputs, actions, total_inr: total });
    e.log.push({ at, by, event: "submit", version: n });
    return e;
  }
  if (!["approve", "skip", "edit", "done", "cant"].includes(ev)) throw new Error("Unknown event.");
  const v = e.versions.at(-1);
  if (!v) throw new Error("Save the plan before approving or skipping actions.");
  const a = v.actions.find((x) => x.id === body.action_id);
  if (!a) throw new Error("That action is not in the saved plan; save the updated plan first.");
  const row: LogRow = { at, by, event: ev, version: v.n, action_id: a.id };
  if (ev === "done" || ev === "cant") {
    // the duty engineer reports on a step the chief engineer approved; a step that was never approved is not theirs to act on
    const last = [...e.log].reverse().find((r) => r.version === v.n && r.action_id === a.id && (r.event === "approve" || r.event === "skip"));
    if (last?.event !== "approve") throw new Error("Only approved steps can be marked done or can't do.");
    if (ev === "cant") {
      const reason = String(body.reason ?? "").trim().slice(0, 500);
      if (!reason) throw new Error("Say why it can't be done (needed for the log).");
      row.reason = reason;
    }
  }
  if (ev === "skip") {
    const reason = String(body.reason ?? "").trim().slice(0, 500);
    if (!reason) throw new Error("Give a short reason for skipping.");
    row.reason = reason;
  }
  if (ev === "edit") {
    const start = String(body.start ?? ""), end = String(body.end ?? "");
    if (!HH.test(start) || !HH.test(end)) throw new Error("Times must be whole hours, e.g. 08:00.");
    const h = (t: string) => Number(t.slice(0, 2)) + (t.includes("next day") ? 24 : 0);
    if (h(end) <= h(start)) throw new Error("The end must be after the start.");
    if (a.group === "ahu" && a.start_h != null && a.start_h - h(start) > 2) throw new Error("Banquet AHUs may not start more than 2 h before the event.");
    row.start = start; row.end = end;
    if (body.reason) row.reason = String(body.reason).slice(0, 500);
  }
  e.log.push(row);
  return e;
}

/** What the page shows: the latest version, each action's latest approve/skip, and its latest edited time (for that version). */
export function view(date: string, entry: Entry | undefined, storage: PlanView["storage"]): PlanView {
  const plan = entry?.versions.at(-1) ?? null;
  const decisions: PlanView["decisions"] = {}, edits: PlanView["edits"] = {}, duty: PlanView["duty"] = {};
  for (const r of entry?.log ?? []) {
    if (!plan || r.version !== plan.n || !r.action_id) continue;
    if (r.event === "approve" || r.event === "skip") decisions[r.action_id] = r;
    if (r.event === "done" || r.event === "cant") duty[r.action_id] = r;
    if (r.event === "edit" && r.start && r.end) edits[r.action_id] = { start: r.start, end: r.end, by: r.by, at: r.at, reason: r.reason };
  }
  return { date, storage, plan, decisions, duty, edits, log: entry?.log ?? [] };
}

/** The saved plan as it should be checked against the meters: edited times applied, and each step's latest approve / skip attached
 *  (a skipped step is a recorded decision, not a deviation). */
export function checkActions(v: PlanView): (SavedAction & { decision?: string; decision_reason?: string })[] {
  if (!v.plan) return [];
  return v.plan.actions.map((a) => {
    const ed = v.edits[a.id], d = v.decisions[a.id];
    return { ...a, start: ed?.start ?? a.start, end: ed?.end ?? a.end, decision: d?.event, decision_reason: d?.reason };
  });
}
