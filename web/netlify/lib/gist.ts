// Shared GitHub Gist storage for the Netlify functions (kept outside netlify/functions so Netlify does not deploy it as a function).
// Env: GITHUB_TOKEN (classic, gist scope), RATINGS_GIST_ID (id or full gist URL): the same private gist the alert ratings use.
// SAFFRON_MEMORY_STORE=1 (local dev and the Plant Room end-to-end test only; never set on Netlify): files live in this process's memory.
export function gistId(): string { return (process.env.RATINGS_GIST_ID || "").trim().replace(/\/+$/, "").split("/").pop() || ""; }
const MEM: Map<string, string> | null = process.env.SAFFRON_MEMORY_STORE === "1" ? new Map() : null;
export const configured = () => !!MEM || (!!process.env.GITHUB_TOKEN && !!gistId());

async function gh(method: string, body?: unknown) {
  const r = await fetch(`https://api.github.com/gists/${gistId()}`, {
    method, body: body ? JSON.stringify(body) : undefined,
    headers: { Authorization: `Bearer ${process.env.GITHUB_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "saffron-energy" },
  });
  if (!r.ok) throw new Error(`GitHub ${r.status}${r.status === 404 ? " (check the gist id and that the token has the gist scope)" : ""}`);
  return r.json();
}

/** A JSON file in the gist; large files are truncated in the gist API response, so fetch raw_url when needed. */
export async function readJSON<T>(name: string, empty: T): Promise<T> {
  if (MEM) { const t = MEM.get(name); return t ? (JSON.parse(t) as T) : empty; }
  const g = await gh("GET");
  const f = g.files?.[name];
  if (!f) return empty;
  const txt: string = f.truncated ? await (await fetch(f.raw_url)).text() : f.content;
  try { return JSON.parse(txt) as T; } catch { return empty; }
}
/** Several JSON files from one gist read (the Plant Room polls every 5 s: one GitHub call per poll, not one per file). */
export async function readFiles<T extends Record<string, unknown>>(empties: T): Promise<T> {
  const out = { ...empties };
  if (MEM) { for (const k of Object.keys(empties)) { const t = MEM.get(k); if (t) (out as Record<string, unknown>)[k] = JSON.parse(t); } return out; }
  const g = await gh("GET");
  for (const k of Object.keys(empties)) {
    const f = g.files?.[k];
    if (!f) continue;
    const txt: string = f.truncated ? await (await fetch(f.raw_url)).text() : f.content;
    try { (out as Record<string, unknown>)[k] = JSON.parse(txt); } catch { /* keep the empty value */ }
  }
  return out;
}
export async function writeJSON(name: string, obj: unknown): Promise<void> {
  if (MEM) { MEM.set(name, JSON.stringify(obj)); return; }
  await gh("PATCH", { files: { [name]: { content: JSON.stringify(obj, null, 1) } } });
}
