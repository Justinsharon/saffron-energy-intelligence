// Mark done at sim 22:00 -> jump to 20:00 -> Fault 1 -> Play -> the AHU alert on Today within 20 s (the meters take a Done in from the
// step's own start hour, and a fix later than the sim clock never shortens the plan check's window).
// Run: node tools/plant_e2e_late_done.mjs [base URL]   (then node tools/demo_reset.mjs <tomorrow> [base URL])
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const BASE = (process.argv[2] ?? "https://saffron-energy-intelligence1.netlify.app").replace(/\/$/, "");
const DATE = process.env.PLANT_DATE ?? new Date(Date.now() + 5.5 * 3.6e6 + 864e5).toISOString().slice(0, 10);   // PLANT_DATE: avoid a plan someone is rehearsing
const say = (s) => console.log(`${new Date().toISOString().slice(11, 19)} ${s}`);
const fail = (s) => { say(`FAIL: ${s}`); process.exitCode = 1; throw new Error(s); };
const browser = await chromium.launch({ proxy: process.env.HTTPS_PROXY ? { server: process.env.HTTPS_PROXY, bypass: "localhost,127.0.0.1" } : undefined });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, ignoreHTTPSErrors: true });
await ctx.addInitScript(() => { try { if (!localStorage.getItem("view_as")) localStorage.setItem("view_as", "chief"); localStorage.setItem("planner", "TEST – Claude Code"); } catch {} });
const app = await ctx.newPage(), plant = await ctx.newPage();
try {
  await app.goto(`${BASE}/#/demand`);
  await app.waitForSelector("text=Weather:", { timeout: 60000 });
  await app.locator("input[type=date]").first().fill(DATE);
  await app.waitForTimeout(3000);
  await app.waitForSelector("text=Weather:", { timeout: 60000 });
  if (!(await app.getByRole("button", { name: "Remove" }).count())) await app.getByRole("button", { name: "+ Add a booking" }).click();
  await app.getByRole("spinbutton").last().fill("300");
  await app.waitForTimeout(9000);
  for (let i = 0; i < 4; i++) {
    if (!(await app.locator("text=not saved yet").count()) && !(await app.locator("text=The plan has changed since it was saved").count())) break;
    const s = app.getByRole("button", { name: "Save bookings and plan" }); if (await s.isEnabled().catch(() => false)) await s.click(); await app.waitForTimeout(6000);
  }
  for (let i = 0; i < 20; i++) {
    const ok = app.getByRole("button", { name: "Save and continue" }); if (await ok.count()) { await ok.click(); await app.waitForTimeout(4000); continue; }
    const b = app.locator("li.step button:has-text('Approve'):not([disabled])").first(); if (!(await b.count())) break; await b.click(); await app.waitForTimeout(1500);
  }
  say(`plan ${DATE}: ${await app.locator("li.step .status.ok").count()} steps approved`);
  // simulator at sim 22:00, THEN mark the AHU step done
  await plant.goto(`${BASE}/plant?date=${DATE}`);
  await plant.waitForSelector("text=approved, not done yet", { timeout: 60000 });
  await plant.getByRole("slider").fill("22"); await plant.waitForTimeout(800);
  const li = app.locator("[data-testid=duty-panel] li.duty-row").filter({ hasText: "Banquet AHUs" }).first();
  await li.getByTestId("mark-done").click(); await li.getByTestId("done-by").waitFor({ timeout: 20000 });
  await plant.waitForFunction(() => document.querySelector("[data-testid=done-count]")?.textContent === "1", null, { timeout: 15000 }).catch(() => fail("Done not taken in"));
  const audit = await plant.locator(".pr-audit tr").first().innerText();
  say(`marked done at sim 22:00 -> simulator: "${audit.replace(/\s+/g, " ").slice(0, 150)}"`);
  // back to 20:00, fault 1, play
  await plant.getByRole("slider").fill("20"); await plant.waitForTimeout(800);
  await plant.getByRole("button", { name: /1\. Banquet AHU left on/ }).click();
  await plant.getByRole("button", { name: /Play/ }).click();
  const t0 = Date.now();
  await app.evaluate(() => localStorage.setItem("view_as", "duty"));
  await app.goto(`${BASE}/#/today`); await app.reload();
  await app.waitForSelector("[data-testid=plant-alert] .title:has-text('banquet AHUs')", { timeout: 20000 }).catch(() => fail("no AHU alert within 20 s"));
  const card = app.locator("[data-testid=plant-alert]").filter({ hasText: "banquet AHUs" }).first();
  say(`AHU alert on Today ${((Date.now() - t0) / 1000).toFixed(1)} s after fault 1: "${(await card.locator(".title").innerText()).trim()}" · ${(await card.getByTestId("plant-cost").innerText()).split("\n")[0]}`);
  await plant.getByRole("button", { name: /Pause/ }).click();
  say("PASS");
} finally { await browser.close(); }
