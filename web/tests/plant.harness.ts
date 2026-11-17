// Plant Room unit checks + fault scenarios, run in Node by tests/test_plant_room.py and tools/plant_cloud_check.py (bundled with esbuild).
// Input (argv[2]): { date, forecast, bookings, actions (the API plan's actions) }. Output (argv[3]): { unit: {...}, scenarios: [...] }.
// Each scenario = the meter rows the Saffron app would send to /check, plus what the browser fallback (plant/check.ts) finds on them.
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { actionId } from "../src/plan";
import { checkDay } from "../src/plant/check";
import { CONTROLLED, MONITORED, NOISE, checkWindow, equipOf, hourRow, noise, snapshot, type SimDay, type SimState } from "../src/plant/model";
import { applyPlantEvent, empty, type PlantEntry } from "../src/plant/store";
import { applyEvent, isScenario, view } from "../src/planlog";
import { costBreakdown } from "../src/plant/cost";

const inp = JSON.parse(readFileSync(process.argv[2], "utf8"));
const root = new URL("../public/data/", import.meta.url);
const read = (p: string) => JSON.parse(readFileSync(new URL(p, root), "utf8"));
const pd = read(`plan/${inp.date}.json`);
const steps = inp.actions.map((a: any) => ({ ...a, id: actionId(a), decision: "approve" }));
const day: SimDay = { date: inp.date, forecast: { kw: inp.forecast.kw, kva: inp.forecast.kva, tr: inp.forecast.tr, temp: inp.forecast.temp_c },
  steps, bookings: inp.bookings, profile: read(`plant/${inp.date}.json`), index: read("plant/index.json"), ref: pd.ref, tariff: pd.tariff, pf: pd.pf };
const BY = "TEST – Claude Code";
const ahu0 = () => steps.find((s: any) => s.group === "ahu");
let clock = 0;
const at = () => `2026-11-18 10:${String(clock++).padStart(2, "0")}`;
function ev(e: PlantEntry, body: Record<string, unknown>) { return applyPlantEvent(e, { by: BY, ...body }, at(), steps); }
const sim = (e: PlantEntry): SimState => ({ applied: e.applied, faults: e.faults });

// ---- unit checks ----
const unit: Record<string, boolean> = {};
// 1. noise stays within ±2.5 % of the curve
let worst = 0;
for (let m = 0; m < 24 * 60; m++) for (const k of ["main", "CH-1", "CH-3", "AHU-A", "LDY", "DHW", "tr"]) worst = Math.max(worst, Math.abs(noise(k, day.date, m)));
const base = empty();
for (let m = 0; m < 24 * 60; m += 7) {
  const t = m / 60, a = snapshot(day, sim(base), t), b = snapshot(day, sim(base), t, false);
  if (b.kva > 0) worst = Math.max(worst, Math.abs(a.kva / b.kva - 1));
  for (const id of ["CH-1", "CH-3", "LAUNDRY", "HP-DHW"] as const) if (b.equip[id].kw > 0.5) worst = Math.max(worst, Math.abs(a.equip[id].kw / b.equip[id].kw - 1));
}
assert.ok(worst <= NOISE + 1e-9, `noise ${worst}`); unit.noise_within_2_5_pct = true;
// 2. nothing changes without Apply: habit until a person applies; then the plan
const chw = steps.find((s: any) => s.group === "chw" && s.setpoint_c > 7);
assert.ok(chw, "the test day needs an 8.0 °C block");
const h = Number(chw.start.slice(0, 2)) + 1;
const before = snapshot(day, sim(base), h + 0.5, false);
assert.equal(before.setpoint, 7.0); assert.equal(before.equip["CH-3"].following === "plan" || before.equip["CH-1"].following === "plan", false);
const ap = ev(base, { event: "apply", stepId: chw.id, simHour: h });
assert.ok(!ap.error);
const after = snapshot(day, sim(ap.entry), h + 0.5, false);
assert.equal(after.setpoint, chw.setpoint_c);
const chKw = (s: typeof after) => s.equip["CH-1"].kw + s.equip["CH-3"].kw;
assert.ok(chKw(after) < chKw(before), "warmer chilled water must lower chiller kW");
assert.ok(after.kva < before.kva, "main kVA follows");
assert.equal(snapshot(day, sim(ap.entry), h - 0.5, false).setpoint, 7.0, "before the apply time the equipment still followed habit");
unit.habit_until_apply_then_plan = true;
// 3. CHW override below 6.5 °C refused, with the reason, and the refusal logged
const ref = ev(base, { event: "override", stepId: chw.id, value: 6.0, reason: "guest complaint", simHour: h });
assert.match(ref.error ?? "", /never below 6\.5/);
assert.equal(ref.entry.applied[chw.id], undefined);
assert.equal(ref.entry.audit.at(-1)?.event, "override refused");
const okOv = ev(base, { event: "override", stepId: chw.id, value: 7.5, reason: "guest complaint", simHour: h });
assert.ok(!okOv.error && okOv.entry.applied[chw.id].value === 7.5);
assert.ok(ev(base, { event: "override", stepId: chw.id, value: 7.5, reason: "", simHour: h }).error, "an override needs a reason");
unit.chw_below_6_5_refused = true;
// 4. monitored-only systems: never in a step, never accept an action; unapproved steps refused; a name is required
for (const m of MONITORED) {
  assert.ok(ev(base, { event: "apply", stepId: m.id, simHour: 1 }).error?.startsWith("Monitored only"));
  assert.ok(!CONTROLLED.some((c) => c.id === (m.id as string)));
}
for (const s of steps) for (const id of equipOf(s)) assert.ok(!MONITORED.some((m) => m.id === (id as string)));
assert.ok(ev(base, { event: "apply", stepId: "chillers|99:00|nothing", simHour: 1 }).error?.includes("approved"));
assert.ok(applyPlantEvent(base, { event: "apply", stepId: chw.id, simHour: 1 }, at(), steps).error?.includes("Signed in as"));
unit.monitored_only_no_actions = true;
// 5. every apply / override / fault / clear is in the audit log
let e = empty();
for (const s of steps) e = ev(e, { event: "apply", stepId: s.id, simHour: 6 }).entry;
e = ev(e, { event: "fault", type: "chw_low", simHour: 9 }).entry;
e = ev(e, { event: "clearFault", simHour: 10 }).entry;
assert.equal(e.audit.length, steps.length + 2);
assert.ok(e.audit.every((r) => r.by === BY && r.at && r.event && r.what));
unit.every_action_audited = true;

