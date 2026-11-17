// Meter simulator end to end (headless Playwright): the chief engineer approves today's plan -> the duty engineer marks the steps Done in the
// Saffron app -> the simulator's meters follow the plan -> after the event, fault 1 (banquet AHU left on) -> the alert appears on the app's
// Today page within 15 s -> the duty engineer presses "Fixed on site" -> the alert clears. The simulator page has no sign-in and no controls
// besides the fault demo. Screenshots of both screens go to tools/demo_screens/.
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
await ctx.addInitScript((n) => { try { if (!localStorage.getItem("view_as")) localStorage.setItem("view_as", "chief"); localStorage.setItem("planner", n); } catch {} }, NAME);
const app = await ctx.newPage();
const plant = await ctx.newPage();
const consoleLines = [];
app.on("console", (m) => { if (m.text().includes("[plant room]")) consoleLines.push(m.text()); });

try {
  // warm the plan API (a cold weather fetch would otherwise make the first plan use typical temperatures) and start from a clean simulator
  const today = new Date(Date.now() + 5.5 * 3.6e6).toISOString().slice(0, 10);
  await fetch(`${BASE}/api/plan`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ date: today }) }).catch(() => {});
  await fetch(`${BASE}/.netlify/functions/plant`, { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ date: today, site: "GGN", event: "reset", by: NAME, simHour: 0, reason: "end-to-end test start" }) }).catch(() => {});

  // 1. Chief engineer: today's plan with a conference, saved and every step approved
  await app.goto(`${BASE}/#/demand`);
  await app.waitForSelector("text=Weather:", { timeout: 30000 });
  await app.locator("input[type=date]").first().fill(today);
  await app.waitForSelector("text=Weather:", { timeout: 30000 });
  await app.waitForTimeout(1500);
  if (!(await app.getByRole("button", { name: "Remove" }).count())) await app.getByRole("button", { name: "+ Add a booking" }).click();
  await app.waitForTimeout(2000);
  const save = app.getByRole("button", { name: "Save bookings and plan" });
  if (await save.isVisible().catch(() => false)) await save.click();
  await app.waitForSelector("button:has-text('Approve')", { timeout: 30000 });
  for (let i = 0; i < 20; i++) {
    const b = app.locator("button:has-text('Approve'):not([disabled])").first();
    if (!(await b.count())) break;
    await b.click();
    await app.waitForTimeout(400);
  }
  const approved = await app.locator(".status.ok").count();
  step(`app (chief engineer): today's plan saved, ${approved} steps approved`);
  if (approved < 3) fail("too few steps approved");

  // 2. Meter simulator: approved but not done -> every channel on habit; no controls on the page
  await plant.goto(`${BASE}/plant.html`);
  await plant.waitForSelector("[data-testid=channels]", { timeout: 30000 });
  const banner = await plant.getByTestId("sim-banner").innerText();
  if (!banner.startsWith("SIMULATION · Gurugram · Sim time")) fail(`banner: ${banner}`);
  if (await plant.locator("text=Signed in as").count()) fail("simulator shows a sign-in picker");
  if (await plant.getByRole("button", { name: /^(Apply|Override)/ }).count()) fail("simulator has Apply / Override controls");
  await plant.waitForSelector("text=approved, not done yet", { timeout: 15000 });
  step(`simulator: "${banner}"; no sign-in, no Apply/Override; channels on habit (approved, not done yet)`);

  // 3. Duty engineer marks every step Done in the app -> the simulator's meters follow the plan
  await app.evaluate(() => localStorage.setItem("view_as", "duty"));
  await app.goto(`${BASE}/#/today`);
  await app.reload();                                                        // a hash change alone keeps the old view
  await app.waitForSelector("button.btn.big:has-text('Done')", { timeout: 30000 });
  for (let i = 0; i < 20; i++) {
    const b = app.locator("button.btn.big:has-text('Done'):not([disabled])").first();
    if (!(await b.count())) break;
    await b.click();
    await app.waitForTimeout(500);
  }
  const t0done = Date.now();
  await plant.waitForFunction((n) => document.querySelector("[data-testid=done-count]")?.textContent === String(n), approved, { timeout: 20000 });
  await plant.waitForSelector(".pr-src.plan", { timeout: 10000 });
  step(`app (duty engineer): ${approved} steps marked Done -> simulator follows the plan (${((Date.now() - t0done) / 1000).toFixed(1)} s after the last click)`);
  await app.waitForSelector("[data-testid=plant-no-alert]", { timeout: 20000 }).catch(() => fail("an alert is still shown with every step done and no fault"));
  step("app: no simulator alert with every step done");

  // 4. After the event: inject fault 1 -> alert in the app
  await plant.getByRole("button", { name: /^\d\d:00 after event$/ }).click();
  await plant.waitForTimeout(800);
  await plant.screenshot({ path: `${OUT}plant_room_after_event.png` });
  await app.waitForSelector("[data-testid=plant-alerts]", { timeout: 20000 });
  await plant.getByRole("button", { name: /1\. Banquet AHU left on/ }).click();
  const t0 = Date.now();
  step("simulator: fault 1 injected (banquet AHU left on after event)");
  await app.waitForSelector("[data-testid=plant-alert] .title:has-text('banquet AHUs')", { timeout: 15000 }).catch(() => fail("no AHU alert in the app within 15 s"));
  step(`app: alert visible after ${((Date.now() - t0) / 1000).toFixed(1)} s: "${(await app.locator("[data-testid=plant-alert] .title").first().innerText()).trim()}"`);
  await app.locator("[data-testid=plant-alerts]").scrollIntoViewIfNeeded();
  await app.screenshot({ path: `${OUT}app_today_alert.png` });
  await plant.waitForSelector(".pr-src.fault", { timeout: 5000 });
  await plant.screenshot({ path: `${OUT}plant_room_fault.png` });

  // 5. Duty engineer: "Fixed on site" -> the simulator takes it in, the alert clears
  await app.getByTestId("plant-fixed").click();
  const t1 = Date.now();
  await app.waitForSelector("[data-testid=plant-no-alert]", { timeout: 25000 }).catch(() => fail("alert still shown 25 s after Fixed on site"));
  step(`app: alert resolved ${((Date.now() - t1) / 1000).toFixed(1)} s after "Fixed on site"`);
  await app.screenshot({ path: `${OUT}app_today_resolved.png` });
  await plant.waitForTimeout(1000);
  await plant.screenshot({ path: `${OUT}plant_room_fixed.png` });
  step(`console: ${consoleLines.slice(-2).join(" | ")}`);
  step("PASS");
} finally {
  writeFileSync(`${OUT}e2e_log.txt`, log.join("\n") + "\n");
  await browser.close();
}
