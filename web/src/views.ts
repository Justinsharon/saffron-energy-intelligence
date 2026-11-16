// "View as": one app, four menus. Each view orders the menu for one job and opens on its first item; every other page stays one tap
// away under "More", so nothing is lost. Ask is in every view. The choice (and the hotel picked on the role pages) is kept on this device.
import { createContext, useContext } from "react";
import type { Site } from "./data";

export type PageId = "today" | "attention" | "demand" | "equipment" | "costs" | "bills" | "billcheck" | "savings" | "overview" | "report"
  | "ask" | "feedback" | "accuracy";
export type ViewId = "duty" | "chief" | "gm" | "finance";

export const PAGE: Record<PageId, { label: string; hint: string }> = {
  today: { label: "Today", hint: "What needs attention now" },
  attention: { label: "Needs attention", hint: "Every open problem, most costly first" },
  demand: { label: "Tomorrow's plan", hint: "Bookings, chiller plan and power-limit risk for tomorrow" },
  equipment: { label: "Equipment", hint: "Repeat problems and patterns" },
  costs: { label: "Monthly costs", hint: "Why the bill went up or down" },
  bills: { label: "Bills & savings", hint: "Bill checks and where to save" },
  billcheck: { label: "Bills", hint: "Every bill checked against the tariff and our meter" },
  savings: { label: "Savings", hint: "What the hotels can save, and how it is proven" },
  overview: { label: "Overview", hint: "This month at a glance" },
  report: { label: "Monthly report", hint: "One page per month, ready to print" },
  ask: { label: "Ask", hint: "Questions in plain words" },
  feedback: { label: "Alert feedback", hint: "Rate the alerts" },
  accuracy: { label: "How accurate is it?", hint: "How well the models do" },
};
const ALL: PageId[] = ["today", "attention", "demand", "equipment", "costs", "bills", "billcheck", "savings", "overview", "report", "ask", "feedback", "accuracy"];

export const VIEWS: Record<ViewId, { label: string; menu: PageId[] }> = {
  duty: { label: "Duty engineer", menu: ["today", "attention", "equipment", "ask"] },
  chief: { label: "Chief engineer", menu: ["demand", "today", "equipment", "costs", "bills", "ask"] },
  gm: { label: "General manager", menu: ["overview", "costs", "report", "ask"] },
  finance: { label: "Finance controller", menu: ["savings", "billcheck", "report", "ask"] },
};
export const VIEW_IDS = Object.keys(VIEWS) as ViewId[];
export const home = (v: ViewId): PageId => VIEWS[v].menu[0];
export const morePages = (v: ViewId): PageId[] => ALL.filter((p) => !VIEWS[v].menu.includes(p));
export const isPage = (s: string): s is PageId => (ALL as string[]).includes(s);

function get(k: string): string | null { try { return localStorage.getItem(k); } catch { return null; } }
function put(k: string, v: string) { try { localStorage.setItem(k, v); } catch { /* private window: kept for this visit only */ } }
export const viewStore = {
  get: (): ViewId => { const v = get("view_as"); return v && v in VIEWS ? (v as ViewId) : "duty"; },
  set: (v: ViewId) => put("view_as", v),
};
export const hotelStore = {
  get: (): Site => { const s = get("hotel"); return s === "JAI" || s === "GOA" ? s : "GGN"; },
  set: (s: Site) => put("hotel", s),
};

/** The hotel picked on the role pages (Today for the duty engineer, Needs attention, Overview, Savings), shared between them. */
export const HotelCtx = createContext<{ hotel: Site; setHotel: (s: Site) => void }>({ hotel: "GGN", setHotel: () => {} });
export const useHotel = () => useContext(HotelCtx);
