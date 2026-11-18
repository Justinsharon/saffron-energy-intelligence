// Live-weather demo check on the DEPLOYED site (two tabs): plan on the real forecast with a 300-guest Hall A conference, approved -> Mark done on the AHU
// and chiller steps -> the meter simulator follows within 5 s -> fault 1 at 20:00 -> alert on Today with ₹/day, cost so far and "if left on
// all day" -> Fixed on site -> cleared; audit shows done / fault / fix. Then tools/demo_reset.mjs is run separately.
// Run: node tools/plant_e2e_final.mjs [base URL]
import { createRequire } from "node:module";
import { writeFileSync } from "node:fs";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const BASE = (process.argv[2] ?? "https://saffron-energy-intelligence1.netlify.app").replace(/\/$/, "");
const OUT = new URL("./demo_screens/live_weather/", import.meta.url).pathname;
const NAME = "TEST – Claude Code";
const DATE = new Date(Date.now() + 5.5 * 3.6e6 + 864e5).toISOString().slice(0, 10);
const log = [];
const step = (s) => { const l = `${new Date().toISOString().slice(11, 19)} ${s}`; log.push(l); console.log(l); };
const fail = (s) => { step(`FAIL: ${s}`); throw new Error(s); };
const proxy = process.env.HTTPS_PROXY ? { server: process.env.HTTPS_PROXY } : undefined;
const browser = await chromium.launch({ proxy });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, ignoreHTTPSErrors: true });
await ctx.addInitScript((n) => { try { if (!localStorage.getItem("view_as")) localStorage.setItem("view_as", "chief"); localStorage.setItem("planner", n); } catch {} }, NAME);
const app = await ctx.newPage(), plant = await ctx.newPage();
const lines = [];
app.on("console", (m) => { if (m.text().includes("[plant room]")) lines.push(m.text()); });
const kvaOf = async () => Number((await plant.locator(".pr-gauge text").first().textContent()) ?? 0);
try {
  // a. plan page: scenario on, Hall A 09:00-18:00 300 guests, save, approve all
  await app.goto(`${BASE}/#/demand`);
  await app.waitForSelector("text=Weather:", { timeout: 60000 });
  if (await app.getByTestId("scenario-40").count()) fail("the scenario toggle is visible without ?scenario=1");
  if (!(await app.getByRole("button", { name: "Remove" }).count())) await app.getByRole("button", { name: "+ Add a booking" }).click();
  await app.getByRole("spinbutton").last().fill("300");
  await app.waitForTimeout(4000);
  await app.getByRole("button", { name: "Save bookings and plan" }).click();
  await app.waitForSelector("button:has-text('Approve')", { timeout: 30000 });
  for (let i = 0; i < 20; i++) { const b = app.locator("button:has-text('Approve'):not([disabled])").first(); if (!(await b.count())) break; await b.click(); await app.waitForTimeout(1200); }
  const approved = await app.locator("li.step .status.ok").count();
  const weather = await app.getByTestId("weather-line").innerText();
  if (/SCENARIO/.test(weather) || (await app.getByTestId("scenario-banner").count())) fail("scenario shown");
  step(`a. plan ${DATE}: live weather, ${approved} steps approved · "${weather.slice(0, 90)}"`);
  await app.screenshot({ path: `${OUT}a_plan_live.png`, fullPage: true });

  // b. simulator open first (meter before), then Mark done on the AHU and chiller steps in the app
  await plant.goto(`${BASE}/plant?date=${DATE}`);
  await plant.waitForSelector("text=approved, not done yet", { timeout: 60000 });
  if (await plant.getByTestId("scenario-pill").count()) fail("SCENARIO pill shown");
  const kwhOf = async () => Number(((await plant.locator(".pr-meter td").nth(5).textContent()) ?? "").replace(/[^0-9]/g, ""));
  const at = async (h) => { await plant.getByRole("slider").fill(String(h)); await plant.waitForTimeout(700); };
  await at(23.75); const habitKwh = await kwhOf();
  await at(14); const before = await kvaOf();
  await at(0);                                                             // Done is taken in at the sim time: from 00:00 the whole day follows the plan
  const toMark = app.locator("li.step").filter({ hasText: /Banquet AHUs|Chillers \(CH-1|Chilled-water supply setpoint/ });
  const n = await toMark.count();
  for (let i = 0; i < n; i++) { await toMark.nth(i).getByTestId("mark-done").click(); await app.waitForTimeout(1500); }
  const t0 = Date.now();
  await plant.waitForFunction((k) => document.querySelector("[data-testid=done-count]")?.textContent === String(k), n, { timeout: 15000 }).catch(() => fail("simulator did not show the Done steps"));
  await plant.waitForSelector(".pr-mtile.src-plan", { timeout: 10000 });
  const secs = ((Date.now() - t0) / 1000).toFixed(1);
  await at(14); const after = await kvaOf();
  await at(23.75); const planKwh = await kwhOf();
  step(`b. ${n} steps marked done (AHU, chillers, CHW) -> simulator shows them as plan ${secs} s after the last click; ${await plant.locator(".pr-mtile.src-plan").count()} channels on plan`);
  step(`b. main meter, habit vs plan: kVA at 14:00 ${before} -> ${after}; kWh for the day (to 23:45) ${habitKwh} -> ${planKwh}`);
  await plant.screenshot({ path: `${OUT}b_plant_done.png`, fullPage: true });

  // c. jump to after the event, fault 1, play -> alert on Today
  await plant.getByRole("button", { name: /^\d\d:00 after event$/ }).click();
  await plant.getByRole("button", { name: /1\. Banquet AHU left on/ }).click();
  await plant.getByRole("button", { name: /Play/ }).click();
  const t1 = Date.now();
  await app.evaluate(() => localStorage.setItem("view_as", "duty"));
  await app.goto(`${BASE}/#/today`); await app.reload();
  await app.waitForSelector("[data-testid=plant-alert] .title:has-text('banquet AHUs')", { timeout: 20000 }).catch(() => fail("no alert within 20 s"));
  const cost = await app.getByTestId("plant-cost").first().innerText();
  const perDay = await app.locator("[data-testid=plant-alert] .money b").first().innerText();
  step(`c. alert ${((Date.now() - t1) / 1000).toFixed(1)} s after fault 1: ${perDay} a day · ${cost.split("\n")[0]}`);
  if (!/Cost so far/.test(cost) || !/If left on all day/.test(cost)) fail("cost lines missing");
  await app.getByTestId("plant-cost").first().locator("summary").click();
  await app.locator("[data-testid=plant-alerts]").scrollIntoViewIfNeeded();
  await app.screenshot({ path: `${OUT}c_app_alert.png` });
  await plant.getByRole("button", { name: /Pause/ }).click();
  await plant.screenshot({ path: `${OUT}c_plant_fault.png`, fullPage: true });

  // d. fixed on site -> clears; audit shows done, fault, fix
  await app.getByTestId("plant-fixed").click();
  const t2 = Date.now();
  await app.waitForSelector("[data-testid=plant-no-alert]", { timeout: 30000 }).catch(() => fail("alert not cleared"));
  step(`d. alert cleared ${((Date.now() - t2) / 1000).toFixed(1)} s after Fixed on site`);
  await plant.waitForTimeout(6000);
  const audit = await plant.locator(".pr-audit").innerText();
  for (const k of ["step marked done", "fault injected", "fault cleared"]) if (!audit.includes(k)) fail(`audit lacks "${k}"`);
  step("d. audit log has step marked done, fault injected, fault cleared rows");
  await app.screenshot({ path: `${OUT}d_app_cleared.png` });
  await plant.screenshot({ path: `${OUT}d_plant_audit.png`, fullPage: true });
  step(`console: ${lines.slice(-2).join(" | ")}`);
  await plant.close();
  // e. demo reset, then Today shows no simulator alert
  const { execFileSync } = await import("node:child_process");
  step("e. " + execFileSync("node", [new URL("./demo_reset.mjs", import.meta.url).pathname, DATE, BASE]).toString().trim().replace(/\n/g, " | "));
  await app.reload(); await app.waitForTimeout(12000);
  if (await app.locator("[data-testid=plant-alert]").count()) fail("a simulator alert is still on Today after the reset");
  const after2 = await (await fetch(`${BASE}/.netlify/functions/plans?date=${DATE}&site=GGN`)).json();
  if (after2.plan) fail("a plan is still saved for tomorrow");
  step("e. clean: no plan for tomorrow, no simulator alert on Today");
  await app.screenshot({ path: `${OUT}e_app_clean.png` });
  step("PASS");
} finally {
  writeFileSync(`${OUT}e2e_log.txt`, log.join("\n") + "\n");
  await browser.close();
}
