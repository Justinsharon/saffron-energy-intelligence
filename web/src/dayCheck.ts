// Plan vs actual for the day on screen (Gurugram): the saved plan if there is one, else the API's suggested plan; checked up to the hour
// shown (live: now; looking back: that hour). Used by the Today's plan card and to put PLAN_DEVIATION alerts into Today's alerts.
import { useEffect, useState } from "react";
import { checkPlan, type CheckResult } from "./planApi";
import { checkActions, type PlanView } from "./planlog";
import { loadPlan } from "./planStore";

export interface DayCheck { view: PlanView | null; check: CheckResult | null }

export function useDayCheck(now: string): DayCheck | undefined {
  const date = now.slice(0, 10), hour = now.slice(0, 13);
  const [v, setV] = useState<DayCheck | undefined>(undefined);
  useEffect(() => {
    let on = true;
    if (date < "2026-10-02") { setV({ view: null, check: null }); return; }        // the original year has no plans
    (async () => {
      const view = await loadPlan(date).catch(() => null);
      const acts = view?.plan ? checkActions(view) : undefined;
      const check = await checkPlan(date, `${hour}:00`, acts, acts ? "saved" : undefined);
      if (on) setV({ view, check });
    })();
    return () => { on = false; };
  }, [date, hour]);
  return v;
}
