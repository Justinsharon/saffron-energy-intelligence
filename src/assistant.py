"""Conversational assistant ("Why was last Tuesday's bill so high?") with hard guardrails.

Design (CLAUDE.md: LLM text may only state facts present in the data; all numbers come from the models):
1. A deterministic guard runs *before* any model: requests to automatically control kitchen exhaust, guest-room thermostats,
   fire/life-safety, lifts, or to set CHW below 6.5 °C are refused with the safe alternative (T10). The LLM cannot override this.
2. Claude answers with tools only - each tool returns numbers computed by our modules (bills, attribution, alerts, forecast, savings).
3. Every number in Claude's final text is checked against the tool outputs; if any number is not found, the answer is replaced
   by the deterministic summary built from the same tool output.
4. Without an API key the same tools are routed by keywords, so the product still works.
"""
import json
import os
import re

import pandas as pd

from features import CLEAN, SITES

APP = CLEAN.parent / "app"
MODEL = os.environ.get("PS12_MODEL", "claude-sonnet-5-5")
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# ---- 1. deterministic guard ---------------------------------------------------------------------------------
NEVER = {
    "kitchen exhaust": ("Kitchen exhaust must run whenever cooking equipment is on (fire and air-quality safety), so it is never switched off "
                        "automatically. Recommended instead: an interlock that ties exhaust and make-up air to kitchen operating hours, with a "
                        "30-minute run-on after the last order, approved and commissioned by the chief engineer. I can show the nights the exhaust "
                        "ran after the kitchen closed."),
    "thermostat": ("Guest-room thermostats are not controlled by this product (guest comfort 22–25 °C, guest override 20–26 °C). The only allowed "
                   "change is a setback for unsold rooms through the PMS, approved by a person."),
    "fire": "Fire pumps, pressurisation fans and life-safety systems are never controlled or recommended for switching off.",
    "life safety": "Life-safety systems are never controlled or recommended for switching off.",
    "lift": "Lifts are never controlled by this product.",
    "elevator": "Lifts are never controlled by this product.",
}
CONTROL_WORDS = r"\b(auto|automatic|automatically|switch(ed)? off|turn(ed)? off|shut( down| off)?|disable|control|stop|schedule off)\b"


def guard(q: str) -> str | None:
    ql = q.lower()
    for k, msg in NEVER.items():
        if k in ql and re.search(CONTROL_WORDS, ql):
            return "I can't do that. " + msg
    m = re.search(r"(chw|chilled[- ]water|setpoint)[^0-9]{0,40}(\d+(?:\.\d+)?)\s*°?\s*c?", ql)
    if m and float(m.group(2)) < 6.5:
        return ("I can't recommend that. The chilled-water setpoint must never go below 6.5 °C (engineering guide); the standard is 7.0 °C, "
                "and a reset to 8 °C is allowed when it is below 24 °C outside and the load is light.")
    return None


# ---- 2. tools (all numbers come from our modules) -----------------------------------------------------------
def _site(x: str | None) -> str:
    if not x:
        return "GGN"
    x = x.strip().lower()
    for code, name in SITES.items():
        if x in (code.lower(), name.lower()) or name.lower().startswith(x):
            return code
    return "GGN"


def tool_explain_bill_change(site: str, month_a: str, month_b: str) -> dict:
    from attribution import explain_change
    r = explain_change(_site(site), month_a, month_b)
    t = r["table"].groupby("group").inr.sum().round(0).sort_values(ascending=False)
    return dict(hotel=SITES[r["site"]], month_a=month_a, month_b=month_b, bill_a_inr=round(r["bill_a"]), bill_b_inr=round(r["bill_b"]),
                change_inr=round(r["delta"]), change_by_driver_inr=t.to_dict(),
                detail_inr={k: round(v) for k, v in zip(r["table"].driver, r["table"].inr)},
                context={k: round(v, 3) if isinstance(v, float) else v for k, v in r["context"].items()},
                waste_kwh_in_month_b_by_type=r["alert_rules_b"])


def tool_bill_reconciliation(site: str, month: str | None = None) -> dict:
    r = pd.read_parquet(APP / "bills_recon.parquet")
    r = r[r.site == _site(site)]
    if month:
        r = r[r.month == month]
    cols = ["month", "status", "billed_total", "corrected_total", "billed_minus_corrected", "md_kva", "pf", "pf_source", "note"]
    return dict(hotel=SITES[_site(site)], rows=r[cols].round(3).to_dict("records"))


