// Plan vs actual for the day on screen (the hotel selected on Today; Gurugram when all hotels are shown): the saved plan if there is one, else the API's suggested plan; checked up to the hour
// shown (live: now; looking back: that hour). Used by the Today's plan card and to put PLAN_DEVIATION alerts into Today's alerts.
import { useEffect, useState } from "react";
import { checkPlan, RETRY_TIMEOUT_MS, type CheckResult } from "./planApi";
import { checkActions, isScenario, type PlanView } from "./planlog";
import { loadPlan } from "./planStore";
import type { PlanSite } from "./plan";

export interface DayCheck { view: PlanView | null; check: CheckResult | null; site: PlanSite }

export function useDayCheck(now: string, site: PlanSite = "GGN"): DayCheck | undefined {
  const date = now.slice(0, 10), hour = now.slice(0, 13);
  const [v, setV] = useState<DayCheck | undefined>(undefined);
  useEffect(() => {
    let on = true;
    setV(undefined);
    if (date < "2026-10-02") { setV({ view: null, check: null, site }); return; }        // the original year has no plans
    (async () => {
      const view = await loadPlan(date, site).catch(() => null);
      // a weather-scenario plan is a what-if: never checked against the real meters (no verified ₹, no deviation alerts)
      const acts = view?.plan && !isScenario(view.plan.inputs) ? checkActions(view) : undefined;
      const check = await checkPlan(date, `${hour}:00`, acts, acts ? "saved" : undefined, site);
      if (on) setV({ view, check, site });
      // no answer (often a cold start): keep what is shown, ask once more in the background with a longer wait
      if (!check) {
        const again = await checkPlan(date, `${hour}:00`, acts, acts ? "saved" : undefined, site, RETRY_TIMEOUT_MS);
        if (on && again) setV({ view, check: again, site });
      }
    })();
    return () => { on = false; };
  }, [date, hour, site]);
  return v;
}
