// Plant Room alerts where the duty engineer looks (View as: Duty engineer), on the deployed site by default:
// simulator at 06:00 -> Reset demo for this day -> TEST plan (Hall A 09:00-18:00, 300 guests) saved and approved -> Mark done on the AHU step
// (duty panel) -> 20:00 -> Fault 1 -> Play 20 s -> red badge on "Needs attention", alert in its list (and on Today) -> Fixed on site in Needs
// attention clears it in both places -> simulator back to 06:00 -> Reset demo for this day once.
// The plan is saved and approved through the plans function (what the page posts); every other step is clicked in the browser.
// Run: node tools/plant_e2e_attention.mjs [base URL]
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const B = (process.argv[2] ?? "https://saffron-energy-intelligence1.netlify.app").replace(/\/$/, "");
const D = process.env.PLANT_DATE ?? new Date(Date.now() + 5.5 * 3.6e6 + 864e5).toISOString().slice(0, 10);
const BY = "TEST – Claude Code";
const OUT = new URL("./demo_screens/attention/", import.meta.url).pathname; mkdirSync(OUT, { recursive: true });
const say = (s) => console.log(`${new Date().toISOString().slice(11, 19)} ${s}`);
const fail = (s) => { say(`FAIL: ${s}`); throw new Error(s); };
const post = async (fn, b) => { const r = await fetch(`${B}/.netlify/functions/${fn}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(b) }); const j = await r.json(); if (!r.ok) throw new Error(`${fn} ${r.status} ${j.error}`); return j; };
const local = /localhost|127\.0\.0\.1/.test(B);
const br = await chromium.launch({ proxy: process.env.HTTPS_PROXY && !local ? { server: process.env.HTTPS_PROXY } : undefined });
const ctx = await br.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, ignoreHTTPSErrors: true });
await ctx.addInitScript((n) => { try { localStorage.setItem("view_as", "duty"); localStorage.setItem("planner", n); } catch {} }, BY);
const plant = await ctx.newPage(), app = await ctx.newPage();
const resetDemo = async () => {
  await plant.getByRole("button", { name: "Reset demo for this day" }).click();
  await plant.getByRole("button", { name: "Confirm reset" }).last().click();
  await plant.waitForSelector(".pr-msg.ok", { timeout: 30000 });
  return (await plant.locator(".pr-msg.ok").innerText()).trim();
};
const at = async (h) => { await plant.getByRole("slider").fill(String(h)); await plant.waitForTimeout(800); };
try {
  // 1. simulator at 06:00, Reset demo for this day
  await plant.goto(`${B}/plant?date=${D}`);
  await plant.waitForSelector("[data-testid=channels]", { timeout: 60000 });
  await at(6);
  say(`1. reset at 06:00: ${await resetDemo()}`);
  // 2. TEST plan, Hall A 09:00-18:00 300 guests, every step approved (plans function, as the page posts it)
  const bookings = [{ hall: "A", start: "09:00", end: "18:00", guests: 300 }];
  const plan = await (await fetch(`${B}/api/plan`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ date: D, site: "GGN", bookings }) })).json();
  const actions = plan.actions.map((a) => ({ ...a, id: `${a.group}|${a.start}|${a.equipment}` }));
  await post("plans", { date: D, site: "GGN", by: BY, event: "submit", actions,
    inputs: { rooms: plan.inputs_used.rooms, guests: plan.inputs_used.guests, covers: plan.inputs_used.covers, bookings, notes: "", temps_source: plan.inputs_used.weather, weather_mode: "live" } });
  for (const a of actions) await post("plans", { date: D, site: "GGN", by: BY, event: "approve", action_id: a.id });
  say(`2. TEST plan ${D} saved, ${actions.length} steps approved`);
  // 3. Mark done on the AHU step in the duty panel (Tomorrow's plan)
  await app.goto(`${B}/#/demand`); await app.reload();
  if (D !== new Date(Date.now() + 5.5 * 3.6e6 + 864e5).toISOString().slice(0, 10)) await app.locator("input[type=date]").first().fill(D);
  const li = app.locator("[data-testid=duty-panel] li.duty-row").filter({ hasText: "Banquet AHUs" }).first();
  await li.getByTestId("mark-done").click({ timeout: 60000 }); await li.getByTestId("done-by").waitFor({ timeout: 30000 });
  await plant.waitForFunction(() => document.querySelector("[data-testid=done-count]")?.textContent === "1", null, { timeout: 20000 }).catch(() => fail("simulator did not take in the Done"));
  say("3. AHU step marked done (duty panel); simulator follows it");
  // 4. 20:00, Fault 1, Play 20 s
  await at(20);
  await plant.getByRole("button", { name: /1\. Banquet AHU left on/ }).click();
  await plant.getByRole("button", { name: /Play/ }).click();
  const t0 = Date.now();
  await app.goto(`${B}/#/attention`);
  await app.waitForSelector("[data-testid=attention-badge]", { timeout: 25000 }).catch(() => fail("no badge on Needs attention"));
  const badge = await app.getByTestId("attention-badge").innerText();
  await app.waitForSelector("[data-testid=plant-alert] .title:has-text('banquet AHUs')", { timeout: 25000 }).catch(() => fail("no alert in Needs attention"));
  const card = app.locator("[data-testid=plant-alert]").filter({ hasText: "banquet AHUs" }).first();
  say(`4. after ${((Date.now() - t0) / 1000).toFixed(1)} s: badge "Needs attention ${badge}"; alert at the top of Needs attention: "${(await card.locator(".title").innerText()).trim()}" · ${(await card.getByTestId("plant-cost").innerText()).split("\n")[0]}`);
  await app.waitForTimeout(Math.max(0, 20000 - (Date.now() - t0)));
  await plant.getByRole("button", { name: /Pause/ }).click();
  await app.screenshot({ path: `${OUT}attention_alert.png` });
  await plant.screenshot({ path: `${OUT}plant_fault.png`, fullPage: true });
  // 5. Fixed on site (Needs attention) clears it in both places
  await app.getByTestId("plant-fixed").first().click();
  const t1 = Date.now();
  await app.waitForSelector("[data-testid=plant-no-alert]", { timeout: 30000 }).catch(() => fail("alert not cleared in Needs attention"));
  if (await app.getByTestId("attention-badge").count()) fail("badge still shown after the fix");
  say(`5. Fixed on site: cleared in Needs attention and the badge ${((Date.now() - t1) / 1000).toFixed(1)} s later`);
  await app.screenshot({ path: `${OUT}attention_cleared.png` });
  await app.goto(`${B}/#/today`); await app.waitForSelector("[data-testid=plant-alerts]", { timeout: 20000 }); await app.waitForTimeout(2000);
  if (await app.locator("[data-testid=plant-alert]").count()) fail("alert still on Today");
  say("5. Today: no Plant Room alert either");
  // 6. back to 06:00, Reset demo for this day once
  await at(6);
  say(`6. reset at 06:00: ${await resetDemo()}`);
  const after = await (await fetch(`${B}/.netlify/functions/plans?date=${D}&site=GGN`)).json();
  say(`6. saved plan for ${D}: ${after.plan ? `v${after.plan.n} ${after.plan.by}` : "none"}`);
  say("PASS");
} finally { await br.close(); }
