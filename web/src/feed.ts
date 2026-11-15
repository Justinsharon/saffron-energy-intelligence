// Today's view of each hotel. Live: the feed function (/.netlify/functions/feed), refreshed every 5 minutes; it only ever returns rows
// up to the current IST hour. If the function can't be reached (local dev, offline) the same cut is made here from the static files
// with the same code (feedcore.feedFor). Looking back: built locally for the chosen hour, from whichever year it falls in.
import { useEffect, useState } from "react";
import { load, SITES, type Alert, type Bills, type Fault, type Hourly, type Site } from "./data";
import { feedFor, istNow, joinHourly, type Feed, type FeedSource } from "./feedcore";

export interface Feeds { feeds: Record<Site, Feed>; updated: string; via: "feed" | "local" }

let src: Promise<Record<Site, FeedSource>> | null = null;
function localSource(): Promise<Record<Site, FeedSource>> {
  const both = <T,>(n: string) => Promise.all([load<T>(n), load<T>(`live_feed/${n}`).catch(() => null)]);
  return (src ??= Promise.all([both<Alert[]>("alerts.json"), both<Fault[]>("faults.json"), both<Bills>("bills.json"),
                               ...SITES.map((s) => both<Hourly>(`hourly_${s}.json`))]).then(([al, fa, bi, ...hr]) => {
    const alerts = [...al[0], ...(al[1] ?? [])], faults = [...fa[0], ...(fa[1] ?? [])], recon = [...bi[0].recon, ...(bi[1]?.recon ?? [])];
    return Object.fromEntries(SITES.map((s, i) => [s, { hourly: hr[i][1] ? joinHourly(hr[i][0], hr[i][1]!) : hr[i][0], alerts, faults, recon }])) as Record<Site, FeedSource>;
  }));
}

async function fromFunction(): Promise<Record<Site, Feed>> {
  const xs = await Promise.all(SITES.map(async (s) => {
    const r = await fetch(`/.netlify/functions/feed?site=${s}&hours=48`);
    if (!r.ok || !(r.headers.get("content-type") ?? "").includes("json")) throw new Error("feed unavailable");
    const j = (await r.json()) as Feed;
    if (!j.readings) throw new Error("bad feed");
    return j;
  }));
  return Object.fromEntries(xs.map((f) => [f.site, f])) as Record<Site, Feed>;
}

export function useFeeds(now: string, live: boolean): Feeds | null {
  const [v, setV] = useState<Feeds | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!live) return;
    const t = setInterval(() => setTick((x) => x + 1), 5 * 60e3);
    return () => clearInterval(t);
  }, [live]);
  useEffect(() => {
    let on = true;
    (async () => {
      const at = live ? istNow() : now;
      if (live) {
        try { const f = await fromFunction(); if (on) setV({ feeds: f, updated: at, via: "feed" }); return; } catch { /* fall back to the static files */ }
      }
      const s = await localSource();
      if (on) setV({ feeds: Object.fromEntries(SITES.map((x) => [x, feedFor(x, at, 48, s[x])])) as Record<Site, Feed>, updated: at, via: "local" });
    })();
    return () => { on = false; };
  }, [live, live ? tick : now]);
  return v;
}
