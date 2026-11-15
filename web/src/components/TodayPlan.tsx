import { useEffect, useState } from "react";
import { TAG } from "../plan";
import type { PlanView, SavedAction } from "../planlog";
import { loadPlan } from "../planStore";

const hourOf = (t: string) => Number(t.slice(0, 2)) + (t.includes("next day") ? 24 : 0);

/** Today's operating plan (Gurugram), as saved the day before: what is due next, what is approved, and how much is done. */
export function TodayPlanCard({ now, onPlan }: { now: string; onPlan: () => void }) {
  const date = now.slice(0, 10);
  const [v, setV] = useState<PlanView | null | undefined>(undefined);
  useEffect(() => { let on = true; setV(undefined); loadPlan(date).then((x) => on && setV(x)).catch(() => on && setV(null)); }, [date]);
  if (v === undefined) return null;
  const head = <div className="section-title" style={{ marginTop: 8 }}><h2>Today's plan, Gurugram</h2><button className="btn ghost" onClick={onPlan}>Tomorrow's plan</button></div>;
  if (!v || !v.plan) {
    return (<>{head}<div className="panel flat today-plan"><p style={{ margin: 0 }}><strong>No plan was saved for today.</strong> Plans are made the day before: enter the bookings on <button className="ask-inline" onClick={onPlan}>Tomorrow's plan</button> and approve the steps, so the night shift knows how to run the chillers, laundry and water heating.</p></div></>);
  }
  const h = Number(now.slice(11, 13)) + Number(now.slice(14, 16)) / 60;
  const acts: (SavedAction & { s: number; e: number })[] = v.plan.actions.map((a) => {
    const ed = v.edits[a.id];
    return { ...a, start: ed?.start ?? a.start, end: ed?.end ?? a.end, s: hourOf(ed?.start ?? a.start), e: hourOf(ed?.end ?? a.end) };
  });
  const st = (a: SavedAction) => v.decisions[a.id]?.event;
  const approved = acts.filter((a) => st(a) === "approve");
  const done = approved.filter((a) => a.e <= h);
  const next = acts.filter((a) => a.e > h && st(a) !== "skip").sort((x, y) => x.s - y.s).slice(0, 3);
  const pending = acts.filter((a) => !st(a)).length;
  return (
    <>
      {head}
      <div className="panel flat today-plan">
        <p style={{ margin: 0 }}><strong>{done.length} of {acts.length} done</strong> · {approved.length} approved{pending ? `, ${pending} not yet approved` : ""} · saved by {v.plan.by} at {v.plan.at.slice(11)} on {v.plan.at.slice(8, 10)}/{v.plan.at.slice(5, 7)}
          {v.storage === "device" ? " (this device only)" : ""}</p>
        {next.length > 0 ? (
          <div className="next">
            {next.map((a) => (
              <div key={a.id}>
                <span className="t">{a.s <= h ? "now" : a.start.replace(" (next day)", "")}–{a.end === "00:00 (next day)" ? "midnight" : a.end.replace(" (next day)", "⁺¹")}</span>
                <span className="tag">{TAG[a.group]}</span>
                <span>{a.setting}</span>
                <span className={`st ${st(a) === "approve" ? "ok" : ""}`}>{st(a) === "approve" ? `approved by ${v.decisions[a.id].by}` : "needs approval"}</span>
              </div>
            ))}
          </div>
        ) : <p className="muted small">Nothing else is due today.</p>}
        {v.plan.inputs.notes && <p className="small" style={{ margin: 0 }}><strong>Notes:</strong> {v.plan.inputs.notes}</p>}
      </div>
    </>
  );
}