def tool_list_alerts(site: str | None = None, date_from: str | None = None, date_to: str | None = None, top: int = 8) -> dict:
    c = pd.read_parquet(APP / "cards.parquet")
    if site:
        c = c[c.site == _site(site)]
    if date_from:
        c = c[c.end >= pd.Timestamp(date_from)]
    if date_to:
        c = c[c.start <= pd.Timestamp(date_to) + pd.Timedelta(days=1)]
    c = c.sort_values("cost_inr", ascending=False).head(top)
    return dict(n=len(c), alerts=[dict(id=r.alert_id, hotel=r.hotel, title=r.title, severity=r.severity, start=f"{r.start:%Y-%m-%d %H:%M}",
                                       hours=round(r.duration_h, 1), inr=round(r.cost_inr), inr_per_day=round(r.inr_per_day), evidence=r.evidence,
                                       action=r.action) for r in c.itertuples()])


def _risk_out(a: dict) -> dict:
    plan = None if a["plan"] is None else [dict(load=r.load, action=r.action, relief_kva=round(r.relief_kva)) for r in a["plan"].itertuples()]
    return dict(forecast_peak_kva=round(a["peak"]), peak_hour=a["hour"], upper90_kva=round(a["upper"]),
                chance_above_1000_kva_pct=None if a["p_exceed"] != a["p_exceed"] else round(a["p_exceed"] * 100),
                stacking_scenario_kva=round(a["stack_peak"]), stacking_basis=a["stack_basis"], risk=a["level"], reason=a["why"],
                contract_demand_kva=1000, shift_plan=plan)


def tool_forecast_day(date: str) -> dict:
    import forecast_app
    try:
        w, a = forecast_app.day_view(date)
    except Exception:
        return dict(error="No forecast for that date (data covers 8 Oct 2025 – 30 Sep 2026, Gurugram only).")
    if w.empty:
        return dict(error="No forecast for that date (data covers 8 Oct 2025 – 30 Sep 2026, Gurugram only).")
    return dict(hotel="Gurugram", date=date, actual_peak_kva=round(float(w.actual_kva.max())), **_risk_out(a))


def tool_forecast_scenario(max_temp_c: float, conference_guests: int = 0) -> dict:
    """What-if for tomorrow at Gurugram: a weekday with this max temperature and a 09:00-18:00 conference."""
    import forecast_app
    w, a = forecast_app.scenario("2026-05-20", float(max_temp_c), int(conference_guests))
    return dict(hotel="Gurugram", scenario=f"weekday, max {float(max_temp_c):.0f} °C, conference {int(conference_guests)} guests 09:00-18:00", **_risk_out(a))


def tool_savings_plan() -> dict:
    from savings import plan
    p = plan()
    tot = pd.read_parquet(CLEAN / "monthly_bills.parquet").total_energy_cost_inr.sum()
    core = p[p.category != "Capital (note)"]
    return dict(total_inr=round(core.inr.sum()), pct_of_group_bill=round(core.inr.sum() / tot * 100, 1),
                with_capital_note_inr=round(p.inr.sum()), with_capital_note_pct=round(p.inr.sum() / tot * 100, 1), target_pct="8-12",
                by_category_inr=p.groupby("category").inr.sum().round(0).to_dict(),
                measures=[dict(hotel=r.hotel, measure=r.measure, category=r.category, inr=round(r.inr), safety=r.safety) for r in p.itertuples()])


TOOLS = {
    "explain_bill_change": (tool_explain_bill_change, "Split the change between two monthly bills of one hotel into weather, occupancy, events, calendar, anomalies (incl. PF), demand, diesel, tariff mix. Months as YYYY-MM.",
                            {"site": "string: GGN/JAI/GOA or hotel name", "month_a": "string YYYY-MM (earlier)", "month_b": "string YYYY-MM (later)"}),
    "bill_reconciliation": (tool_bill_reconciliation, "Issued bill vs tariff rebuild vs meter, with status (Reconciled / Meter fault / Provisional).",
                            {"site": "string", "month": "string YYYY-MM, optional"}),
    "list_alerts": (tool_list_alerts, "Detected waste alerts with evidence, ₹ and action, largest ₹ first.",
                    {"site": "string, optional", "date_from": "YYYY-MM-DD optional", "date_to": "YYYY-MM-DD optional", "top": "integer, optional"}),
    "forecast_day": (tool_forecast_day, "Gurugram day-ahead peak-kVA forecast and contract-demand risk for a date.", {"date": "YYYY-MM-DD"}),
    "forecast_scenario": (tool_forecast_scenario, "Gurugram what-if for tomorrow: weekday with a given max temperature and conference size; contract-demand risk and shift plan.",
                          {"max_temp_c": "string number, e.g. 40", "conference_guests": "integer, optional"}),
    "savings_plan": (tool_savings_plan, "Sized savings measures (energy / ToD / demand) with safety notes.", {}),
}


