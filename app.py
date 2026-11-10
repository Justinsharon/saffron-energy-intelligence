"""Saffron Suites — Energy Intelligence (PS-12). Engineer-facing web app.

Run locally:  uv run streamlit run app.py
Reads only data/app/*.parquet and data/clean/*.parquet (built by src/build_app_data.py). Recommends, never controls.
"""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "src"))
from features import CLEAN, SITES  # noqa: E402

APP = CLEAN.parent / "app"
st.set_page_config(page_title="Saffron Suites · Energy Intelligence", page_icon="⚡", layout="wide")

SEV_COLOR = {"High": "#c0392b", "Medium": "#d68910", "Low": "#5d6d7e", "Data quality": "#7d3c98"}
INK, BASE, ACT, ACC = "#1f2a36", "#9aa5b1", "#1f6feb", "#d35400"


# ---------------------------------------------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------------------------------------------
@st.cache_data
def frame(site):
    return pd.read_parquet(APP / f"frame_{site}.parquet")


@st.cache_data
def cards():
    return pd.read_parquet(APP / "cards.parquet")


@st.cache_data
def faults():
    return pd.read_parquet(APP / "faults.parquet")


@st.cache_data
def recon():
    return pd.read_parquet(APP / "bills_recon.parquet")


@st.cache_data
def bills():
    return pd.read_parquet(CLEAN / "monthly_bills.parquet")


@st.cache_data
def events():
    return pd.read_parquet(CLEAN / "events.parquet")


@st.cache_data(show_spinner="Explaining the bill change…")
def explain(site, a, b):
    from attribution import explain_change
    return explain_change(site, a, b)


@st.cache_data(show_spinner="Sizing measures…")
def savings_plan():
    from savings import plan
    return plan()


@st.cache_data
def mv_stats(site):
    from savings import model_stats
    return model_stats(site)


@st.cache_resource(show_spinner="Loading the forecast model…")
def fc():
    import forecast_app
    forecast_app.state()
    return forecast_app


def inr(x, unit=True):
    if pd.isna(x):
        return "—"
    if abs(x) >= 1e7:
        return f"₹{x / 1e7:,.2f} cr"
    if abs(x) >= 1e5:
        return f"₹{x / 1e5:,.2f} L"
    return f"₹{x:,.0f}"


def sev_badge(s):
    return f"<span style='background:{SEV_COLOR.get(s, '#555')};color:white;padding:2px 8px;border-radius:10px;font-size:0.8em'>{s}</span>"


def style_fig(fig, h=320):
    if fig.layout.title.text:
        st.markdown(f"**{fig.layout.title.text}**")
        fig.update_layout(title=None)
    fig.update_layout(height=h, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.0, yanchor="bottom", x=0),
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", hovermode="x unified")
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.2)")
    return fig


# ---------------------------------------------------------------------------------------------------------------
# sidebar
# ---------------------------------------------------------------------------------------------------------------
if "audit" not in st.session_state:
    st.session_state.audit = []          # acknowledge / snooze / rating log (session-level; download as CSV)

st.sidebar.markdown("### ⚡ Saffron Suites\n**Energy Intelligence**")
page = st.sidebar.radio("Page", ["Overview", "Alerts", "Bills", "Forecast (Gurugram)", "Savings", "Assistant", "Method & limits"],
                        label_visibility="collapsed")
st.sidebar.divider()
st.sidebar.caption("Replay clock: the data covers 1 Oct 2025 – 30 Sep 2026. Pick the moment to view the product 'as of'.")
d0 = st.sidebar.date_input("As of date", value=pd.Timestamp("2026-05-24").date(), min_value=pd.Timestamp("2025-10-01").date(),
                           max_value=pd.Timestamp("2026-09-30").date())
h0 = st.sidebar.slider("As of hour", 0, 23, 10)
NOW = pd.Timestamp(d0) + pd.Timedelta(hours=h0)
st.sidebar.caption(f"Viewing as of **{NOW:%a %d %b %Y, %H:00}**")
st.sidebar.divider()
st.sidebar.caption("Synthetic data, fictional company, illustrative tariffs. The product recommends; a person approves every action.")