// 6. the meters move only when the duty engineer marks a step Done in the app (plans log), taken in at the current sim time
const doneAll = Object.fromEntries(steps.map((s: any) => [s.id, { event: "done", by: "Rahul", at: "2026-11-18 09:00" }]));
let sy = applyPlantEvent(empty(), { event: "sync", simHour: 6 }, at(), steps, doneAll).entry;
assert.equal(Object.keys(sy.applied).length, steps.length);
assert.ok(Object.values(sy.applied).every((a) => a.simHour === 6 && a.by === "Rahul"));
assert.equal(applyPlantEvent(sy, { event: "sync", simHour: 9 }, at(), steps, doneAll).entry.audit.length, sy.audit.length, "a report is taken in once");
const cant = { ...doneAll, [chw.id]: { event: "cant", by: "Rahul", at: "2026-11-18 09:05", reason: "guest complaint" } };
sy = applyPlantEvent(sy, { event: "sync", simHour: 7 }, at(), steps, cant).entry;
assert.equal(sy.applied[chw.id], undefined, "Can't do: back on habit");
assert.equal(snapshot(day, sim(sy), h + 0.5, false).setpoint, 7.0);
const approvedOnly = applyPlantEvent(empty(), { event: "sync", simHour: 6 }, at(), steps, {}).entry;
assert.equal(Object.keys(approvedOnly.applied).length, 0, "approved but not done: habit");
let fx = ev(applyPlantEvent(empty(), { event: "sync", simHour: 6 }, at(), steps, doneAll).entry, { event: "fault", type: "chw_low", simHour: 13 }).entry;
const later = { ...doneAll, [chw.id]: { event: "done", by: "Rahul", at: "2026-11-18 23:59" } };
fx = applyPlantEvent(fx, { event: "sync", simHour: 14 }, at(), steps, later).entry;
assert.ok(fx.faults.every((f) => f.fixedAt !== undefined) || !steps.some((s: any) => s.id === chw.id), "Done after the fault fixes it");
unit.meters_follow_done_in_app = true;

// 7. the Done event written by the plan page / duty Today (plans log) is exactly what the simulator reads; Undo puts the meters back on habit
let log = applyEvent(undefined, { event: "submit", by: BY, site: "GGN", inputs: { rooms: 180, guests: 300, covers: 400, bookings: inp.bookings, notes: "", temps_source: "x" },
  actions: steps.map(({ decision, ...a }: any) => a) }, "2026-11-18 08:00");
for (const s of steps) log = applyEvent(log, { event: "approve", by: BY, action_id: s.id }, "2026-11-18 08:01");
log = applyEvent(log, { event: "done", by: "Rahul", action_id: ahu0().id }, "2026-11-18 08:05");
let pv = view(inp.date, log, "gist");
assert.deepEqual(Object.keys(pv.duty), [ahu0().id]);
let ps = applyPlantEvent(empty(), { event: "sync", simHour: 7 }, at(), steps, pv.duty).entry;
assert.equal(ps.applied[ahu0().id]?.by, "Rahul"); assert.equal(ps.audit.at(-1)?.event, "step marked done");
log = applyEvent(log, { event: "undone", by: "Rahul", action_id: ahu0().id }, "2026-11-18 08:06");
pv = view(inp.date, log, "gist");
assert.equal(pv.duty[ahu0().id], undefined);
ps = applyPlantEvent(ps, { event: "sync", simHour: 8 }, at(), steps, pv.duty).entry;
assert.equal(ps.applied[ahu0().id], undefined, "Undo: back on habit"); assert.equal(ps.audit.at(-1)?.event, "done undone");
assert.throws(() => applyEvent(log, { event: "done", by: "Rahul", action_id: "nope" }, "x"));
unit.done_event_read_by_simulator = true;
// 8. weather scenarios never count: flagged by isScenario (plans month listing, device fallback and Today's check skip them); TEST-only withdraw
assert.ok(isScenario({ weather_mode: "scenario-40C" } as any) && !isScenario({ weather_mode: "live" } as any) && !isScenario({} as any));
assert.equal(view(inp.date, applyEvent(log, { event: "withdraw", by: "demo reset" }, "x"), "gist").plan, null);
const real = applyEvent(undefined, { event: "submit", by: "Meera", site: "GGN", inputs: {}, actions: steps.map(({ decision, ...a }: any) => a) }, "x");
assert.throws(() => applyEvent(real, { event: "withdraw", by: "demo reset" }, "y"), /TEST/);
unit.scenario_and_withdraw_rules = true;

