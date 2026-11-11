// Indian number formats: ₹ in lakh / crore, dates in IST as recorded (start of interval).
export function inr(x: number | null | undefined, opts: { exact?: boolean } = {}): string {
  if (x == null || Number.isNaN(x)) return "—";
  const s = x < 0 ? "−" : "";
  const a = Math.abs(x);
  if (!opts.exact && a >= 1e7) return `${s}₹${(a / 1e7).toFixed(2)} cr`;
  if (!opts.exact && a >= 1e5) return `${s}₹${(a / 1e5).toFixed(2)} L`;
  return `${s}₹${Math.round(a).toLocaleString("en-IN")}`;
}
export function signedInr(x: number): string {
  return (x >= 0 ? "+" : "") + inr(x);
}
export function n(x: number | null | undefined, d = 0): string {
  if (x == null || Number.isNaN(x)) return "—";
  return x.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
}
export function pct(x: number | null | undefined, d = 0): string {
  return x == null ? "—" : `${(x * 100).toFixed(d)}%`;
}
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
export function parse(t: string): Date {
  // stored as local IST wall time without zone; treat as UTC internally so arithmetic never shifts
  const [d, h = "00:00"] = t.split("T");
  const [y, m, dd] = d.split("-").map(Number);
  const [hh, mm = 0] = h.split(":").map(Number);
  return new Date(Date.UTC(y, m - 1, dd, hh, mm));
}
export function fmtDT(t: string | Date, withDow = true): string {
  const d = typeof t === "string" ? parse(t) : t;
  const hh = String(d.getUTCHours()).padStart(2, "0"), mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${withDow ? DOW[d.getUTCDay()] + " " : ""}${d.getUTCDate()} ${MON[d.getUTCMonth()]}, ${hh}:${mm}`;
}
export function fmtD(t: string | Date): string {
  const d = typeof t === "string" ? parse(t) : t;
  return `${d.getUTCDate()} ${MON[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}
export function fmtMonth(m: string): string {
  const [y, mo] = m.split("-").map(Number);
  return `${MON[mo - 1]} ${y}`;
}
export function hours(h: number): string {
  if (h < 48) return `${Math.round(h)} h`;
  return `${(h / 24).toFixed(1)} days`;
}
export function iso(d: Date): string {
  return d.toISOString().slice(0, 16);
}