# ---------------------------------------------------------------------------------------------------------------
# pages
# ---------------------------------------------------------------------------------------------------------------
def page_overview():
    st.title("Portfolio overview")
    c = cards()
    seen = c[c.alert_time <= NOW]
    open_ = seen[seen.end > NOW]
    b = bills()
    yr = b.total_energy_cost_inr.sum()
    k = st.columns(4)
    k[0].metric("Open alerts now", len(open_), help="Alerts raised before the replay time whose episode is still running")
    k[1].metric("₹/day at stake (open)", inr(open_.inr_per_day.sum()))
    k[2].metric("Waste flagged to date", inr(seen.cost_inr.sum()), help="Sum of ₹ over alerts raised so far in the data year")
    k[3].metric("Group energy cost (year)", inr(yr))

    st.subheader("Open now")
    if open_.empty:
        st.success("No open alerts at this time.")
    for r in open_.sort_values("inr_per_day", ascending=False).itertuples():
        with st.container(border=True):
            st.markdown(f"{sev_badge(r.severity)} &nbsp; **{r.hotel} · {r.title}** — since {r.start:%d %b %H:%M} "
                        f"({(NOW - r.start).total_seconds() / 3600:.0f} h) · **{inr(r.inr_per_day)}/day**", unsafe_allow_html=True)
            st.caption(r.evidence)
            st.markdown(f"**Action:** {r.action}")

    st.subheader("Per hotel")
    cols = st.columns(3)
    for col, s in zip(cols, SITES):
        bs = b[b.site == s]
        cs = seen[seen.site == s]
        d = frame(s)
        with col, st.container(border=True):
            st.markdown(f"#### {SITES[s]}")
            st.metric("Energy cost (year)", inr(bs.total_energy_cost_inr.sum()))
            st.metric("Alerts to date / ₹ flagged", f"{len(cs)} / {inr(cs.cost_inr.sum())}")
            last = d[(d.timestamp <= NOW) & (d.timestamp > NOW - pd.Timedelta(days=7))]
            fig = go.Figure([go.Scatter(x=last.timestamp, y=last.pred_ens, name="baseline", line=dict(color=BASE)),
                             go.Scatter(x=last.timestamp, y=last.total_kwh, name="actual kW", line=dict(color=ACT, width=1.5))])
            st.plotly_chart(style_fig(fig, 200), width="stretch", key=f"ov_{s}")

    st.subheader("Today's BMS alarms vs this product")
    t = pd.DataFrame({"": ["Alarms / alerts per year", "Precision (alarms that are real waste)", "Recall of High+Medium waste",
                           "Median time to detect (High)", "Closed with no action"],
                      "BMS today (brief)": ["1,829", "26%", "40%", "8.3 h (alarm → action)", "66%"],
                      "This product (held-out, from 1 Apr 2026)": [f"{len(c)}", "98%", "96%", "1.0 h (from first appearance)", "rate in Alerts tab"]})
    st.dataframe(t, hide_index=True, width="stretch")
    st.caption("Held-out scores from notebooks 05/06: detector frozen before scoring labels from 1 Apr 2026. Post-hoc demand/EV rules excluded from these figures.")


def evidence_chart(r):
    d = frame(r.site)
    pad = pd.Timedelta(hours=max(12, min(48, r.duration_h)))
    w = d[(d.timestamp >= r.start - pad) & (d.timestamp <= min(r.end + pad, NOW))]
    fig = go.Figure()
    fig.add_vrect(x0=r.start, x1=r.end, fillcolor=ACC, opacity=0.10, line_width=0, annotation_text="alert window", annotation_position="top left")
    fig.add_trace(go.Scatter(x=w.timestamp, y=w.pred_ens, name="expected (baseline)", line=dict(color=BASE, dash="dot")))
    fig.add_trace(go.Scatter(x=w.timestamp, y=w.total_kwh, name="site kW (actual)", line=dict(color=ACT, width=1.5)))
    fig.update_layout(title="Main meter vs weather/occupancy/event baseline")
    figs = [style_fig(fig)]
    from alert_cards import CHART
    sub = [c for c in CHART.get(r.rule, []) if c in w]
    if sub:
        f2 = go.Figure()
        for c in sub:
            yaxis = "y2" if c in ("ev_guests", "temp_c", "chiller_load_tr", "n_chillers", "chw_setpoint_c", "kw_per_tr", "pf") and len(sub) > 1 and c != sub[0] else "y"
            f2.add_trace(go.Scatter(x=w.timestamp, y=w[c], name=c, yaxis=yaxis, line=dict(width=1.5)))
        f2.add_vrect(x0=r.start, x1=r.end, fillcolor=ACC, opacity=0.10, line_width=0)
        f2.update_layout(title="Equipment evidence", yaxis2=dict(overlaying="y", side="right", showgrid=False))
        figs.append(style_fig(f2, 260))
    return figs


