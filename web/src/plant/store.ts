// Plant Room shared state and audit log. Pure functions, used by the Netlify function (web/netlify/functions/plant.ts, stored in the same
// private gist as the plans, file plant_state.json) and by the tests. SIMULATION ONLY: nothing here touches real equipment.
// Rules (brief: any simulated automation needs an override and an audit log):
//   - nothing changes without a person: every event needs `by`; there is no automatic apply;
//   - only steps APPROVED on Tomorrow's plan can be applied or overridden; monitored-only systems can never be;
//   - an override needs a reason and passes the same guardrails as the plan (never CHW < 6.5 °C); a refused override is logged too;
//   - every apply / override / fault / clear / reset is appended to the audit log (who, when, what, why); readings are the latest snapshot only.
import { FAULTS, isMonitored, overrideError, type ActiveFault, type Applied, type FaultType, type MeterRow } from "./model";
import type { SavedAction } from "../planlog";

export interface AuditRow { at: string; by: string; event: string; what: string; why?: string; simHour?: number; stepId?: string; value?: string | number }
export interface Readings { simHour: number; at: string; kva: number; kw: number; values: Record<string, number | string>; recent: MeterRow[]; lastFix: number | null }
export interface PlantEntry { applied: Record<string, Applied>; faults: ActiveFault[]; readings: Readings | null; audit: AuditRow[]; lastFix: number | null; updated: string }
export interface PlantView extends PlantEntry { date: string; site: string; exists: boolean; storage: string;
  plan: { version: number; by: string; at: string; inputs: unknown; steps: (SavedAction & { decision?: string; decision_reason?: string })[] } | null }

export const empty = (): PlantEntry => ({ applied: {}, faults: [], readings: null, audit: [], lastFix: null, updated: "" });
export const AUDIT_KEEP = 500;
const simHourOf = (x: unknown) => { const v = Number(x); return Number.isFinite(v) && v >= 0 && v <= 24 ? Math.round(v * 100) / 100 : null; };
export const hhmm = (t: number) => `${String(Math.floor(t)).padStart(2, "0")}:${String(Math.floor((t % 1) * 60 + 1e-6)).padStart(2, "0")}`;
const label = (a: SavedAction) => `${a.equipment}: ${a.setting} (${a.start.replace(" (next day)", "⁺¹")}–${a.end.replace(" (next day)", "⁺¹")})`;
export const activeFaults = (e: PlantEntry) => e.faults.filter((f) => f.fixedAt === undefined);

/** Apply one event. Returns the new entry, and `error` when the event was refused (a refused override is still logged). */
export function applyPlantEvent(entry: PlantEntry | undefined, body: Record<string, any>, at: string, approved: SavedAction[]): { entry: PlantEntry; error?: string } {
  const e: PlantEntry = entry ? { ...entry, applied: { ...entry.applied }, faults: entry.faults.map((f) => ({ ...f })), audit: [...entry.audit] } : empty();
  e.updated = at;
  const by = String(body.by ?? "").trim().slice(0, 80);
  const ev = String(body.event ?? "");
  const t = simHourOf(body.simHour);
  const log = (row: Omit<AuditRow, "at" | "by">) => { e.audit.push({ at, by, ...row }); if (e.audit.length > AUDIT_KEEP) e.audit = e.audit.slice(-AUDIT_KEEP); };
  const withReadings = () => { if (body.readings && typeof body.readings === "object") e.readings = sanitizeReadings(body.readings, at); };
  if (ev === "readings") { withReadings(); return { entry: e }; }
  if (!by) return { entry: entry ?? empty(), error: "Pick who you are first (Signed in as): every action is logged with a name." };
  if (t === null) return { entry: entry ?? empty(), error: "simHour must be a number of hours from 0 to 24." };

  if (ev === "apply" || ev === "override") {
    const id = String(body.stepId ?? "");
    if (isMonitored(id)) return { entry: entry ?? empty(), error: "Monitored only: kitchen exhaust, guest-room thermostats, lifts and fire / life safety are never controlled." };
    const step = approved.find((a) => a.id === id);
    if (!step) return { entry: entry ?? empty(), error: "Only steps approved on Tomorrow's plan can be applied. Approve it there first." };
    if (isMonitored(step.equipment)) return { entry: entry ?? empty(), error: "Monitored only: never controlled." };
    if (ev === "override") {
      const reason = String(body.reason ?? "").trim().slice(0, 500);
      const value = body.value;
      const err = !reason ? "Give a reason for the override (needed for the log)." : overrideError(step, value);
      if (err) {
        log({ event: "override refused", what: `${label(step)} → ${value}`, why: `${err}${reason ? ` (asked: ${reason})` : ""}`, simHour: t, stepId: id, value });
        withReadings();
        return { entry: e, error: err };
      }
      e.applied[id] = { stepId: id, kind: "override", by, at, simHour: t, value, reason };
      log({ event: "override", what: `${label(step)} → ${value}`, why: reason, simHour: t, stepId: id, value });
    } else {
      const fixes = activeFaults(e).filter((f) => FAULTS[f.type].fixGroup === step.group);
      const prev = e.applied[id];
      if (!prev || prev.kind === "override") e.applied[id] = { stepId: id, kind: "apply", by, at, simHour: t };
      log({ event: prev && prev.kind === "apply" ? "re-applied" : "apply", what: label(step), why: fixes.length ? `fix for: ${fixes.map((f) => FAULTS[f.type].label).join(", ")}` : undefined, simHour: t, stepId: id });
      for (const f of fixes) { f.fixedAt = t; f.fixedBy = by; }
    }
    e.lastFix = t;
  } else if (ev === "fault") {
    const type = String(body.type ?? "") as FaultType;
    if (!(type in FAULTS)) return { entry: entry ?? empty(), error: "Unknown fault." };
    if (activeFaults(e).some((f) => f.type === type)) return { entry: entry ?? empty(), error: "That fault is already active." };
    e.faults.push({ type, startedAt: t, by, at });
    log({ event: "fault injected (demo)", what: FAULTS[type].label, why: FAULTS[type].what, simHour: t });
  } else if (ev === "clearFault") {
    const act = activeFaults(e).filter((f) => !body.type || f.type === body.type);
    if (!act.length) return { entry: entry ?? empty(), error: "No active fault to clear." };
    for (const f of act) { f.fixedAt = t; f.fixedBy = by; }
    log({ event: "fault cleared", what: act.map((f) => FAULTS[f.type].label).join(", "), simHour: t });
    e.lastFix = t;
  } else if (ev === "reset") {
    const reason = String(body.reason ?? "").trim().slice(0, 300);
    e.applied = {}; e.faults = []; e.readings = null; e.lastFix = null;
    log({ event: "reset", what: "Simulation reset: all equipment back to habit, faults removed", why: reason || undefined, simHour: t });
    return { entry: e };
  } else {
    return { entry: entry ?? empty(), error: "Unknown event." };
  }
  withReadings();
  return { entry: e };
}

function sanitizeReadings(r: any, at: string): Readings {
  const recent = Array.isArray(r.recent) ? r.recent.slice(-24) : [];
  const num = (x: unknown) => (Number.isFinite(Number(x)) ? Number(x) : 0);
  return { simHour: num(r.simHour), at, kva: num(r.kva), kw: num(r.kw), values: typeof r.values === "object" && r.values ? r.values : {},
           recent, lastFix: r.lastFix === null || r.lastFix === undefined ? null : num(r.lastFix) };
}

/** Storage key per day and hotel (only Gurugram has a Plant Room). */
export const plantKey = (date: string, site = "GGN") => `${date}@${site}`;
