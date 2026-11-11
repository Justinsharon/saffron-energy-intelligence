import { createContext, useContext, useEffect, useState } from "react";
import Shift from "./pages/Shift";
import Demand from "./pages/Demand";
import Engineering from "./pages/Engineering";
import GM from "./pages/GM";
import Finance from "./pages/Finance";
import Ask from "./pages/Ask";
import Rate from "./pages/Rate";
import Method from "./pages/Method";

export const PAGES = [
  { id: "shift", label: "Shift", who: "Duty engineer" },
  { id: "demand", label: "Demand", who: "Duty / chief engineer" },
  { id: "engineering", label: "Engineering", who: "Chief engineer" },
  { id: "gm", label: "GM", who: "General manager" },
  { id: "finance", label: "Finance", who: "Finance controller" },
  { id: "ask", label: "Ask", who: "Anyone" },
] as const;
const EXTRA = ["rate", "method"] as const;
type PageId = (typeof PAGES)[number]["id"] | (typeof EXTRA)[number];

interface Clock { now: string; setNow: (s: string) => void; go: (p: PageId) => void }
const Ctx = createContext<Clock>({ now: "2026-05-24T10:00", setNow: () => {}, go: () => {} });
export const useClock = () => useContext(Ctx);

function readHash(): PageId {
  const h = window.location.hash.replace("#/", "").split("?")[0];
  return ([...PAGES.map((p) => p.id), ...EXTRA] as string[]).includes(h) ? (h as PageId) : "shift";
}

export default function App() {
  const [page, setPage] = useState<PageId>(readHash());
  const [now, setNow] = useState("2026-05-24T10:00");
  useEffect(() => { const f = () => setPage(readHash()); window.addEventListener("hashchange", f); return () => window.removeEventListener("hashchange", f); }, []);
  const go = (p: PageId) => { window.location.hash = `#/${p}`; setPage(p); window.scrollTo(0, 0); };
  const date = now.slice(0, 10), hour = Number(now.slice(11, 13));
  return (
    <Ctx.Provider value={{ now, setNow, go }}>
      <header className="bar">
        <div className="bar-in">
          <div className="brand">
            <span className="brand-mark" aria-hidden>
              <svg width="15" height="15" viewBox="0 0 32 32"><path d="M17 3 8 18h6.5l-2 11L23 13h-6.5z" fill="#E3A23B" /></svg>
            </span>
            <span>Saffron Suites<small>Energy desk</small></span>
          </div>
          <nav className="tabs" aria-label="Views">
            {PAGES.map((p) => (
              <button key={p.id} className="tab" aria-current={page === p.id ? "page" : undefined} onClick={() => go(p.id)} title={p.who}>{p.label}</button>
            ))}
          </nav>
          <div className="clock" title="Replay: the data covers 1 Oct 2025 – 30 Sep 2026. The product shows only what was known at this moment.">
            <label htmlFor="d">As of</label>
            <input id="d" type="date" min="2025-10-01" max="2026-09-30" value={date}
                   onChange={(e) => e.target.value && setNow(`${e.target.value}T${String(hour).padStart(2, "0")}:00`)} />
            <input aria-label="Hour" type="range" min={0} max={23} value={hour} onChange={(e) => setNow(`${date}T${e.target.value.padStart(2, "0")}:00`)} />
            <span className="num" style={{ minWidth: 42 }}>{String(hour).padStart(2, "0")}:00</span>
          </div>
        </div>
      </header>
      <main>
        {page === "shift" && <Shift />}
        {page === "demand" && <Demand />}
        {page === "engineering" && <Engineering />}
        {page === "gm" && <GM />}
        {page === "finance" && <Finance />}
        {page === "ask" && <Ask />}
        {page === "rate" && <Rate />}
        {page === "method" && <Method />}
      </main>
      <footer className="foot">
        <span>Synthetic data, fictional hotels, illustrative tariffs. The product recommends; a person approves every action.</span>
        <span style={{ display: "flex", gap: 14 }}>
          <button onClick={() => go("rate")}>Rate alerts</button>
          <button onClick={() => go("method")}>How it works and accuracy</button>
        </span>
      </footer>
    </Ctx.Provider>
  );
}