def page_alerts():
    st.title("Alerts")
    c = cards()
    f1, f2, f3, f4 = st.columns([1, 1, 1, 1])
    site = f1.multiselect("Hotel", list(SITES), default=list(SITES), format_func=SITES.get)
    sev = f2.multiselect("Severity", ["High", "Medium", "Low"], default=["High", "Medium", "Low"])
    scope = f3.selectbox("Show", ["Raised up to replay time", "Open at replay time", "Whole year"])
    sort = f4.selectbox("Sort by", ["₹ impact", "Newest"])
    x = c[c.site.isin(site) & c.severity.isin(sev)]
    if scope != "Whole year":
        x = x[x.alert_time <= NOW]
    if scope == "Open at replay time":
        x = x[x.end > NOW]
    x = x.sort_values("cost_inr" if sort == "₹ impact" else "alert_time", ascending=False)
    st.caption(f"{len(x)} alerts · {inr(x.cost_inr.sum())} flagged. Ranked by ₹ by default (owner default: rank by ₹, show confidence).")

    tab1, tab2, tab3 = st.tabs(["Alert cards", "Data faults (suppressed)", "Big events — why no alert"])
    with tab1:
        if x.empty:
            st.info("No alerts for these filters.")
            return
        left, right = st.columns([1, 2])
        labels = [f"{r.alert_id} · {r.hotel} · {r.title} · {r.start:%d %b} · {inr(r.cost_inr)}" for r in x.itertuples()]
        pick = left.radio("Alerts", range(len(x)), format_func=lambda i: labels[i], label_visibility="collapsed")
        r = x.iloc[pick].copy()
        live = scope != "Whole year" and r.end > NOW
        if live:                      # replay: show only what was known at NOW
            so_far = (NOW - r.start).total_seconds() / 3600
            r["cost_inr"] = r.inr_per_hour * so_far if r.cost_inr else 0.0
            r["duration_h"] = so_far
            r["end"] = NOW
        with right:
            st.markdown(f"{sev_badge(r.severity)} &nbsp; `{r.alert_id}` {'&nbsp; <i>post-hoc rule</i>' if r.post_hoc else ''}", unsafe_allow_html=True)
            st.markdown(f"### {r.hotel} · {r.title}")
            m = st.columns(4)
            m[0].metric("Since", f"{r.start:%d %b, %H:%M}")
            m[1].metric("Running for" if live else "Duration", f"{r.duration_h:.0f} h" + (" (ongoing)" if live else ""))
            m[2].metric("₹ / hour", inr(r.inr_per_hour) if r.cost_inr else "—")
            m[3].metric("₹ / day", inr(r.inr_per_day) if r.cost_inr else "—")
            st.caption(f"Raised {r.alert_time:%d %b %H:%M} ({r.detect_lag_h:.1f} h after the signature started) · {'cost so far' if live else 'episode total'} {inr(r.cost_inr)}"
                       + (f" · {r.cost_note}" if r.cost_note else ""))
            st.markdown(f"**Evidence.** {r.evidence}")
            st.markdown(f"**Where.** {r.equipment}")
            st.markdown(f"**Likely cause.** {r.cause}")
            st.markdown(f"**Recommended action.** {r.action}")
            st.info(r.guard_text, icon="🛡️")
            for i, f in enumerate(evidence_chart(r)):
                st.plotly_chart(f, width="stretch", key=f"ev_{r.alert_id}_{i}")
            with st.form(f"act_{r.alert_id}"):
                a1, a2 = st.columns(2)
                act = a1.selectbox("Response", ["Acknowledge", "Snooze 2 h", "Not waste (explain)"])
                why = a2.text_input("Reason / note")
                rating = st.slider("How useful is this alert? (1 = noise, 5 = would act on it)", 1, 5, 4)
                if st.form_submit_button("Record"):
                    if act != "Acknowledge" and not why:
                        st.warning("A reason is required to snooze or dismiss.")
                    else:
                        st.session_state.audit.append(dict(time=pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), alert_id=r.alert_id, response=act,
                                                           reason=why, usefulness=rating))
                        st.success("Recorded in the audit log.")
        if st.session_state.audit:
            st.divider()
            st.markdown("**Audit log (this session)**")
            log = pd.DataFrame(st.session_state.audit)
            st.dataframe(log, hide_index=True, width="stretch")
            st.metric("Mean usefulness", f"{log.usefulness.mean():.1f} / 5 over {len(log)} ratings")
            st.download_button("Download ratings CSV", log.to_csv(index=False), "alert_ratings.csv")
    with tab2:
        f = faults()
        st.markdown("Meter data faults are found from the billed readings themselves (frozen or zero kWh while kW stays live). "
                    "They are **never** alerts or savings: those hours are excluded from the baseline and from every waste rule (T5).")
        st.dataframe(f[["hotel", "start", "end", "kind", "detected_at", "evidence", "handling"]], hide_index=True, width="stretch")
        n_in = sum(((c.site == r.site) & (c.start < r.end) & (c.end > r.start)).sum() for r in f.itertuples())
        st.metric("Waste alerts raised inside fault windows", n_in)
    with tab3:
        st.markdown("Large events add real load. The baseline includes event guests and timing, so a busy wedding night is compared with what a wedding "
                    "night should use — no alert unless something else is wrong (T2).")
        e = events()
        e = e[(e.guests >= 300) & e.site.isin(site)].copy()
        rows = []
        for r in e.itertuples():
            d = frame(r.site)
            day = d[d.timestamp.dt.normalize() == pd.Timestamp(r.date)]
            ev = day[day.hour >= int(r.start_time[:2])]
            al = c[(c.site == r.site) & (c.start < pd.Timestamp(r.date) + pd.Timedelta(days=1, hours=2)) & (c.end > pd.Timestamp(r.date) + pd.Timedelta(hours=int(r.start_time[:2])))]
            rows.append(dict(hotel=SITES[r.site], date=r.date, event=r.event_type, guests=r.guests, temp_max=day.temp_c.max(),
                             actual_kw=ev.total_kwh.mean(), expected_kw=ev.pred_ens.mean(), gap_pct=(ev.total_kwh.mean() / ev.pred_ens.mean() - 1) * 100,
                             alerts=", ".join(al.title.unique()) or "none"))
        t = pd.DataFrame(rows)
        st.dataframe(t.round(1), hide_index=True, width="stretch")
        if len(t):
            st.caption(f"{(t.alerts == 'none').sum()} of {len(t)} events ≥300 guests raise no alert; event-hour load is within "
                       f"{t.gap_pct.abs().median():.1f}% (median) of the event-aware baseline. Alerts that do overlap an event name specific equipment "
                       "(e.g. lighting left on after the event ends), each checked against a labelled anomaly in notebook 06.")