def _schemas():
    out = []
    for name, (_, desc, params) in TOOLS.items():
        props = {k: {"type": "integer" if v.startswith("integer") else "string", "description": v} for k, v in params.items()}
        req = [k for k, v in params.items() if "optional" not in v]
        out.append(dict(name=name, description=desc, input_schema=dict(type="object", properties=props, required=req)))
    return out


SYSTEM = """You are the energy assistant for Saffron Suites (fictional hotels: Gurugram, Jaipur, Goa; data Oct 2025 - Sep 2026; tariffs are illustrative).
Users are duty engineers, the chief engineer, the GM and finance. Answer using ONLY numbers returned by the tools - never compute, add up, subtract, total, round differently,
estimate or invent numbers (a sum of several drivers is NOT allowed unless a tool returned it); quote them as given (you may format with ₹ and thousands separators, or express ₹ lakh only if a tool gave that value).
If the tools do not cover the question, say what the product can show instead. Be brief: lead with the answer, then 3-6 bullet points with the ₹ drivers.
You only recommend; a person approves every action. Never suggest automatic control of kitchen exhaust, guest-room thermostats, lifts or life-safety,
and never a chilled-water setpoint below 6.5 °C. "Last month" etc. refers to the data period; the latest month is 2026-09."""


# ---- 3. number check ----------------------------------------------------------------------------------------
def _numbers(text: str) -> list[float]:
    out = []
    for m in re.finditer(r"(?<![A-Za-z0-9])(\d[\d,]*\.?\d*)\s*(lakh|l\b|cr|crore)?", text, flags=re.I):
        s = m.group(1).replace(",", "").rstrip(".")
        if not s:
            continue
        v = float(s)
        unit = (m.group(2) or "").lower()
        if unit in ("lakh", "l"):
            v *= 1e5
        elif unit in ("cr", "crore"):
            v *= 1e7
        out.append(v)
    return out


def check_numbers(answer: str, facts: str, question: str) -> list[float]:
    """Numbers in the answer that appear nowhere in the tool outputs or the question (tolerating rounding)."""
    known = _numbers(facts) + _numbers(question)
    bad = []
    for v in _numbers(answer):
        if v <= 31 or 2000 <= v <= 2100:          # day numbers, list counters, years
            continue
        tol = max(1.0, abs(v) * 0.006)           # e.g. ₹5.30 lakh vs 530,316
        if not any(abs(v - k) <= tol or abs(v - abs(k)) <= tol for k in known):
            bad.append(v)
    return bad


