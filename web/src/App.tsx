import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import Shift from "./pages/Shift";
import Demand from "./pages/Demand";
import Engineering from "./pages/Engineering";
import GM from "./pages/GM";
import Finance from "./pages/Finance";
import Ask from "./pages/Ask";
import Rate from "./pages/Rate";
import Method from "./pages/Method";
import { fmtDT } from "./format";

const I = (d: string) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d={d} /></svg>;
const ICON: Record<string, ReactNode> = {
  today: I("M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z"),
  demand: I("M13 2 4 14h7l-1 8 9-12h-7z"),
  equipment: I("M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z"),
  costs: I("M3 3v18h18M7 15l4-4 3 3 5-6"),
  bills: I("M6 2h9l5 5v15H6zM14 2v6h6M9 13h6M9 17h6"),
  ask: I("M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"),
  feedback: I("M14 9V5a3 3 0 0 0-6 0v4H4l2 12h12l2-12z"),
  accuracy: I("M9 12l2 2 4-4M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z"),
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

interface Clock { now: string; setNow: (s: string) => void; go: (p: PageId) => void }
const Ctx = createContext<Clock>({ now: "2026-05-24T10:00", setNow: () => {}, go: () => {} });
export const useClock = () => useContext(Ctx);

function readHash(): PageId {
  const h = window.location.hash.replace("#/", "").split("?")[0];
  if (OLD[h]) return OLD[h];
  return ([...PAGES, ...MORE].map((p) => p.id) as string[]).includes(h) ? (h as PageId) : "today";
}

export default function App() {
  const [page, setPage] = useState<PageId>(readHash());
  const [now, setNow] = useState("2026-05-24T10:00");
  useEffect(() => { const f = () => setPage(readHash()); window.addEventListener("hashchange", f); return () => window.removeEventListener("hashchange", f); }, []);
  const go = (p: PageId) => { window.location.hash = `#/${p}`; setPage(p); window.scrollTo(0, 0); };
  const date = now.slice(0, 10), hour = Number(now.slice(11, 13));
  return (
    <Ctx.Provider value={{ now, setNow, go }}>
      <div className="shell">
        <aside className="side">
          <div className="brand">
            <span className="brand-mark" aria-hidden><svg width="16" height="16" viewBox="0 0 32 32"><path d="M17 3 8 18h6.5l-2 11L23 13h-6.5z" fill="#E3A23B" /></svg></span>
            <span>Saffron Suites<small>Energy</small></span>
          </div>
          <nav className="nav" aria-label="Sections">
            {PAGES.map((p) => (
              <button key={p.id} aria-current={page === p.id ? "page" : undefined} onClick={() => go(p.id)}>
                {ICON[p.id]}<span><b>{p.label}</b><small>{p.hint}</small></span>
              </button>
            ))}
          </nav>
          <nav className="nav nav-more" aria-label="More">
            {MORE.map((p) => (
              <button key={p.id} aria-current={page === p.id ? "page" : undefined} onClick={() => go(p.id)}>{ICON[p.id]}<span><b>{p.label}</b></span></button>
            ))}
          </nav>
          <p className="side-foot">Gurugram · Jaipur · Goa</p>
        </aside>
        <div className="content">
          <div className="topline">
            <span className="muted small">Showing</span>
            <strong className="small">{fmtDT(now)}</strong>
            <span className="when">
              <input aria-label="Date" type="date" min="2025-10-01" max="2026-09-30" value={date}
                     onChange={(e) => e.target.value && setNow(`${e.target.value}T${String(hour).padStart(2, "0")}:00`)} />
              <select aria-label="Time" value={hour} onChange={(e) => setNow(`${date}T${e.target.value.padStart(2, "0")}:00`)}>
                {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}
              </select>
            </span>
          </div>
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
            <span>Demo with sample data for Saffron Suites (Oct 2025 – Sep 2026); tariff rates are illustrative. Every change is recommended, never made automatically.</span>
          </footer>
        </div>
      </div>
    </Ctx.Provider>
  );
}
