import { useRef, useState } from "react";

/** Claude sometimes answers with light markdown: render **bold** and "- " bullets, nothing else (no HTML from the model). */
function Rich({ text }: { text: string }) {
  const inline = (t: string) => t.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : <span key={i}>{part}</span>);
  const blocks: JSX.Element[] = [];
  let list: string[] = [];
  const flush = () => { if (list.length) blocks.push(<ul key={blocks.length} style={{ margin: "6px 0", paddingLeft: 20 }}>{list.map((l, i) => <li key={i}>{inline(l)}</li>)}</ul>); list = []; };
  for (const line of text.split("\n")) {
    const m = line.match(/^\s*(?:[-•*]|\d+[.)])\s+(.*)$/);
    if (m) { list.push(m[1]); continue; }
    flush();
    if (line.trim()) blocks.push(<p key={blocks.length} style={{ margin: "6px 0" }}>{inline(line.replace(/^#+\s*/, ""))}</p>);
  }
  flush();
  return <>{blocks}</>;
}

interface Msg { role: "user" | "assistant"; content: string; via?: string }
const PROMPTS = [
  "Why was Gurugram's May 2026 bill higher than April's?",
  "Tomorrow is 40 °C with a 300-guest conference. Will we go over the power limit?",
  "Is the Goa July 2026 bill right?",
  "What is wasting the most money at Jaipur?",
  "Switch off the kitchen extract fans automatically at night",
  "Where can we save the most?",
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
      setMsgs([...next, { role: "assistant", content: "Ask isn't available right now. The other pages still work; please try again in a minute.", via: "offline" }]);
    } finally {
      setBusy(false);
      setTimeout(() => end.current?.scrollIntoView({ behavior: "smooth" }), 50);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Ask</h1>
          <p className="lead">Ask about bills, waste, tomorrow's power demand or savings, in your own words. Every figure in an answer comes from the hotel's own data and is checked before you see it. Ask can suggest changes; it never switches anything.</p>
        </div>
      </div>
      <div className="prompts" style={{ marginBottom: 16 }}>
        {PROMPTS.map((p) => <button key={p} onClick={() => send(p)} disabled={busy}>{p}</button>)}
      </div>
      <div className="chat" aria-live="polite">
        {msgs.map((m, i) => (
          <div key={i} className={`msg ${m.role === "user" ? "user" : "bot"}`}>
            {m.role === "user" ? m.content : <Rich text={m.content} />}
            {m.via && <span className="via">{m.via}</span>}
          </div>
        ))}
        {busy && <div className="msg bot muted">Looking at the hotel data…</div>}
        <div ref={end} />
      </div>
      <form className="ask" onSubmit={(e) => { e.preventDefault(); send(q); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="For example: why did Goa's July bill go up?" aria-label="Question" />
        <button className="btn" disabled={busy || !q.trim()}>Ask</button>
      </form>
    </>
  );
}