# ---- 4. answer ------------------------------------------------------------------------------------------------
def _route(q: str) -> list[tuple[str, dict]]:
    """Keyword routing used when no API key is configured (and as a safety net)."""
    ql = q.lower()
    site = next((c for c, n in SITES.items() if n.lower() in ql or re.search(rf"\b{c.lower()}\b", ql)), "GGN")
    found = [(MONTHS[m[:3]], m) for m in re.findall(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", ql)]
    ym = [f"{2025 if n >= 10 else 2026}-{n:02d}" for n, _ in found]
    if "bill" in ql and ("why" in ql or "higher" in ql or "change" in ql or "increase" in ql) and len(ym) >= 1:
        a, b = (ym[1], ym[0]) if len(ym) >= 2 else (str(pd.Period(ym[0]) - 1), ym[0])
        a, b = sorted([a, b])
        return [("explain_bill_change", dict(site=site, month_a=a, month_b=b))]
    if "bill" in ql or "reconcil" in ql or "provisional" in ql:
        return [("bill_reconciliation", dict(site=site, month=ym[0] if ym else None))]
    tm = re.search(r"(\d{2}(?:\.\d)?)\s*°?\s*c\b", ql)
    if tm and ("tomorrow" in ql or "what if" in ql):
        g = re.search(r"(\d{2,4})\s*(?:-|\s)?(?:guest|people|pax|delegate)", ql)
        return [("forecast_scenario", dict(max_temp_c=float(tm.group(1)), conference_guests=int(g.group(1)) if g else (300 if "conference" in ql else 0)))]
    if "forecast" in ql or "risk" in ql or "tomorrow" in ql or "peak" in ql or "kva" in ql:
        d = re.search(r"20\d\d-\d\d-\d\d", q)
        return [("forecast_day", dict(date=d.group(0) if d else "2026-06-18"))]
    if "saving" in ql or "save" in ql:
        return [("savings_plan", {})]
    return [("list_alerts", dict(site=site))]


def _fallback_text(calls: list) -> str:
    parts = []
    for name, args, res in calls:
        if name == "explain_bill_change":
            parts.append(f"{res['hotel']} bill {res['month_b']} vs {res['month_a']}: ₹{res['bill_b_inr']:,} vs ₹{res['bill_a_inr']:,} "
                         f"(change ₹{res['change_inr']:+,}). By driver:")
            parts += [f"- {k}: ₹{v:+,.0f}" for k, v in res["change_by_driver_inr"].items()]
        elif name == "list_alerts":
            parts.append(f"Top {res['n']} alerts by ₹:")
            parts += [f"- {a['hotel']} · {a['title']} from {a['start']} ({a['hours']} h), ₹{a['inr']:,}. {a['action']}" for a in res["alerts"]]
        elif name == "bill_reconciliation":
            parts += [f"- {r['month']}: {r['status']} — billed ₹{r['billed_total']:,.0f}. {r['note']}" for r in res["rows"]]
        elif name in ("forecast_day", "forecast_scenario"):
            if res.get("error"):
                parts.append(res["error"])
            else:
                parts.append(f"{res.get('date', res.get('scenario'))}: forecast peak {res['forecast_peak_kva']} kVA at {res['peak_hour']}:00, "
                             f"chance above 1,000 kVA {res['chance_above_1000_kva_pct']}%, if shiftable loads stack {res['stacking_scenario_kva']} kVA. "
                             f"Risk {res['risk']}. {res['reason']}")
                parts += [f"- {p['action']} (≈{p['relief_kva']} kVA)" for p in (res["shift_plan"] or [])]
        elif name == "savings_plan":
            parts.append(f"Identified savings ₹{res['total_inr']:,} ({res['pct_of_group_bill']}% of the group bill):")
            parts += [f"- {m['hotel']} · {m['measure']}: ₹{m['inr']:,} ({m['category']})" for m in res["measures"]]
    return "\n".join(parts)


def answer(q: str, history: list | None = None, api_key: str | None = None) -> dict:
    """Returns dict(text, mode, calls, unverified)."""
    g = guard(q)
    if g:
        return dict(text=g, mode="guardrail", calls=[], unverified=[])
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        calls = [(n, a, TOOLS[n][0](**a)) for n, a in _route(q)]
        return dict(text=_fallback_text(calls), mode="rules (no API key)", calls=calls, unverified=[])

    import anthropic
    client = anthropic.Anthropic(api_key=key)
    msgs = list(history or []) + [{"role": "user", "content": q}]
    calls = []
    for _ in range(5):
        resp = client.messages.create(model=MODEL, max_tokens=1200, system=SYSTEM, tools=_schemas(), messages=msgs)
        if resp.stop_reason != "tool_use":
            break
        msgs.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if b.type == "tool_use":
                args = {k: v for k, v in b.input.items() if v not in (None, "")}
                try:
                    res = TOOLS[b.name][0](**args)
                except Exception as e:                       # bad arguments: tell the model, don't crash the UI
                    res = dict(error=str(e))
                calls.append((b.name, args, res))
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(res, default=str)})
        msgs.append({"role": "user", "content": results})
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    facts = json.dumps([c[2] for c in calls], default=str)
    bad = check_numbers(text, facts, q)
    if bad:                     # one repair round: the model rewrites using only tool numbers
        msgs += [{"role": "assistant", "content": resp.content},
                 {"role": "user", "content": f"Rewrite your answer. These numbers do not appear in the tool results: {bad[:8]}. Do not add, subtract, "
                                             "total or convert numbers yourself; quote only figures exactly as the tools returned them."}]
        resp = client.messages.create(model=MODEL, max_tokens=1200, system=SYSTEM, messages=msgs, tools=_schemas())
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        bad = check_numbers(text, facts, q)
    if bad:
        fb = _fallback_text(calls) if calls else "I could not verify the figures for that answer."
        return dict(text=fb, mode=f"verified fallback (model text had unverified numbers: {bad[:5]})", calls=calls, unverified=bad)
    return dict(text=text, mode=f"Claude ({MODEL}) · numbers verified", calls=calls, unverified=[])


if __name__ == "__main__":
    for q in ["Why was Gurugram's May 2026 bill higher than April's?", "Auto switch off kitchen exhaust overnight",
              "Set the CHW setpoint to 5 C", "What is the risk on 2026-06-18?", "Is the Goa July bill right?", "How much can we save?"]:
        r = answer(q)
        print("Q:", q, "|", r["mode"]); print(r["text"][:700]); print()