def page_bills():
    st.title("Bills")
    site = st.radio("Hotel", list(SITES), format_func=SITES.get, horizontal=True)
    r = recon()[lambda t: t.site == site]
    k = st.columns(4)
    k[0].metric("Bills reconciled", f"{(r.status == 'Reconciled').sum()} / {len(r)}")
    k[1].metric("Meter-fault months", int((r.status == "Meter fault").sum()))
    k[2].metric("Provisional bills", int((r.status == "Provisional").sum()))
    k[3].metric("Year total", inr(r.billed_total.sum()))
    from bills import components
    comp = components(site)
    fig = go.Figure()
    for cname in comp.component.unique():
        z = comp[comp.component == cname]
        fig.add_trace(go.Bar(x=z.billing_month, y=z.inr, name=cname))
    fig.update_layout(barmode="relative", title="Issued bill by component (₹)")
    st.plotly_chart(style_fig(fig, 360), width="stretch")

    st.subheader("Reconciliation")
    st.caption("Each bill is rebuilt from the tariff sheet (proves every ₹ line) and from the meter (proves the quantities). Demand: billing demand = "
               "max(MD, 75% of contract demand), charged up to contract demand; excess above contract demand at 2× (penalty on top). Bills are never altered.")
    show = r[["month", "status", "billed_total", "tariff_check_max_gap", "billed_kvah", "meter_kvah", "meter_gap_pct", "corrected_total",
              "billed_minus_corrected", "md_kva", "billing_demand_kva", "pf", "note"]].rename(columns={"tariff_check_max_gap": "max line gap ₹"})

    def color(v):
        return {"Reconciled": "color: #1e8449", "Meter fault": "color: #7d3c98", "Provisional": "color: #c0392b"}.get(v, "")
    st.dataframe(show.style.map(color, subset=["status"]).format({"billed_total": "₹{:,.0f}", "corrected_total": "₹{:,.0f}", "billed_minus_corrected": "₹{:,.0f}",
                                                                   "max line gap ₹": "{:,.0f}", "billed_kvah": "{:,.0f}", "meter_kvah": "{:,.0f}", "meter_gap_pct": "{:+.2f}%",
                                                                   "md_kva": "{:,.0f}", "billing_demand_kva": "{:,.0f}", "pf": "{:.3f}"}),
                 hide_index=True, width="stretch")
    from bills import unused_demand
    u = unused_demand(site)
    if u["months_on_floor"]:
        st.warning(f"Demand floor: recorded MD stayed below 75% of contract demand ({u['floor']:,.0f} kVA) in {u['months_on_floor']} of 12 months "
                   f"(max MD {u['max_md']:,.0f} kVA). ₹{u['paid_for_unused_inr']:,.0f} was paid this year for demand not used — see Savings.")

    st.subheader("Why did the bill change?")
    months = list(r.month)
    a1, a2 = st.columns(2)
    ma = a1.selectbox("From month", months, index=months.index("2026-04") if "2026-04" in months else 0)
    mb = a2.selectbox("To month", months, index=months.index("2026-05") if "2026-05" in months else 1)
    if ma == mb:
        st.info("Pick two different months.")
        return
    a, b = sorted([ma, mb])
    x = explain(site, a, b)
    g = x["table"].groupby("group").inr.sum().sort_values(key=abs, ascending=False)
    g = g[g.abs() >= 1]
    fig = go.Figure(go.Waterfall(x=[f"{a} bill"] + list(g.index) + [f"{b} bill"], measure=["absolute"] + ["relative"] * len(g) + ["total"],
                                 y=[x["bill_a"]] + list(g.values) + [x["bill_b"]], connector=dict(line=dict(color="rgba(128,128,128,0.4)")),
                                 increasing=dict(marker=dict(color=ACC)), decreasing=dict(marker=dict(color="#1e8449")), totals=dict(marker=dict(color=ACT))))
    fig.update_layout(title=f"{SITES[site]}: {a} → {b}, change {inr(x['delta'])}", yaxis=dict(range=[min(x['bill_a'], x['bill_b']) * 0.85, max(x['bill_a'], x['bill_b']) * 1.04]))
    st.plotly_chart(style_fig(fig, 380), width="stretch")
    ctx = x["context"]
    st.markdown(f"Cooling degree-hours {ctx['cdh_A']:,.0f} → {ctx['cdh_B']:,.0f} · max temp {ctx['tmax_A']:.1f} → {ctx['tmax_B']:.1f} °C · "
                f"room-nights sold {ctx['rooms_A']:,.0f} → {ctx['rooms_B']:,.0f} · event guests {ctx['event_guests_A']:,} → {ctx['event_guests_B']:,} · "
                f"MD {ctx['md_A']:,.0f} → {ctx['md_B']:,.0f} kVA · PF {ctx['pf_A']:.3f} → {ctx['pf_B']:.3f}")
    with st.expander("Line-by-line detail and method"):
        st.dataframe(x["table"].round(0), hide_index=True, width="stretch")
        st.caption("kWh change split by the baseline model (exact Shapley over weather / occupancy / events; calendar = day count). ₹ at the month's marginal "
                   "rate; PF, ToD, demand, penalty and diesel from the bills. 'Rounding' closes the sum to the two issued bills exactly.")


