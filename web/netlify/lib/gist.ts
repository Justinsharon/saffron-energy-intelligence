import { getStore, type Store } from "@netlify/blobs";
// Shared GitHub Gist storage for the Netlify functions (kept outside netlify/functions so Netlify does not deploy it as a function).
// Env: GITHUB_TOKEN (classic, gist scope), RATINGS_GIST_ID (id or full gist URL): the same private gist the alert ratings use.
// SAFFRON_MEMORY_STORE=1 (local dev and the Plant Room end-to-end test only; never set on Netlify): files live in this process's memory.
export function gistId(): string { return (process.env.RATINGS_GIST_ID || "").trim().replace(/\/+$/, "").split("/").pop() || ""; }
const MEM: Map<string, string> | null = process.env.SAFFRON_MEMORY_STORE === "1" ? new Map() : null;
const gistReady = () => !!process.env.GITHUB_TOKEN && !!gistId();

// The plan log and the meter simulator's state live in Netlify Blobs (store "saffron"; no GitHub rate limit). The gist stays a READ-ONLY
// fallback: a file not yet in Blobs is read from the gist once, and the first write puts it in Blobs. Other files (ratings) stay in the gist.
const BLOB_FILES = new Set(["plans.json", "plant_state.json"]);
let blobStore: Store | null | undefined;
function blobs(): Store | null {
  if (blobStore !== undefined) return blobStore;
  try { blobStore = getStore({ name: "saffron", consistency: "strong" }); } catch { blobStore = null; }   // not on Netlify (local dev)
  return blobStore;
}
const etags = new Map<string, string | null>();      // last read version per file, so a write only lands on what was read (else retried)
export const configured = () => !!MEM || !!blobs() || gistReady();

async function gh(method: string, body?: unknown) {
  const r = await fetch(`https://api.github.com/gists/${gistId()}`, {
    method, body: body ? JSON.stringify(body) : undefined,
    headers: { Authorization: `Bearer ${process.env.GITHUB_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "saffron-energy" },
  });
  if (!r.ok) throw new Error(`GitHub ${r.status}${r.status === 404 ? " (check the gist id and that the token has the gist scope)" : ""}`);
  return r.json();
}

/** A JSON file in the gist; large files are truncated in the gist API response, so fetch raw_url when needed. */
async function blobRead<T>(st: Store, name: string, empty: T): Promise<T> {
  const r = await st.getWithMetadata(name, { type: "json" });
  if (r) { etags.set(name, r.etag ?? null); return r.data as T; }
  etags.set(name, null);                                                   // not in Blobs yet: first write must create it
  return gistReady() ? gistRead(name, empty) : empty;                      // read-only fallback for plans saved before the move
}
export async function readJSON<T>(name: string, empty: T): Promise<T> {
  if (MEM) { const t = MEM.get(name); return t ? (JSON.parse(t) as T) : empty; }
  const st = BLOB_FILES.has(name) ? blobs() : null;
  if (st) return blobRead(st, name, empty);
  return gistRead(name, empty);
}
async function gistRead<T>(name: string, empty: T): Promise<T> {
  const g = await gh("GET");
  const f = g.files?.[name];
  if (!f) return empty;
  const txt: string = f.truncated ? await (await fetch(f.raw_url)).text() : f.content;
  try { return JSON.parse(txt) as T; } catch { return empty; }
}
/** Several JSON files from one gist read (the Plant Room polls every 5 s: one GitHub call per poll, not one per file). */
export async function readFiles<T extends Record<string, unknown>>(empties: T): Promise<T> {
  const out = { ...empties };
  const st = blobs();
  if (!MEM && st && Object.keys(empties).every((k) => BLOB_FILES.has(k))) {
    for (const k of Object.keys(empties)) (out as Record<string, unknown>)[k] = await blobRead(st, k, empties[k]);
    return out;
  }
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
  const st = BLOB_FILES.has(name) ? blobs() : null;
  if (st) {
    const tag = etags.get(name);
    const r = await st.setJSON(name, obj, tag ? { onlyIfMatch: tag } : tag === null ? { onlyIfNew: true } : {});
    if (r && r.modified === false) throw new Error("Storage 409: changed since it was read");   // withRetry re-reads and re-applies
    etags.delete(name);
    return;
  }
  await gh("PATCH", { files: { [name]: { content: JSON.stringify(obj, null, 1) } } });
}

/** Read-modify-write with retries: GitHub answers 409 when two edits of the gist cross (e.g. the meter simulator posting readings while a
 *  plan step is approved). The whole step (read, apply the event, write) is re-run on the fresh gist, up to 4 times. */
export async function withRetry<T>(step: () => Promise<T>, tries = 4): Promise<T> {
  for (let i = 1; ; i++) {
    try { return await step(); }
    catch (e) {
      if (i >= tries || !/(GitHub|Storage) (409|5\d\d)/.test(String((e as Error).message ?? e))) throw e;
      await new Promise((r) => setTimeout(r, 300 * i + Math.random() * 400));
    }
  }
}
