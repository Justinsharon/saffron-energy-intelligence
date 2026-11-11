import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import Shift, { TodayHero } from "./pages/Shift";
import Demand from "./pages/Demand";
import Engineering from "./pages/Engineering";
import GM from "./pages/GM";
import Finance from "./pages/Finance";
import Ask from "./pages/Ask";
import Rate from "./pages/Rate";
import Method from "./pages/Method";
import { addMs, DATA_FIRST, DATA_LAST, FEED_OFFSET_MS, fmtDT, istNow } from "./format";

const I = (d: string) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d={d} /></svg>;
export const ICON: Record<string, ReactNode> = {
  today: I("M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z"),
  demand: I("M13 2 4 14h7l-1 8 9-12h-7z"),
  equipment: I("M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z"),
  costs: I("M3 3v18h18M7 15l4-4 3 3 5-6"),
  bills: I("M6 2h9l5 5v15H6zM14 2v6h6M9 13h6M9 17h6"),
  ask: I("M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"),
  feedback: I("M14 9V5a3 3 0 0 0-6 0v4H4l2 12h12l2-12z"),
  accuracy: I("M9 12l2 2 4-4M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z"),
  calendar: I("M4 5h16v16H4zM4 10h16M9 3v4M15 3v4"),
  search: I("M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4"),
  mic: I("M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3"),
  arrow: I("M5 12h14M13 6l6 6-6 6"),
};

export const PAGES = [
  { id: "today", label: "Today", hint: "What needs attention now" },
  { id: "demand", label: "Peak demand", hint: "Tomorrow's power limit risk" },
  { id: "equipment", label: "Equipment", hint: "Repeat problems and patterns" },
  { id: "costs", label: "Monthly costs", hint: "Why the bill went up or down" },
  { id: "bills", label: "Bills & savings", hint: "Bill checks and where to save" },
  { id: "ask", label: "Ask", hint: "Questions in plain words" },
] as const;
const MORE = [
  { id: "feedback", label: "Alert feedback" },
  { id: "accuracy", label: "How accurate is it?" },
] as const;
type PageId = (typeof PAGES)[number]["id"] | (typeof MORE)[number]["id"];
const OLD: Record<string, PageId> = { shift: "today", engineering: "equipment", gm: "costs", finance: "bills", rate: "feedback", method: "accuracy" };

/** `now` is what the screen calls "now"; `dataNow` is the matching hour in the meter data. Live: today, replayed from the same
 *  weekday 52 weeks earlier (the sample feed ends 30 Sep 2026). Looking back: a past hour, shown as it was (offset 0). */
interface Clock { now: string; dataNow: string; offset: number; live: boolean; setNow: (s: string | null) => void; go: (p: PageId) => void }
const Ctx = createContext<Clock>({ now: istNow(), dataNow: addMs(istNow(), -FEED_OFFSET_MS), offset: FEED_OFFSET_MS, live: true, setNow: () => {}, go: () => {} });
export const useClock = () => useContext(Ctx);

function readHash(): PageId {
  const h = window.location.hash.replace("#/", "").split("?")[0];
  if (OLD[h]) return OLD[h];
  return ([...PAGES, ...MORE].map((p) => p.id) as string[]).includes(h) ? (h as PageId) : "today";
}

export default function App() {
  const [page, setPage] = useState<PageId>(readHash());
  const [real, setReal] = useState(istNow());
  const [past, setPast] = useState<string | null>(null);
  useEffect(() => { const t = setInterval(() => setReal(istNow()), 30e3); return () => clearInterval(t); }, []);
  useEffect(() => { const f = () => setPage(readHash()); window.addEventListener("hashchange", f); return () => window.removeEventListener("hashchange", f); }, []);
  const go = (p: PageId) => { window.location.hash = `#/${p}`; setPage(p); window.scrollTo(0, 0); };
  const live = past == null;
  const now = past ?? real;
  const offset = live ? FEED_OFFSET_MS : 0;
  const clock: Clock = { now, dataNow: addMs(now, -offset), offset, live, setNow: setPast, go };
  const date = now.slice(0, 10), hour = Number(now.slice(11, 13));
  const pickRef = useRef<HTMLInputElement>(null);
  const openPicker = () => { const el = pickRef.current; if (!el) return; try { el.showPicker(); } catch { el.focus(); } };
  return (
    <Ctx.Provider value={clock}>
      <div className="shell">
       <div className="frame">
        <header className="top">
          <div className="brand">
            <span className="circle dark" aria-hidden><svg width="18" height="18" viewBox="0 0 32 32"><path d="M17 3 8 18h6.5l-2 11L23 13h-6.5z" fill="#E8613C" /></svg></span>
            <span>Saffron Suites<small>Energy</small></span>
          </div>
          <span className="spacer" />
          <span className="clock">
            {live && <span className="live-dot" aria-hidden />}
            <span>{live ? "Live" : "Looking back at"}</span>
            <strong>{fmtDT(now)}{live ? " IST" : ""}</strong>
          </span>
          <span className="when">
            {!live && (
              <>
                <input aria-label="Date" type="date" min={DATA_FIRST} max={DATA_LAST} value={date}
                       onChange={(e) => e.target.value && setPast(`${e.target.value}T${String(hour).padStart(2, "0")}:00`)} />
                <select aria-label="Time" value={hour} onChange={(e) => setPast(`${date}T${e.target.value.padStart(2, "0")}:00`)}>
                  {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}
                </select>
                <button className="btn accent" onClick={() => setPast(null)}>Back to today</button>
              </>
            )}
            <span style={{ position: "relative" }}>
              <button className="circle" title="Look back to a past day" aria-label="Look back to a past day" onClick={openPicker}>{ICON.calendar}</button>
              <input ref={pickRef} type="date" min={DATA_FIRST} max={DATA_LAST} value="" tabIndex={-1} aria-hidden
                     onChange={(e) => e.target.value && setPast(`${e.target.value}T10:00`)}
                     style={{ position: "absolute", inset: 0, opacity: 0, pointerEvents: "none" }} />
            </span>
          </span>
          <button className="search" onClick={() => go("ask")}><span className="circle">{ICON.search}</span><span className="search-label">Ask anything about the hotels…</span></button>
        </header>
        <nav className="nav" aria-label="Sections">
          {PAGES.map((p) => (
            <button key={p.id} title={p.hint} aria-current={page === p.id ? "page" : undefined} onClick={() => go(p.id)}>{ICON[p.id]}{p.label}</button>
          ))}
          <span className="sep" aria-hidden />
          {MORE.map((p) => (
            <button key={p.id} className="minor" aria-current={page === p.id ? "page" : undefined} onClick={() => go(p.id)}>{p.label}</button>
          ))}
        </nav>
        {page === "today" && <TodayHero />}
        <div className="content">
          <main>
            {page === "today" && <Shift />}
            {page === "demand" && <Demand />}
            {page === "equipment" && <Engineering />}
            {page === "costs" && <GM />}
            {page === "bills" && <Finance />}
            {page === "ask" && <Ask />}
            {page === "feedback" && <Rate />}
            {page === "accuracy" && <Method />}
          </main>
          <footer className="foot">
            <span>Live date and weather. Meter readings are a sample feed (Oct 2025 – Sep 2026), replayed from the same weekday last year until the hotels' meters are connected. Tariff rates are illustrative. Every change is recommended, never made automatically.</span>
          </footer>
        </div>
       </div>
      </div>
    </Ctx.Provider>
  );
}