def page_forecast():
    st.title("Day-ahead demand — Gurugram")
    F = fc()
    t1, t2 = st.tabs(["Forecast for a day", "What if tomorrow… (T7)"])
    with t1:
        day = st.date_input("Day", value=(NOW + pd.Timedelta(days=1)).date(), min_value=pd.Timestamp("2025-10-08").date(), max_value=pd.Timestamp("2026-09-30").date())
        w, a = F.day_view(day)
        show_risk(a)
        fig = go.Figure([go.Scatter(x=w.hour, y=w.pred_kva, name="forecast kVA (made the day before)", line=dict(color=ACT)),
                         go.Scatter(x=w.hour, y=w.actual_kva, name="actual kVA", line=dict(color=INK, width=1, dash="dot"))])
        add_lines(fig)
        st.plotly_chart(style_fig(fig, 340), width="stretch")
        S = F.state()["S"]
        st.caption(f"Out-of-sample accuracy over the year: daily-peak MAPE 5.4%, 59% of days within ±5%, 86% within ±10%. "
                   f"Only three days exceeded 1,000 kVA (12 May, 18 Jun, 25 Jun); all were caused by shiftable loads stacking on a hot afternoon, which "
                   f"weather and bookings cannot see — the stacking watch covers that risk.")
    with t2:
        c1, c2, c3 = st.columns(3)
        tmax = c1.slider("Tomorrow's max temperature (°C)", 30.0, 46.0, 40.0, 0.5)
        guests = c2.slider("Conference guests (09:00–18:00)", 0, 600, 318, 10)
        tmpl = c3.date_input("Template weekday (sets rooms sold, lags)", value=pd.Timestamp("2026-05-20").date(),
                             min_value=pd.Timestamp("2025-10-08").date(), max_value=pd.Timestamp("2026-09-30").date())
        w, a = F.scenario(tmpl, tmax, guests)
        w0, a0 = F.scenario(tmpl, tmax, 0)
        show_risk(a)
        fig = go.Figure([go.Scatter(x=w0.hour, y=w0.pred_kva, name=f"{tmax:.0f} °C, no event", line=dict(color=BASE)),
                         go.Scatter(x=w.hour, y=w.pred_kva, name=f"{tmax:.0f} °C + {guests}-guest conference", line=dict(color=ACC))])
        add_lines(fig)
        st.plotly_chart(style_fig(fig, 340), width="stretch")