// ---- fault scenarios: what the app sends to /check ----
const allApplied = () => applyPlantEvent(empty(), { event: "sync", simHour: 6 }, at(), steps, doneAll).entry;
const ahu = steps.find((s: any) => s.group === "ahu");
const off = Number(ahu.end.slice(0, 2)) + (ahu.end.includes("next day") ? 24 : 0);
const scenarios: any[] = [];
function emit(name: string, e: PlantEntry, now: number, expectAlert: boolean, group?: string) {
  const rows = checkWindow(now, e.lastFix).map((k) => hourRow(day, sim(e), k, now));
  const asOf = `${day.date}T${String(Math.floor(now)).padStart(2, "0")}:${String(Math.floor((now % 1) * 60)).padStart(2, "0")}`;
  const local = checkDay(day.date, steps, rows, asOf, day.ref, day.tariff, day.pf);
  scenarios.push({ name, as_of: asOf, meters: rows, expect_alert: expectAlert, group, local: { alerts: local.alerts.map((a) => ({ id: a.id, title: a.title, cost: a.cost })), steps: local.steps } });
}
let s1 = allApplied();
emit("0 all steps applied, no fault (after event)", s1, off + 1, false);
s1 = ev(s1, { event: "fault", type: "ahu_left_on", simHour: off + 1 }).entry;
emit("1 banquet AHU left on after event", s1, off + 1, true, "ahu");
const fixed = applyPlantEvent(s1, { event: "clearFault", by: "Rahul", simHour: off + 1.2 }, at(), steps);     // "Fixed on site" in the app
assert.equal(fixed.entry.faults[0].fixedAt, off + 1.2, "Fixed on site clears fault 1");
emit("1 fixed on site (duty engineer)", fixed.entry, off + 1.3, false);
let s2 = ev(allApplied(), { event: "fault", type: "chw_low", simHour: 13 }).entry;       // during the conference (one setpoint block)
emit("2 CHW set to 5.5 °C after a complaint", s2, 14.2, true, "chw");
s2 = ev(s2, { event: "clearFault", simHour: 14.4 }).entry;
emit("2 cleared", s2, 14.5, false);
let s3 = ev(allApplied(), { event: "fault", type: "peak_creep", simHour: 18 }).entry;
emit("3 peak creep: laundry + AHU in 18–22", s3, 19.3, true, "laundry");
const creepKva = snapshot(day, sim(s3), 19.3, false).kva, normalKva = snapshot(day, sim(allApplied()), 19.3, false).kva;
assert.ok(creepKva > normalKva + 50, "peak creep raises site kVA");
s3 = ev(s3, { event: "clearFault", simHour: 19.5 }).entry;
emit("3 cleared", s3, 19.6, false);
for (const s of scenarios) assert.equal(s.local.alerts.length > 0, s.expect_alert, `local check: ${s.name}`);
// 9. the alert card's cost: kWh x tariff = ₹ shown; the rows add up to the total; "all day" = ₹ an hour x 24
{
  const rows = checkWindow(off + 1, s1.lastFix).map((k) => hourRow(day, sim(s1), k, off + 1));
  const a = checkDay(day.date, steps, rows, `${day.date}T${String(off + 1).padStart(2, "0")}:00`, day.ref, day.tariff, day.pf).alerts[0];
  const c = costBreakdown(a);
  const rate = (day.tariff.energy + day.tariff.fsa + day.tariff.duty) / day.pf;
  assert.ok(Math.abs(c.kwh * rate - c.soFar) <= 1, `kWh x tariff ${c.kwh * rate} vs ${c.soFar}`);
  assert.ok(Math.abs(c.rows.reduce((x, r) => x + r.kwh, 0) - c.kwh) <= 0.3, "hour rows add up");
  assert.ok(Math.abs(c.rows.reduce((x, r) => x + r.inr, 0) - c.soFar) <= 3);
  assert.equal(c.allDay, Math.round(a.per_hour * 24));
  assert.equal(c.hours, 2);
  unit.alert_cost_arithmetic = true;
}
unit.local_check_matches_expectations = true;
writeFileSync(process.argv[3], JSON.stringify({ unit, scenarios, creep_kva: [normalKva, creepKva] }));
