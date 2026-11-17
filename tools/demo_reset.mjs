// Presenter cleanup before the demo. For ONE date (default: tomorrow, IST) on the deployed site:
//   - withdraws the saved Gurugram plan only if it was saved by a name starting "TEST" (the plans function refuses any other); nothing is
//     deleted: the log keeps every row, and the Done marks go with the withdrawn plan;
//   - clears the meter simulator's fault, readings and taken-in Done steps; its audit rows are kept, marked superseded.
// Run: node tools/demo_reset.mjs [date YYYY-MM-DD] [base URL]
const IST = () => new Date(Date.now() + 5.5 * 3.6e6);
const date = process.argv[2] ?? new Date(IST().getTime() + 864e5).toISOString().slice(0, 10);
const BASE = (process.argv[3] ?? "https://saffron-energy-intelligence1.netlify.app").replace(/\/$/, "");
const BY = "demo reset (presenter)";
const post = async (fn, body) => { const r = await fetch(`${BASE}/.netlify/functions/${fn}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }); return [r.status, await r.json()]; };

const plan = await (await fetch(`${BASE}/.netlify/functions/plans?date=${date}&site=GGN`)).json();
console.log(`${BASE} · ${date}`);
if (!plan.plan) console.log("plan: none saved (nothing to withdraw)");
else if (!/^TEST/i.test(plan.plan.by)) console.log(`plan: v${plan.plan.n} saved by "${plan.plan.by}": not a TEST plan, KEPT`);
else {
  const [st, j] = await post("plans", { date, site: "GGN", event: "withdraw", by: BY, reason: "demo reset: TEST plan removed before the presentation" });
  console.log(st === 200 ? `plan: v${plan.plan.n} by "${plan.plan.by}" withdrawn` : `plan: withdraw refused (${st}): ${j.error}`);
}
const [st2, p] = await post("plant", { date, site: "GGN", event: "demoReset", by: BY, simHour: 0, reason: "demo reset before the presentation" });
console.log(st2 === 200 ? `simulator: cleared (faults ${p.faults.length}, readings ${p.readings ? "kept" : "none"}, steps following plan ${Object.keys(p.applied).length})` : `simulator: refused (${st2}): ${p.error}`);
const after = await (await fetch(`${BASE}/.netlify/functions/plans?date=${date}&site=GGN`)).json();
console.log(`check: saved plan for ${date}: ${after.plan ? `v${after.plan.n} by ${after.plan.by}` : "none"}`);