def add_lines(fig):
    for y, n, c, pos in ((1000, "contract demand 1,000", "#c0392b", "top left"), (920, "EV-throttle 920", "#d68910", "top right"),
                         (900, "watch 900", "#7f8c8d", "bottom left")):
        fig.add_hline(y=y, line=dict(color=c, dash="dash", width=1), annotation_text=n, annotation_position=pos)
    fig.update_layout(xaxis_title="hour", yaxis_title="kVA")


def show_risk(a):
    color = {"OK": "success", "STACKING WATCH": "info", "WARNING": "warning", "BREACH RISK": "error"}[a["level"]]
    m = st.columns(4)
    m[0].metric("Forecast peak", f"{a['peak']:,.0f} kVA", help="Hourly max-kVA forecast")
    m[1].metric("Peak hour", f"{a['hour']}:00")
    m[2].metric("90% upper bound", f"{a['upper']:,.0f} kVA")
    m[3].metric("Shiftable-load headroom", f"{a['allowance']:,.0f} kVA", help="If laundry, water heating and banquet AHUs ran at connected rating")
    getattr(st, color)(f"**{a['level']}**" + (f" — {a['why']}" if a["why"] else " — no action needed."))
    if a["plan"] is not None:
        st.markdown("**Recommended load moves (recommend only — a person approves; chillers, kitchen, lifts, guest rooms and life-safety are never shed):**")
        p = a["plan"][["load", "action", "basis", "kw_moved", "relief_kva", "demand_after_kva", "reaches_target"]]
        st.dataframe(p.round(0), hide_index=True, width="stretch")


