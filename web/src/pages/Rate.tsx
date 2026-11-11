import { useEffect, useMemo, useState } from "react";
import { Ticket } from "../components/parts";
import { useData, type Alert } from "../data";

interface Row { time: string; rater: string; role: string; alert_id: string; usefulness: number; would_act: string; cause_right: string; comment: string; round: number }
const ROUND = 2;

export default function Rate() {
  const alerts = useData<Alert[]>("alerts.json");
  const ids = useData<string[]>("rating_set.json");
  const [rows, setRows] = useState<Row[] | null>(null);
  const [err, setErr] = useState("");
  const [name, setName] = useState(() => { try { return localStorage.getItem("rater") ?? ""; } catch { return ""; } });
  const [role, setRole] = useState("Duty / shift engineer");
  const [i, setI] = useState(0);
  const [u, setU] = useState(4);
  const [act, setAct] = useState("Yes");
  const [cause, setCause] = useState("Yes");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState<"rate" | "results">("rate");

  const reload = () => fetch("/.netlify/functions/ratings").then((r) => r.json()).then((j) => setRows(j.rows ?? [])).catch(() => setErr("Feedback can't be saved right now. Try again in a few minutes."));
  useEffect(() => { reload(); }, []);
  const set = useMemo(() => (alerts && ids ? ids.map((id) => alerts.find((a) => a.id === id)!).filter(Boolean).sort((a, b) => a.start.localeCompare(b.start)) : []), [alerts, ids]);
  const mine = new Set((rows ?? []).filter((r) => r.rater.toLowerCase() === name.trim().toLowerCase() && Number(r.round || 1) === ROUND).map((r) => r.alert_id));
  useEffect(() => { const k = set.findIndex((a) => !mine.has(a.id)); if (k >= 0) setI(k); }, [rows, set.length, name]);
  const a = set[i];

  async function save() {
    if (!a || !name.trim()) return;
    setSaving(true); setErr("");
    try { localStorage.setItem("rater", name.trim()); } catch { /* ignore */ }
    const row: Row = { time: new Date().toISOString().slice(0, 16).replace("T", " "), rater: name.trim(), role, alert_id: a.id, usefulness: u, would_act: act, cause_right: cause, comment: note, round: ROUND };
    try {
      const r = await fetch("/.netlify/functions/ratings", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(row) });
      if (!r.ok) throw new Error(await r.text());
      setNote(""); setU(4); setAct("Yes"); setCause("Yes"); await reload();
    } catch (e) { setErr(`Your feedback wasn't saved (${(e as Error).message.slice(0, 120)}). Try again.`); }
    setSaving(false);
  }

  const latest = useMemo(() => {
    const r = (rows ?? []).filter((x) => Number(x.round || 1) === ROUND);
    const m = new Map<string, Row>(); for (const x of r) m.set(`${x.rater}|${x.alert_id}`, x);
    return [...m.values()];
  }, [rows]);
  const byRater = useMemo(() => {
    const g: Record<string, Row[]> = {}; for (const x of latest) (g[x.rater] ??= []).push(x);
    return Object.entries(g).map(([k, xs]) => ({ k, n: xs.length, mean: xs.reduce((s, x) => s + Number(x.usefulness), 0) / xs.length, act: xs.filter((x) => x.would_act === "Yes").length / xs.length }));
  }, [latest]);
  const mean = latest.length ? latest.reduce((s, x) => s + Number(x.usefulness), 0) / latest.length : null;
  const r1 = (rows ?? []).filter((x) => Number(x.round || 1) === 1 && !x.rater.startsWith("TEST"));
  const mean1 = r1.length ? r1.reduce((s, x) => s + Number(x.usefulness), 0) / r1.length : null;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Alert feedback</h1>
          <p className="lead">Help us make alerts worth reading. Below are 20 recent alerts, one of each kind from every hotel. For each one, say how useful it would have been on your shift. We aim for an average of at least 4 out of 5.</p>
        </div>
        <div className="seg"><button aria-pressed={tab === "rate"} onClick={() => setTab("rate")}>Give feedback</button><button aria-pressed={tab === "results"} onClick={() => setTab("results")}>Results</button></div>
      </div>
      {err && <div className="guard note-warn" style={{ marginBottom: 12 }}><span>⚠</span><span>{err}</span></div>}

      {tab === "rate" && (
        <>
          <div className="panel" style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "end", marginBottom: 14 }}>
            <label style={{ flex: "1 1 220px" }}><div className="small muted">Your name</div>
              <input value={name} onChange={(e) => setName(e.target.value)} style={{ width: "100%", padding: "9px 10px", border: "1px solid var(--rule)", borderRadius: 4 }} /></label>
            <label style={{ flex: "1 1 220px" }}><div className="small muted">Role</div>
              <select value={role} onChange={(e) => setRole(e.target.value)} style={{ width: "100%", padding: "9px 10px", border: "1px solid var(--rule)", borderRadius: 4 }}>
                {["Duty / shift engineer", "Chief engineer", "Facilities / energy manager", "General manager", "Finance", "Other"].map((r) => <option key={r}>{r}</option>)}
              </select></label>
            <div className="small" style={{ flex: "1 1 160px" }}><strong>{[...mine].filter((x) => ids?.includes(x)).length}</strong> of {set.length} rated</div>
          </div>
          {!name.trim() ? <p className="muted">Enter your name to start.</p> : !a ? <p className="muted">Loading…</p> : (
            <>
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
                <button className="btn ghost" disabled={i === 0} onClick={() => setI(i - 1)}>Previous</button>
                <span className="small">Alert {i + 1} of {set.length}{mine.has(a.id) ? " · you've already rated this one; saving again replaces it" : ""}</span>
                <button className="btn ghost" disabled={i === set.length - 1} onClick={() => setI(i + 1)}>Next</button>
              </div>
              <Ticket a={a} defaultOpen />
              <div className="panel" style={{ marginTop: 12 }}>
                <fieldset style={{ border: 0, padding: 0, margin: "0 0 12px" }}>
                  <legend style={{ fontWeight: 600, marginBottom: 6 }}>How useful would this alert be on your shift?</legend>
                  <div className="seg">{[1, 2, 3, 4, 5].map((k) => <button key={k} type="button" aria-pressed={u === k} onClick={() => setU(k)}>{k}</button>)}</div>
                  <span className="small muted" style={{ marginLeft: 10 }}>1 means noise; 5 means I'd act on it straight away</span>
                </fieldset>
                <div className="grid g2">
                  <fieldset style={{ border: 0, padding: 0, margin: 0 }}><legend style={{ fontWeight: 600, marginBottom: 6 }}>Would you act on it?</legend>
                    <div className="seg">{["Yes", "No", "Not sure"].map((k) => <button key={k} type="button" aria-pressed={act === k} onClick={() => setAct(k)}>{k}</button>)}</div></fieldset>
                  <fieldset style={{ border: 0, padding: 0, margin: 0 }}><legend style={{ fontWeight: 600, marginBottom: 6 }}>Does the explanation sound right?</legend>
                    <div className="seg">{["Yes", "No", "Not sure"].map((k) => <button key={k} type="button" aria-pressed={cause === k} onClick={() => setCause(k)}>{k}</button>)}</div></fieldset>
                </div>
                <textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="What would make it more useful? (optional)" rows={2}
                          style={{ width: "100%", marginTop: 12, padding: 10, border: "1px solid var(--rule)", borderRadius: 4 }} />
                <button className="btn big" style={{ marginTop: 10 }} onClick={save} disabled={saving}>{saving ? "Saving…" : "Save and go to the next one"}</button>
              </div>
            </>
          )}
        </>
      )}

      {tab === "results" && (
        <div className="grid g2">
          <div className="panel">
            <div className="grid g2">
              <div className="stat"><span>Average usefulness</span><b>{mean == null ? "—" : `${mean.toFixed(1)} out of 5`}</b><em>from {latest.length} ratings · goal 4 or more</em></div>
              <div className="stat"><span>Would act on it</span><b>{latest.length ? `${Math.round(latest.filter((x) => x.would_act === "Yes").length / latest.length * 100)}%` : "—"}</b><em>of alerts rated</em></div>
            </div>
          </div>
          <div className="panel">
            <table className="t"><thead><tr><th>Who</th><th className="r">Rated</th><th className="r">Average</th><th className="r">Would act</th></tr></thead>
              <tbody>{byRater.map((r) => <tr key={r.k}><td>{r.k}</td><td className="r">{r.n}</td><td className="r">{r.mean.toFixed(2)}</td><td className="r">{Math.round(r.act * 100)}%</td></tr>)}</tbody></table>
            {byRater.length === 0 && <p className="muted small">No feedback yet. Be the first.</p>}
          </div>
        </div>
      )}
    </>
  );
}
