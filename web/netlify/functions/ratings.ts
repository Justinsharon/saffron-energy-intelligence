// Alert ratings (engineer-trust test) stored in a private GitHub Gist as CSV - same file the Streamlit app used.
// Env: GITHUB_TOKEN (classic, gist scope), RATINGS_GIST_ID (id or full gist URL).
const COLS = ["time", "rater", "role", "alert_id", "usefulness", "would_act", "cause_right", "comment", "round"];
const FILE = "ratings.csv";

function gistId(): string { return (process.env.RATINGS_GIST_ID || "").trim().replace(/\/+$/, "").split("/").pop() || ""; }
async function gh(method: string, body?: unknown) {
  const r = await fetch(`https://api.github.com/gists/${gistId()}`, {
    method, body: body ? JSON.stringify(body) : undefined,
    headers: { Authorization: `Bearer ${process.env.GITHUB_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "saffron-energy" },
  });
  if (!r.ok) throw new Error(`GitHub ${r.status}${r.status === 404 ? " (check the gist id and that the token has the gist scope)" : ""}`);
  return r.json();
}

function parseCSV(t: string): string[][] {
  const rows: string[][] = []; let row: string[] = [], f = "", q = false;
  for (let i = 0; i < t.length; i++) {
    const c = t[i];
    if (q) { if (c === '"' && t[i + 1] === '"') { f += '"'; i++; } else if (c === '"') q = false; else f += c; }
    else if (c === '"') q = true; else if (c === ",") { row.push(f); f = ""; }
    else if (c === "\n" || c === "\r") { if (c === "\r" && t[i + 1] === "\n") i++; row.push(f); rows.push(row); row = []; f = ""; }
    else f += c;
  }
  if (f || row.length) { row.push(f); rows.push(row); }
  return rows.filter((r) => r.some((x) => x !== ""));
}
const esc = (v: unknown) => { const s = v == null ? "" : String(v); return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };

async function read(): Promise<Record<string, string>[]> {
  const g = await gh("GET");
  const txt: string = g.files?.[FILE]?.content ?? "";
  const [head, ...body] = parseCSV(txt);
  if (!head) return [];
  return body.map((r) => Object.fromEntries(head.map((h, i) => [h, r[i] ?? ""])));
}

export default async (req: Request) => {
  if (!process.env.GITHUB_TOKEN || !gistId()) return Response.json({ rows: [], storage: "not configured" }, { status: req.method === "GET" ? 200 : 503 });
  try {
    if (req.method === "GET") return Response.json({ rows: await read(), storage: "gist" });
    if (req.method !== "POST") return new Response("Method not allowed", { status: 405 });
    const b = await req.json();
    const u = Number(b.usefulness);
    if (!b.rater || !b.alert_id || !(u >= 1 && u <= 5)) return new Response("Name, alert and a 1–5 score are required.", { status: 400 });
    const rows = await read();
    rows.push({ time: String(b.time ?? ""), rater: String(b.rater).slice(0, 80), role: String(b.role ?? "").slice(0, 60), alert_id: String(b.alert_id).slice(0, 20),
      usefulness: String(u), would_act: String(b.would_act ?? ""), cause_right: String(b.cause_right ?? ""), comment: String(b.comment ?? "").slice(0, 1000), round: String(b.round ?? 2) });
    const csv = [COLS.join(","), ...rows.map((r) => COLS.map((c) => esc(r[c])).join(","))].join("\n") + "\n";
    await gh("PATCH", { files: { [FILE]: { content: csv } } });
    return Response.json({ ok: true, n: rows.length });
  } catch (e) {
    return new Response(String((e as Error).message ?? e), { status: 502 });
  }
};
