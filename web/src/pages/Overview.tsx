// General manager's Overview: this month at a glance, built only from parts that already exist - this month's use vs the adjusted
// baseline (Option C, as on Bills & savings) and vs the same days last year (the hourly meter files, at each month's average bill rate),
// the latest bill-change split (Monthly costs), the top problems by ₹, and how well the daily plan was followed (plan check API).
import { useEffect, useMemo, useState } from "react";
import { useClock } from "../App";
import { Waterfall } from "../components/parts";
import { DRIVER, NOT_CLAIMED, RULE } from "../copy";
import { SITE_NAME, useAlertsAt, useBillsAt, useChangesAt, useData, type Site } from "../data";
import { checkPlan } from "../planApi";
import { loadMonthPlans } from "../planStore";
import { fmtMonth, inr, n } from "../format";
import { rateOf, useMonthSavings } from "../monthSavings";
import { useHotel } from "../views";
import { sentence } from "./GM";
import { loadAcks, SiteSwitch } from "./Shift";

interface Day { approved: number; due: number; followed: number; partly: number; not_followed: number; verified_inr: number; missed_inr: number }
interface Adherence { made: string; upto: string; sites: Record<Site, Record<string, Record<string, Day>>> }
const lastYear = (m: string) => `${Number(m.slice(0, 4)) - 1}${m.slice(4)}`;
const pctTxt = (a: number, b: number) => (b > 0 ? `${a >= b ? "+" : "−"}${Math.abs((a / b - 1) * 100).toFixed(1)}%` : "—");

