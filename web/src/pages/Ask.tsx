import { useRef, useState } from "react";

interface Msg { role: "user" | "assistant"; content: string; via?: string }
const PROMPTS = [
  "Why was Gurugram's May 2026 bill higher than April's?",
  "Tomorrow is 40 °C with a 318-guest conference. Any contract demand risk?",
  "Is the Goa July 2026 bill right?",
  "What are the biggest alerts at Jaipur?",
  "Auto switch off kitchen exhaust overnight",
  "How much can we save, and where?",
];

export default function Ask() {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  async function send(text: string) {
    if (!text.trim() || busy) return;
    const next = [...msgs, { role: "user" as const, content: text }];
    setMsgs(next); setQ(""); setBusy(true);
    try {
      const r = await fetch("/.netlify/functions/assistant", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ question: text, history: next.slice(0, -1).slice(-6).map(({ role, content }) => ({ role, content })) }),
      });
      const j = await r.json();
      setMsgs([...next, { role: "assistant", content: j.text ?? j.error ?? "No answer.", via: j.mode }]);
    } catch {
      setMsgs([...next, { role: "assistant", content: "The assistant could not be reached. The other tabs still work; try again in a minute.", via: "offline" }]);
    } finally {
      setBusy(false);
      setTimeout(() => end.current?.scrollIntoView({ behavior: "smooth" }), 50);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Ask about energy</h1>
          <p className="lead">Plain questions about bills, alerts, tomorrow's demand or savings. Every number in an answer comes from the models and is checked before you see it. It recommends; it never switches anything.</p>
        </div>
      </div>
      <div className="prompts" style={{ marginBottom: 16 }}>
        {PROMPTS.map((p) => <button key={p} onClick={() => send(p)} disabled={busy}>{p}</button>)}
      </div>
      <div className="chat" aria-live="polite">
        {msgs.map((m, i) => (
          <div key={i} className={`msg ${m.role === "user" ? "user" : "bot"}`}>
            {m.content}
            {m.via && <span className="via">{m.via}</span>}
          </div>
        ))}
        {busy && <div className="msg bot muted">Working it out from the data…</div>}
        <div ref={end} />
      </div>
      <form className="ask" onSubmit={(e) => { e.preventDefault(); send(q); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask a question" aria-label="Question" />
        <button className="btn" disabled={busy || !q.trim()}>Ask</button>
      </form>
    </>
  );
}
