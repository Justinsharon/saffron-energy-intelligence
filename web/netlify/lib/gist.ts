// Shared GitHub Gist storage for the Netlify functions (kept outside netlify/functions so Netlify does not deploy it as a function).
// Env: GITHUB_TOKEN (classic, gist scope), RATINGS_GIST_ID (id or full gist URL): the same private gist the alert ratings use.
export function gistId(): string { return (process.env.RATINGS_GIST_ID || "").trim().replace(/\/+$/, "").split("/").pop() || ""; }
export const configured = () => !!process.env.GITHUB_TOKEN && !!gistId();

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
  const g = await gh("GET");
  const f = g.files?.[name];
  if (!f) return empty;
  const txt: string = f.truncated ? await (await fetch(f.raw_url)).text() : f.content;
  try { return JSON.parse(txt) as T; } catch { return empty; }
}
export async function writeJSON(name: string, obj: unknown): Promise<void> {
  await gh("PATCH", { files: { [name]: { content: JSON.stringify(obj, null, 1) } } });
}
