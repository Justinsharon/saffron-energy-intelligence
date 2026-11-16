import { TAG } from "../plan";
import type { DayCheck } from "../dayCheck";
import type { CheckStep } from "../planApi";
import { inr } from "../format";
import { SITE_NAME } from "../data";

const hourOf = (t: string) => Number(t.slice(0, 2)) + (t.includes("next day") ? 24 : 0);
const BADGE: Record<string, string> = { Followed: "ok", Partly: "", "Not followed": "bad", Skipped: "", "Not yet due": "" };
const span = (start: string, end: string, h: number, s: number) =>
  `${s <= h ? "now" : start.replace(" (next day)", "")}–${end === "00:00 (next day)" ? "midnight" : end.replace(" (next day)", "⁺¹")}`;

/** Today's operating plan (the hotel selected on Today; Gurugram when all are shown): what is due next, what is approved, and - checked against the meters up to the hour shown - which
 *  steps were followed. With no saved plan, the suggested plan is shown and checked, clearly marked as not approved. */
export function TodayPlanCard({ now, dc, onPlan }: { now: string; dc: DayCheck | undefined; onPlan: () => void }) {
  if (dc === undefined || now.slice(0, 10) < "2026-10-02") return null;
  const v = dc.view, chk = dc.check;
  const head = <div className="section-title" style={{ marginTop: 8 }}><h2>Today's plan, {SITE_NAME[dc.site]}</h2><button className="btn ghost" onClick={onPlan}>Tomorrow's plan</button></div>;
  const h = Number(now.slice(11, 13)) + Number(now.slice(14, 16)) / 60;
  const steps: (CheckStep & { s: number; e: number })[] = (chk?.steps ?? []).map((x) => ({ ...x, s: hourOf(x.start), e: hourOf(x.end) }));
  const decision = (id: string) => v?.decisions[id]?.event;
  const due = steps.filter((x) => x.status !== "Not yet due");
  const next = steps.filter((x) => x.e > h && x.status !== "Skipped").sort((a, b) => a.s - b.s).slice(0, 3);
  const summary = chk && (chk.summary.approved === 0 ? (chk.summary.would_have_saved_inr >= 1 &&
    <p className="small muted" style={{ margin: "8px 0 0" }}>Suggested, not approved: would have saved {inr(chk.summary.would_have_saved_inr)} if followed. Not counted.</p>)
    : chk.summary.due > 0 && (
    <p className="small" style={{ margin: "8px 0 0" }}><strong>{chk.summary.followed} of {chk.summary.due} approved steps followed</strong>
      {chk.summary.not_followed ? `, ${chk.summary.not_followed} not followed` : ""} · {inr(chk.summary.verified_inr)} saved / {inr(chk.summary.missed_inr)} missed so far</p>
  ));
  const notFollowed = due.filter((x) => x.status === "Not followed").slice(0, 2);
  const rows = (
    <div className="next">
      {next.map((x) => (
        <div key={x.id}>
          <span className="t">{span(x.start, x.end, h, x.s)}</span>
          <span className="tag">{TAG[x.group as keyof typeof TAG]}</span>
          <span>{x.setting}</span>
          <span className={`st ${["Followed", "Partly", "Not followed"].includes(x.status) ? BADGE[x.status] ?? "" : decision(x.id) === "approve" ? "ok" : ""}`}>
            {["Followed", "Partly", "Not followed"].includes(x.status) ? x.status.toLowerCase() + " so far" : !v?.plan ? "suggested, not approved"
              : x.status === "Skipped" ? "skipped" : decision(x.id) === "approve" ? `approved by ${v.decisions[x.id].by}` : "needs approval"}</span>
        </div>
      ))}
      {notFollowed.filter((x) => !next.includes(x)).map((x) => (
        <div key={x.id}><span className="t">{x.start.replace(" (next day)", "")}–{x.end.replace(" (next day)", "")}</span><span className="tag">{TAG[x.group as keyof typeof TAG]}</span>
          <span>{x.setting}</span><span className="st bad">not followed{x.extra_inr >= 1 ? ` · ${inr(x.extra_inr)}` : ""}</span></div>
      ))}
    </div>
  );
  if (!v?.plan) {
    return (<>{head}<div className="panel flat today-plan">
      <p style={{ margin: 0 }}><strong>No plan was saved for today.</strong> Plans are made the day before: enter the bookings on <button className="ask-inline" onClick={onPlan}>Tomorrow's plan</button> and approve the steps, so the night shift knows how to run the chillers, laundry and {dc.site === "GGN" ? "water heating" : dc.site === "GOA" ? "pool pumps" : "event lighting"}.</p>
      {steps.length > 0 && <p className="small muted" style={{ margin: "10px 0 0" }}>The suggested plan (usual pattern, no bookings), shown for reference only: not approved, so not checked or counted.</p>}
      {steps.length > 0 && rows}
      {summary}
      {chk === null && <p className="small muted" style={{ margin: "8px 0 0" }}>The plan check needs the planning service, which did not answer.</p>}
    </div></>);
  }
  const acts = v.plan.actions;
  const approved = acts.filter((a) => decision(a.id) === "approve").length;
  const pending = acts.filter((a) => !decision(a.id)).length;
  return (
    <>
      {head}
      <div className="panel flat today-plan">
        <p style={{ margin: 0 }}><strong>{approved} of {acts.length} approved</strong>{pending ? `, ${pending} not yet approved` : ""} · saved by {v.plan.by} at {v.plan.at.slice(11)} on {v.plan.at.slice(8, 10)}/{v.plan.at.slice(5, 7)}
          {v.storage === "device" ? " (this device only)" : ""}</p>
        {next.length > 0 || notFollowed.length ? rows : <p className="muted small">Nothing else is due today.</p>}
        {summary}
        {v.plan.inputs.notes && <p className="small" style={{ margin: "6px 0 0" }}><strong>Notes:</strong> {v.plan.inputs.notes}</p>}
      </div>
    </>
  );
}
