// Plant Room end to end (headless Playwright): approve tomorrow's plan in the Saffron app -> Apply the steps in the Plant Room -> jump to
// after the event -> inject fault 1 (banquet AHU left on) -> the alert appears on the app's Today page within 15 s -> Apply the fix ->
// the alert is gone. Also: a CHW override below 6.5 °C is refused on screen, monitored-only tiles have no buttons, and Tomorrow's plan
// shows "Applied in plant room". Screenshots of both screens go to tools/demo_screens/.
// Run against a dev server with shared state in memory (see tools/demo_screens/README.md):
//   node tools/plant_e2e.mjs [base URL, default http://127.0.0.1:5173]
import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const BASE = process.argv[2] ?? "http://127.0.0.1:5173";
const OUT = new URL("./demo_screens/", import.meta.url).pathname;
mkdirSync(OUT, { recursive: true });
const NAME = "TEST – Claude Code";
const log = [];
const step = (s) => { const line = `${new Date().toISOString().slice(11, 19)} ${s}`; log.push(line); console.log(line); };
const fail = (s) => { step(`FAIL: ${s}`); throw new Error(s); };

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
await ctx.addInitScript((n) => { try { localStorage.setItem("view_as", "chief"); localStorage.setItem("planner", n); localStorage.setItem("plant_user", "Rahul (Duty engineer)"); } catch {} }, NAME);
const app = await ctx.newPage();
const plant = await ctx.newPage();
const consoleLines = [];
app.on("console", (m) => { if (m.text().includes("[plant room]")) consoleLines.push(m.text()); });

try {
  // warm the plan API (a cold weather fetch would otherwise make the first plan use typical temperatures) and start from a clean Plant Room
  const tomorrow = new Date(Date.now() + 5.5 * 3.6e6 + 864e5).toISOString().slice(0, 10);
  await fetch(`${BASE}/api/plan`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ date: tomorrow }) }).catch(() => {});
  await fetch(`${BASE}/.netlify/functions/plant`, { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ date: tomorrow, site: "GGN", event: "reset", by: NAME, simHour: 0, reason: "end-to-end test start" }) }).catch(() => {});
  // 1. Tomorrow's plan: add a conference booking, save, approve every step
  await app.goto(`${BASE}/#/demand`);
  await app.waitForSelector("text=Weather:", { timeout: 30000 });
  if (!(await app.getByRole("button", { name: "Remove" }).count()))
    await app.getByRole("button", { name: "+ Add a booking" }).click({ timeout: 30000 });
  await app.waitForTimeout(1500);
  const save = app.getByRole("button", { name: "Save bookings and plan" });
  if (await save.isVisible().catch(() => false)) await save.click();          // hidden when the same plan is already saved (a re-run)
  await app.waitForSelector("button:has-text('Approve')", { timeout: 30000 });
  for (let i = 0; i < 20; i++) {
    const b = app.locator("button:has-text('Approve'):not([disabled])").first();
    if (!(await b.count())) break;
    await b.click();
    await app.waitForTimeout(400);
  }
  const approved = await app.locator(".status.ok").count();
  step(`app: plan saved and ${approved} steps approved`);
  if (approved < 3) fail("too few steps approved");

  // 2. Plant Room: the approved steps appear; Apply all at 06:00
  await plant.goto(`${BASE}/plant.html`);
  await plant.waitForSelector("[data-testid^=step-]", { timeout: 30000 });
  const banner = await plant.getByTestId("sim-banner").innerText();
  if (!banner.startsWith("SIMULATION · Gurugram · Sim time")) fail(`banner: ${banner}`);
  const nSteps = await plant.locator("[data-testid^=step-]").count();
  step(`plant: ${nSteps} approved steps in the queue; banner "${banner}"`);
  if (nSteps !== approved) fail(`queue shows ${nSteps}, app approved ${approved}`);
  for (let i = 0; i < nSteps; i++) {
    await plant.locator("[data-testid^=step-]").nth(i).getByRole("button", { name: "Apply", exact: true }).click();
    await plant.waitForTimeout(300);
  }
  await plant.waitForFunction((n) => document.querySelectorAll(".pr-step.applied").length === n, nSteps, { timeout: 15000 });
  step("plant: every step applied (Applied by … shown)");

  // guardrails on screen: CHW override below 6.5 °C refused; monitored-only tiles have no buttons
  const chwStep = plant.locator("[data-testid^=step-chw]").first();
  await chwStep.getByRole("button", { name: "Override…" }).click();
  await chwStep.getByLabel("Override setpoint").fill("6.0");
  await chwStep.getByLabel("Override reason").fill("guest says it is warm (TEST – Claude Code)");
  await chwStep.getByRole("button", { name: "Log override" }).click();
  await plant.waitForSelector(".pr-msg.err:has-text('never below 6.5')", { timeout: 10000 });
  step("plant: CHW override to 6.0 °C refused with the reason shown");
  for (const id of ["KEF", "ROOMS", "LIFTS", "FIRE"]) if (await plant.getByTestId(`mon-${id}`).locator("button").count()) fail(`monitored tile ${id} has a button`);
  step("plant: monitored-only tiles have no controls");

  // Tomorrow's plan shows "Applied in plant room hh:mm"
  await app.reload();
  await app.waitForSelector("[data-testid=plant-applied]", { timeout: 20000 });
  step(`app: Tomorrow's plan shows ${await app.getByTestId("plant-applied").count()} × "Applied in plant room"`);

  // 3. Jump to after the event and inject fault 1
  await plant.getByRole("button", { name: /^\d\d:00 after event$/ }).click();
  await plant.waitForTimeout(500);
  await plant.screenshot({ path: `${OUT}plant_room_after_event.png` });
  await app.goto(`${BASE}/#/today`);
  await app.waitForSelector("[data-testid=plant-alerts]", { timeout: 20000 });
  await plant.getByRole("button", { name: /1\. Banquet AHU left on/ }).click();
  const t0 = Date.now();
  step("plant: fault 1 injected (banquet AHU left on after event)");
  await app.waitForSelector("[data-testid=plant-alert]", { timeout: 15000 }).catch(() => fail("no alert in the app within 15 s"));
  const secs = (Date.now() - t0) / 1000;
  step(`app: alert visible after ${secs.toFixed(1)} s: "${(await app.locator("[data-testid=plant-alert] .title").first().innerText()).trim()}"`);
  await app.locator("[data-testid=plant-alert]").first().scrollIntoViewIfNeeded();
  await app.screenshot({ path: `${OUT}app_today_alert.png` });
  await plant.screenshot({ path: `${OUT}plant_room_fault.png` });

  // 4. Apply the fix (the AHU off step again) -> alert gone
  await plant.locator("[data-testid^=step-ahu]").getByRole("button", { name: "Apply fix" }).click();
  const t1 = Date.now();
  await app.waitForSelector("[data-testid=plant-no-alert]", { timeout: 15000 }).catch(() => fail("alert still shown 15 s after the fix"));
  step(`app: alert resolved ${((Date.now() - t1) / 1000).toFixed(1)} s after Apply fix`);
  await app.screenshot({ path: `${OUT}app_today_resolved.png` });
  await plant.screenshot({ path: `${OUT}plant_room_fixed.png` });
  step(`console: ${consoleLines.slice(-2).join(" | ")}`);
  step("PASS");
} finally {
  writeFileSync(`${OUT}e2e_log.txt`, log.join("\n") + "\n");
  await browser.close();
}