def page_savings():
    st.title("Savings")
    p = savings_plan()
    yr = bills().total_energy_cost_inr.sum()
    k = st.columns(4)
    k[0].metric("Identified savings / year", inr(p.inr.sum()))
    k[1].metric("Share of group bill", f"{p.inr.sum() / yr * 100:.1f}%", help="Brief target 8–12%")
    for i, cat in enumerate(["Energy", "ToD", "Demand"]):
        pass
    by = p.groupby("category").inr.sum()
    k[2].metric("Energy / ToD / Demand", " / ".join(inr(by.get(c, 0)) for c in ["Energy", "ToD", "Demand"]))
    k[3].metric("Target (8–12%)", f"{inr(0.08 * yr)} – {inr(0.12 * yr)}")
    st.warning(f"Honest gap: the measures we can size from the data reach {p.inr.sum() / yr * 100:.1f}% of the bill, below the 8–12% target. The labelled waste "
               "in the data set is itself ~2.9% of the bill (brief). Reaching 8%+ needs measures the data cannot size (base-load audit, capital items) — listed below.")
    st.dataframe(p[["hotel", "category", "measure", "inr", "pct_of_site_bill", "basis", "safety", "confidence"]].style.format({"inr": "₹{:,.0f}", "pct_of_site_bill": "{:.1f}%"}),
                 hide_index=True, width="stretch")
    from savings import NOT_SIZED
    st.markdown("**Not sized (and why):**\n" + "\n".join(f"- {x}" for x in NOT_SIZED))

    st.subheader("Verification — IPMVP Option C")
    st.markdown("Savings are only claimed as **adjusted baseline − actual**: the baseline model (weather, occupancy, events, day type) is driven by the "
                "reporting period's real conditions. The data year contains no implemented measure, so no verified saving is claimed here — this panel shows "
                "the model finance would rely on and the smallest saving it can prove.")
    site = st.radio("Hotel ", list(SITES), format_func=SITES.get, horizontal=True)
    s = mv_stats(site)
    m = st.columns(4)
    m[0].metric("CV(RMSE) hourly", f"{s['cv_rmse_hourly']:.1f}%", help="ASHRAE G14 limit 30%")
    m[1].metric("CV(RMSE) monthly", f"{s['cv_rmse_monthly']:.1f}%", help="ASHRAE G14 limit 15%")
    m[2].metric("NMBE", f"{s['nmbe']:+.2f}%", help="ASHRAE G14 limit ±5% (hourly ±10%)")
    m[3].metric("Uncertainty on an 8% saving (90%)", f"±{s['fsu_at_8pct']:.0f}% of the saving", help="ASHRAE G14 fractional savings uncertainty, one reporting year, autocorrelation-adjusted")
    mv = s["monthly"].reset_index()
    fig = go.Figure([go.Bar(x=mv.month, y=mv.baseline, name="adjusted baseline (kWh)", marker_color=BASE),
                     go.Scatter(x=mv.month, y=mv.actual, name="actual (kWh)", mode="lines+markers", line=dict(color=ACT))])
    st.plotly_chart(style_fig(fig, 300), width="stretch")
    st.caption("Out-of-fold baseline (each month predicted by a model that never saw it). Meter-fault hours excluded; faults are never savings.")