export default function Overview() {
  const { now, go } = useClock();
  const { hotel: site, setHotel } = useHotel();
  const month = now.slice(0, 7);
  const ms = useMonthSavings(month, now, false);                 // Option C and the hourly files only; the plan comes from adherence.json
  const bills = useBillsAt(now);
  const changes = useChangesAt(bills);
  const alerts = useAlertsAt(now);

  // this month so far vs the same days and hours last year (meter-fault hours left out of both, as for Option C)
  const cost = useMemo(() => {
    const h = ms.hourly[site], oc = ms.optionC?.bySite[site];
    if (!h || !bills || !oc) return null;
    const ly = lastYear(month), cut = lastYear(now.slice(0, 13));
    let a = 0, k = 0;
    h.t.forEach((t, i) => { if (t.slice(0, 7) === ly && t <= cut && !h.f[i]) { a += h.a[i]; k++; } });
    const rateLy = rateOf(bills.recon, site, ly);
    return { kwh: oc.actual, inr: oc.actual * oc.rate, base_kwh: oc.baseline, base_inr: oc.baseline * oc.rate, ly_kwh: k ? a : null, ly_inr: k ? a * rateLy : null, hours: oc.hours };
  }, [ms.hourly[site], ms.optionC, bills, site, month, now.slice(0, 13)]);

  // the latest pair of consecutive bills that can be split (within one data year)
  const ch = useMemo(() => {
    if (!bills || !changes) return null;
    const months = bills.recon.filter((r) => r.site === site).map((r) => r.month).sort();
    for (let i = months.length - 1; i > 0; i--) {
      const c = changes[`${site}|${months[i - 1]}|${months[i]}`];
      if (c) return { a: months[i - 1], b: months[i], c };
    }
    return null;
  }, [bills, changes, site]);
  const steps = ch ? Object.entries(ch.c.groups).filter(([, v]) => Math.abs(v) >= 1).sort((p, q) => Math.abs(q[1]) - Math.abs(p[1])) : [];

  const acks = loadAcks();
  // repeats of the same problem at the hotel are one row: how many times, the total ₹, still running if any one is
  const top = useMemo(() => {
    const g: Record<string, { rule: string; title: string; n: number; inr: number; running: boolean; ids: string[] }> = {};
    for (const a of alerts ?? []) {
      if (a.site !== site || a.start.slice(0, 7) !== month || a.cost <= 0 || a.rule === "PLAN_DEVIATION") continue;
      const x = (g[a.rule] ??= { rule: a.rule, title: RULE[a.rule]?.title ?? a.title, n: 0, inr: 0, running: false, ids: [] });
      x.n++; x.inr += a.cost; x.running ||= !!a.ongoing; x.ids.push(a.id);
    }
    return Object.values(g).sort((x, y) => y.inr - x.inr).slice(0, 5);
  }, [alerts, site, month]);

  // daily-plan adherence: the month's complete days precomputed at build time (reports/adherence.json, shown at once), plus the days since
  // then - normally just today - checked against the meters in the background
  const pre = useData<Adherence>("reports/adherence.json");
  const [fresh, setFresh] = useState<{ key: string; days: Record<string, Day> } | null>(null);
  const key = `${site}|${month}|${pre?.upto ?? ""}|${now.slice(0, 13)}`;
  useEffect(() => {
    if (!pre || month < "2026-10") return;
    let on = true;
    const from = pre.upto, to = now.slice(0, 10);
    loadMonthPlans(month, site).then(async (saved) => {
      const days: Record<string, Day> = {};
      for (const d of Object.keys(saved).filter((d) => d > from && d <= to).sort()) {
        const c = await checkPlan(d, `${now.slice(0, 13)}:00`, saved[d], "saved", site);
        if (c) days[d] = c.summary;
      }
      if (on) setFresh({ key, days });
    }).catch(() => on && setFresh({ key, days: {} }));
    return () => { on = false; };
  }, [key, !!pre]);
  const days = { ...(pre?.sites[site]?.[month] ?? {}), ...(fresh?.key === key ? fresh.days : {}) };
  const adh = pre ? Object.values(days).reduce((x, d) => ({ due: x.due + d.due, followed: x.followed + d.followed, partly: x.partly + d.partly,
    not: x.not + d.not_followed, ver: x.ver + d.verified_inr, miss: x.miss + d.missed_inr }), { due: 0, followed: 0, partly: 0, not: 0, ver: 0, miss: 0 }) : null;
  const updating = !!pre && fresh?.key !== key;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{SITE_NAME[site]} this month</h1>
          <p className="lead">{fmtMonth(month)} so far, up to {now.slice(8, 10)}/{now.slice(5, 7)} {now.slice(11, 16)}. Everything here comes from the meters, the bills and the plan log.</p>
        </div>
        <SiteSwitch value={site} onChange={(s) => s !== "ALL" && setHotel(s as Site)} all={false} />
      </div>

      <div className="grid g3">
        <div className="stat"><span>Electricity so far</span><b>{cost ? inr(cost.inr) : "…"}</b><em>{cost ? `${n(cost.kwh)} kWh at the latest bill's average rate` : "loading"}</em></div>
        <div className="stat"><span>vs what the weather, guests and events called for</span>
          <b style={{ color: cost && cost.kwh > cost.base_kwh ? "var(--coral)" : undefined }}>{cost ? pctTxt(cost.kwh, cost.base_kwh) : "…"}</b>
          <em>{cost ? `adjusted baseline ${inr(cost.base_inr)}: ${inr(Math.abs(cost.base_inr - cost.inr))} ${cost.inr <= cost.base_inr ? "below" : "above"}` : "loading"}</em></div>
        <div className="stat"><span>vs the same days last year</span><b>{cost?.ly_inr != null ? pctTxt(cost.inr, cost.ly_inr) : "—"}</b>
          <em>{cost?.ly_inr != null ? `${inr(cost.ly_inr)} last year (${n(cost.ly_kwh!)} kWh), not adjusted for weather or guests` : cost ? "no readings for these days last year" : "loading"}</em></div>
      </div>

      <div className="section-title"><h2>What drove the latest bill change</h2><button className="btn ghost" onClick={() => go("costs")}>Monthly costs</button></div>
      {!ch ? <p className="muted">{changes ? "No two bills from the same data year to compare yet." : "Loading…"}</p> : (
        <div className="split">
          <div className="panel">
            <Waterfall start={ch.c.bill_a} end={ch.c.bill_b} startLabel={fmtMonth(ch.a)} endLabel={fmtMonth(ch.b)} steps={steps.map(([k, v]) => ({ label: DRIVER[k] ?? k, value: v }))} />
          </div>
          <div>
            <p style={{ fontSize: 18, lineHeight: 1.4, margin: "4px 0 12px" }}>The {fmtMonth(ch.b)} bill was <strong>{inr(ch.c.bill_b)}</strong>, {inr(Math.abs(ch.c.delta))} {ch.c.delta >= 0 ? "more" : "less"} than {fmtMonth(ch.a)}.</p>
            <ol style={{ paddingLeft: 20, margin: 0, display: "grid", gap: 8 }}>{steps.slice(0, 3).map(([k, v]) => <li key={k}>{sentence(k, v, ch.c.context, ch.c)}</li>)}</ol>
          </div>
        </div>
      )}

      <div className="split" style={{ marginTop: 18 }}>
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Top problems this month</h3>
          {!alerts ? <p className="muted">Loading…</p> : top.length === 0 ? <p className="muted" style={{ margin: 0 }}>No costed problems so far this month.</p> : (
            <table className="t">
              <thead><tr><th>Problem</th><th className="r">Cost</th><th>Status</th></tr></thead>
              <tbody>{top.map((a) => {
                const ack = a.ids.map((i) => acks[i]).filter(Boolean).at(-1);
                return (
                <tr key={a.rule}><td>{a.title}{a.n > 1 && <span className="muted"> · {a.n} times</span>}{NOT_CLAIMED.has(a.rule) && <div className="small muted">cause under investigation; not counted as waste</div>}</td>
                  <td className="r">{inr(a.inr)}</td>
                  <td className="small">{a.running ? "still running" : "resolved"}{ack ? ` · ${ack.response.toLowerCase()}` : ""}</td></tr>
              ); })}</tbody>
            </table>
          )}
        </div>
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Daily plan this month</h3>
          {!adh ? <p className="muted">Loading…</p> : adh.due === 0 ? (
            <p className="muted" style={{ margin: 0 }}>No approved plan steps were due yet this month.</p>
          ) : (
            <>
              <p style={{ fontSize: 22, fontWeight: 700, margin: "0 0 4px" }}>{adh.followed} of {adh.due} approved steps followed</p>
              <p className="small" style={{ margin: 0 }}>{adh.partly ? `${adh.partly} partly, ` : ""}{adh.not} not followed · <strong style={{ color: "var(--green)" }}>{inr(adh.ver)} saved</strong> / <strong style={{ color: "var(--coral)" }}>{inr(adh.miss)} missed</strong>, checked against the meters.</p>
            </>
          )}
          {pre && <p className="small muted" style={{ margin: "6px 0 0" }}>{updating ? "Checking today against the meters…" : `Up to ${now.slice(11, 16)} today; days to ${pre.upto.slice(8, 10)}/${pre.upto.slice(5, 7)} were checked in advance.`}</p>}
          <p className="guard small" style={{ marginTop: 14 }}><span aria-hidden>🛡</span><span>Guest comfort limits are never relaxed to save energy.</span></p>
        </div>
      </div>
    </>
  );
}