def page_assistant():
    st.title("Assistant")
    st.caption("Ask about bills, alerts, tomorrow's demand or savings. Every number comes from the models and is checked before it is shown. "
               "The assistant recommends only and refuses unsafe automation.")
    try:
        key = st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        key = None
    if not key:
        st.info("No Claude API key configured — answering with the built-in rules engine (same tools, template wording).")
    if "chat" not in st.session_state:
        st.session_state.chat = []
    ex = ["Why was Gurugram's May 2026 bill higher than April's?", "Auto switch off kitchen exhaust overnight",
          "What's the demand risk at Gurugram on 2026-06-18?", "Is the Goa July 2026 bill right?", "What are the biggest alerts in Jaipur?",
          "How much can we save, and where?"]
    cols = st.columns(3)
    clicked = None
    for i, q in enumerate(ex):
        if cols[i % 3].button(q, key=f"ex{i}", width="stretch"):
            clicked = q
    for m in st.session_state.chat:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m.get("mode"):
                st.caption(m["mode"])
    q = st.chat_input("Ask a question") or clicked
    if q:
        from assistant import answer
        st.session_state.chat.append(dict(role="user", content=q))
        with st.chat_message("user"):
            st.markdown(q)
        with st.chat_message("assistant"), st.spinner("Working it out from the data…"):
            hist = [dict(role=m["role"], content=m["content"]) for m in st.session_state.chat[:-1]][-6:]
            try:
                r = answer(q, history=hist, api_key=key)
            except Exception as e:
                from assistant import _fallback_text, _route, TOOLS
                calls = [(n, a, TOOLS[n][0](**a)) for n, a in _route(q)]
                r = dict(text=_fallback_text(calls), mode=f"rules engine (Claude unavailable: {type(e).__name__})", calls=calls)
            st.markdown(r["text"])
            st.caption(r["mode"])
            if r["calls"]:
                with st.expander("Data used"):
                    for n, a, res in r["calls"]:
                        st.markdown(f"`{n}({a})`")
                        st.json(res, expanded=False)
        st.session_state.chat.append(dict(role="assistant", content=r["text"], mode=r["mode"]))


def page_method():
    st.title("Method & limits")
    st.markdown("""
**What it does.** For each hotel, a baseline model (Ridge + shallow LightGBM, averaged) predicts the hour's load from weather, rooms sold, F&B covers,
the events calendar and day type. A rule layer checks each waste signature on the sub-meters against learned *normal for this context* profiles, a residual layer
catches persistent unexplained load, and a separate stream finds meter data faults. Alerts carry evidence, ₹/h, ₹/day, cause and action.

**Accuracy (held-out months / labels from 1 Apr 2026).**
| | Result | Target |
|---|---|---|
| Baseline CV(RMSE) hourly / monthly | GGN 8.3 / 3.4 %, JAI 5.0 / 1.1 %, GOA 5.4 / 2.8 % | < 30 % / < 15 % |
| Baseline NMBE | within ±0.1 % | ±5 % |
| Alert precision | 98 % | ≥ 70 % |
| Recall, High + Medium | 96 % | ≥ 75 % |
| Time to detect (High, from first appearance) | median 1.0 h | < 2 h |
| Day-ahead peak (Gurugram) | MAPE 5.4 %, 59 % of days within ±5 % | ±5 % |

**No label leakage.** Rules and thresholds were set on anomalies before 1 Apr 2026 and frozen; results are reported on later labels. The contract-demand and
EV-charger rules were added after seeing held-out gaps and are labelled *post-hoc*.

**Guardrails.** Recommend only — a person approves. Kitchen exhaust, guest-room thermostats, lifts and life-safety are never automated. CHW never below 6.5 °C.
Meter faults are never alerts or savings, and bills are never altered. LLM text is checked: every number must exist in the model outputs.
""")
    from waste_types import NOT_DETECTED
    st.markdown("**What the product cannot see:**\n" + "\n".join(f"- {x}" for x in NOT_DETECTED))
    st.markdown("**Data caveats.** Synthetic data, fictional company, illustrative tariffs. CH-2 is treated as unavailable (owner-confirmed). Events "
                "recorded as ending 23:59 are assumed to end at 01:00. One year of data: every season is seen once.")


{"Overview": page_overview, "Alerts": page_alerts, "Bills": page_bills, "Forecast (Gurugram)": page_forecast, "Savings": page_savings,
 "Assistant": page_assistant, "Method & limits": page_method}[page]()
