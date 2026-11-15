"""Generate the synthetic "live" year 1 Oct 2026 - 30 Sep 2027 for GGN, JAI and GOA into data/live/.

THIS DATA IS SYNTHETIC. There is no real data after 30 Sep 2026; the app's live mode needs a year to replay, so we
build one from the cleaned original year (data/clean/, Oct 2025 - Sep 2026) the same way the team built earlier
years in tools/make_large_dataset.py (ManishNair01/Applied-AI-Challenge, snapshot/light-2026-11-15):

  * Every forward week is copied from one source week of the original year: the same point in the season
    (target date - 364 days, shifted by 0, +-1 or +-2 weeks at random), weekday preserved. Weather, load,
    sub-meters, occupancy and events for a week all come from that one source week, so they stay consistent.
  * The labelled waste is removed from the source first (each label's channel is refilled with the median of the
    same hour on unlabelled days; chiller staging, CHW setpoint and PF episodes are put back to normal), so last
    year's faults are not repeated on the same dates.
  * On top: a weekly temperature offset (AR(1), sd 1 C) with a chiller response of 3.5 % per C, a growth trend of
    1.2 % a year, and small day-to-day and hour-to-hour noise. The main meter is rebuilt from the sub-meters with
    the source hour's main/sub ratio, so sub-meters still sum to the main meter and kWh/kVAh/kVA/PF stay consistent.
  * New anomalies are injected at random at the original per-site, per-type yearly rates (RATES / TYPE_CH copied
    from make_large_dataset.py), at exactly each type's yearly count. Each is written to anomaly_labels.parquet (ids LV-0001...) with its measured excess.
    Exactly one meter comms fault per site (billed columns flat while kW and PF stay live) is injected, kept in the
    *_raw columns as in data/clean, and listed in meter_faults.parquet.
  * Tariffs: one new rate set per site effective 1 Oct 2026, every rupee rate +3 % (contract demand and the 2 %
    municipal tax unchanged). Bills: one per site per month, priced with src/bills.py's own rule from the generated
    meter readings as the utility would read them (comms-fault values included, as in the original Gurugram bills),
    issued on the 5th of the next month (bill_issued).
  * No dirty-data faults are injected: the output is already clean, with the same schemas as data/clean/.
    Deviations: meter_goa_hourly gains grid_kwh_raw / grid_kvah_raw / kva_max_in_hour_raw (Goa had no comms fault
    before, so the clean table had nowhere to keep the readings as billed); monthly_bills gains bill_issued;
    tariffs gains effective_from. On Jaipur the comms-fault hours are flagged is_imputed (rebuilt from live kW),
    which is how features.unified_hourly() picks up a Jaipur meter fault.

LABEL LEAKAGE: the injected anomaly types and rates come from the full original label set, including labels from
1 Apr 2026. Scores of the frozen detector on this year are a robustness check, not a clean held-out test.

Run: uv run python tools/make_live_year.py      (seeded, same output every run, well under 2 minutes)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import bills  # noqa: E402  (priced with the pipeline's own bill rule)
from features import gurugram_hourly  # noqa: E402

CLEAN = ROOT / "data" / "clean"
OUT = ROOT / "data" / "live"
SEED = 2027
ORIG, START = pd.Timestamp("2025-10-01"), pd.Timestamp("2026-10-01")
ND = 365
NH = ND * 24
DAYS = pd.date_range(START, periods=ND, freq="D")
HOURS = pd.date_range(START, periods=NH, freq="h")
Q15 = pd.date_range(START, periods=NH * 4, freq="15min")
DMON = DAYS.month.to_numpy()
HOD = np.tile(np.arange(24), ND)
SITES = ("GGN", "JAI", "GOA")
CD = {"GGN": 1000, "JAI": 700, "GOA": 600}
COOL = {"chiller_ch1_kw", "chiller_ch3_kw", "chillers_kw"}
RATES = {  # anomalies per site-year, from the original label counts (copied from make_large_dataset.py)
    "GGN": {"AHU_SCHEDULE_OVERRIDE": 16, "CHILLER_ON_LOW_LOAD": 13, "CHW_SETPOINT_LOWERED": 8, "CONTRACT_DEMAND_BREACH": 3,
            "EV_CHARGER_FAULT": 2, "KITCHEN_EXHAUST_LEFT_ON": 10, "LAUNDRY_PEAK_TARIFF": 12, "METER_DATA_FAULT": 3,
            "POWER_FACTOR_DROP": 2, "SIMULTANEOUS_HEAT_COOL": 9},
    "JAI": {"CHILLER_ON_LOW_LOAD": 6, "EVENT_LIGHTING_LEFT_ON": 9, "LAUNDRY_PEAK_TARIFF": 4, "METER_DATA_FAULT": 1,
            "POWER_FACTOR_DROP": 1},
    "GOA": {"CHILLER_ON_LOW_LOAD": 6, "LAUNDRY_PEAK_TARIFF": 3, "POOL_PUMPS_24H": 3, "METER_DATA_FAULT": 1},
}
TYPE_CH = {"AHU_SCHEDULE_OVERRIDE": ["ahu_banquet_kw"], "CONTRACT_DEMAND_BREACH": ["laundry_kw", "ahu_banquet_kw", "water_heating_kw"],
           "EV_CHARGER_FAULT": ["ev_chargers_kw"], "KITCHEN_EXHAUST_LEFT_ON": ["kitchen_exhaust_mua_kw"],
           "LAUNDRY_PEAK_TARIFF": ["laundry_kw"], "POOL_PUMPS_24H": ["pumps_pool_kw"], "EVENT_LIGHTING_LEFT_ON": ["lighting_kw"],
           "SIMULTANEOUS_HEAT_COOL": ["ahu_heaters_kw"], "POWER_FACTOR_DROP": ["pf"]}
N_FIXED = {"METER_DATA_FAULT": 1}          # exactly one comms fault per site (the original GGN year had 3)
OVERSAMPLE = 4                             # one year at the yearly rate exactly; candidates that collide are skipped


def us(t):
    return pd.DatetimeIndex(t).astype("datetime64[us]")


def ar1(rng, n, sd, rho):
    e = rng.normal(0, sd * np.sqrt(1 - rho ** 2), n)
    x = np.empty(n)
    x[0] = rng.normal(0, sd)
    for i in range(1, n):
        x[i] = rho * x[i - 1] + e[i]
    return x


# ----------------------------------------------------------------------------------------------- templates
def fill_normal(x, hrs, blocked):
    """Replace x[hrs] with the median of the same hour on unlabelled days within +-28 days."""
    y = x.copy()
    off = 24 * np.r_[np.arange(-28, 0), np.arange(1, 29)]
    for h in hrs:
        c = h + off
        c = c[(c >= 0) & (c < len(x))]
        c = c[~blocked[c]]
        if len(c):
            y[h] = np.median(x[c])
    return y


def build_templates(rng):
    """The original year per site with its labelled waste taken out (as make_large_dataset.build_templates)."""
    lab = pd.read_parquet(CLEAN / "anomaly_labels.parquet")
    ev = pd.read_parquet(CLEAN / "events.parquet")
    occ = pd.read_parquet(CLEAN / "occupancy_daily.parquet")
    wx = pd.read_parquet(CLEAN / "weather_hourly.parquet")
    sjg = pd.read_parquet(CLEAN / "sub_jai_goa_hourly.parquet")
    hr = pd.Timedelta("1h")
    T = {}
    for site in SITES:
        t = {}
        if site == "GGN":
            g = pd.read_parquet(CLEAN / "meter_ggn_15min.parquet").sort_values("timestamp")
            s = pd.read_parquet(CLEAN / "sub_ggn_hourly.parquet").sort_values("timestamp")
            load15 = (g["total_kwh"] * 4).to_numpy(float).copy()
            load = load15.reshape(-1, 4).mean(1)
            t["pf15"] = g["power_factor"].ffill().bfill().to_numpy(float).copy()
            t["dg15"] = g["is_dg"].to_numpy(bool).copy()
            t["sp"] = s["chw_setpoint_c"].to_numpy(float).copy()
            t["sup"] = s["chw_supply_temp_c"].to_numpy(float).copy()
            t["run"] = s["chillers_running"].to_numpy(float).copy()
        else:
            m = pd.read_parquet(CLEAN / f"meter_{site.lower()}_hourly.parquet").sort_values("timestamp")
            s = sjg[sjg.site == site].sort_values("timestamp")
            load = m["kw_avg"].to_numpy(float).copy()
            t["pf"] = m["power_factor"].to_numpy(float).copy()
            t["dgfrac"] = np.clip(m["dg_kwh"].to_numpy(float) / load, 0, 1)
            gk = m["grid_kvah"].to_numpy(float)
            t["kr"] = np.where(gk > 0, m["kva_max_in_hour"].to_numpy(float) / np.where(gk > 0, gk, 1), 1.05)
        kw = [c for c in s.columns if c.endswith("_kw")]
        sub = {c: s[c].to_numpy(float).copy() for c in kw}
        tr = s["chiller_load_tr"].to_numpy(float).copy()
        n = len(load)
        before = sum(sub.values())

        active = np.zeros(n, bool)                                  # hours when a banquet event legitimately runs AHUs
        for r in ev[ev.site == site].itertuples():
            d = (r.date - ORIG).days * 24
            a, b = (8, 19) if r.start_time < "12:00" else (17, 26)
            active[max(d + a, 0):min(d + b, n)] = True

        blocked, wins = {}, []
        for r in lab[lab.site == site].itertuples():
            a, b = max(int((r.start - ORIG) / hr), 0), min(int(np.ceil((r.end - ORIG) / hr)), n)
            chans = TYPE_CH.get(r.anomaly_type, ["chillers_kw"] if (r.anomaly_type == "CHILLER_ON_LOW_LOAD" and site != "GGN") else [])
            for c in chans:
                blocked.setdefault(c, np.zeros(n, bool))[a:b] = True
            wins.append((r.anomaly_type, a, b))
        for typ, a, b in wins:
            if site == "GGN" and typ == "CHILLER_ON_LOW_LOAD":       # back to CH-3 alone at ~0.65 kW/TR
                h = np.arange(a, b)
                h = h[(t["run"][h] == 2) & (tr[h] < 130)]
                sub["chiller_ch3_kw"][h] = tr[h] * 0.65
                sub["chiller_ch1_kw"][h] = 0
                t["run"][h] = 1
            if typ == "CHW_SETPOINT_LOWERED":
                h = np.arange(a, b)
                h = h[t["sp"][h] < 7]
                t["sp"][h] = 7.0
                t["sup"][h] += 1.5
                sub["chiller_ch1_kw"][h] /= 1.1
                sub["chiller_ch3_kw"][h] /= 1.1
        for c, bl in blocked.items():
            if c == "pf":
                continue
            hrs = np.flatnonzero(bl)
            if c == "ahu_banquet_kw":
                hrs = hrs[~active[hrs]]
            sub[c] = fill_normal(sub[c], hrs, bl)
        if "pf" in blocked:                                         # PF-drop episodes -> typical PF
            if site == "GGN":
                b15 = np.repeat(blocked["pf"], 4)
                t["pf15"][b15] = rng.choice(t["pf15"][~b15], b15.sum())
            else:
                bl = blocked["pf"]
                t["pf"][bl] = rng.choice(t["pf"][~bl], bl.sum())
        after = sum(sub.values())
        clean_load = load - (before - after)
        if site == "GGN":                                           # main/sub ratio stays inside the range seen on valid hours
            valid = ~(t["dg15"] | g["exclude_from_model"].to_numpy(bool)).reshape(-1, 4).any(1)
        else:
            valid = ~(m["is_dg"].to_numpy(bool) | m["exclude_from_model"].to_numpy(bool))
        r0 = (load / before)[valid & (before > 0)]
        t["ratio"] = np.clip(clean_load / after, max(r0.min(), 0.9), min(r0.max(), 1.1))
        if site == "GGN":
            t["r15"] = load15 / np.where(np.repeat(load, 4) > 0, np.repeat(load, 4), 1)
        t.update(sub=sub, kw=kw, tr=tr, avg=float(clean_load.mean()))
        w = wx[wx.site == site].sort_values("timestamp")
        t.update(temp=w["temp_c"].to_numpy(float), rh=w["rel_humidity_pct"].to_numpy(float), rain=w["rain_mm"].to_numpy(float))
        o = occ[occ.site == site].sort_values("date")
        t.update(occ=(o["rooms_sold"] / o["rooms_available"]).to_numpy(float), gpr=(o["guests_in_house"] / o["rooms_sold"]).to_numpy(float),
                 covers=o["covers_served_fnb"].to_numpy(float), rooms=int(o["rooms_available"].iat[0]))
        e = ev[ev.site == site].copy()
        e["src"] = (e["date"] - ORIG).dt.days
        t["events"] = e[["src", "event_type", "venue", "guests", "start_time", "end_time", "catering"]]
        T[site] = t
    return T, lab


def make_map(rng):
    """Target day -> source day by whole weeks (weekday preserved), plus a weekly temperature offset and growth."""
    d = np.arange(ND)
    wb = (d + START.day_of_week) // 7
    nb = wb.max() + 1
    j = rng.choice([-2, -1, 0, 1, 2], nb, p=[.1, .2, .4, .2, .1])
    dt = ar1(rng, nb, 1.0, 0.5)
    yf = 1.012 ** (1 + (d - ND / 2) / 365)                         # one year on: +1.2 %, ramping through the year
    return dict(src=(d + 1 + 7 * j[wb]) % 364, dt=dt[wb], yf=yf)    # d + 1: target date - 364 days, same weekday


# ------------------------------------------------------------------------------------------ anomaly planner
def plan(rng, site, avg, conf, wed, hot):
    """Draw this year's anomalies for one site: type, start/end minute, nominal kW and nominal excess."""
    pool = np.arange(ND - 2)
    rows = []

    def days(n, months=None):
        p = pool if months is None else pool[np.isin(DMON[pool], months)]
        return rng.choice(p, n) if len(p) and n else np.zeros(0, int)

    for typ, rate in RATES[site].items():
        n = OVERSAMPLE * N_FIXED.get(typ, rate)                    # spare candidates: inject() keeps the first that fit
        if not n:
            continue
        kvah, pen = None, 0.0
        if typ == "AHU_SCHEDULE_OVERRIDE":
            c = np.r_[conf * 24 + 18, (wed + 1) * 24 + 1]
            k = np.r_[np.full(len(conf), 45.), np.full(len(wed), 90.)]
            i = rng.choice(len(c), min(n, len(c)), replace=False)
            h0, kw = c[i], k[i]
            dur = rng.integers(12, 46, len(h0))
            kwh = kw * dur
        elif typ == "CHILLER_ON_LOW_LOAD":
            h0 = days(n, [10, 11, 12, 1, 2, 3, 4] if site == "JAI" else None) * 24 + 22
            dur = rng.integers(33, 130, len(h0))
            kw = np.full(len(h0), {"GGN": 85., "JAI": 30., "GOA": 36.}[site])
            kwh = kw * dur * (.75 if site == "GGN" else 10 / 24)
        elif typ == "CHW_SETPOINT_LOWERED":
            h0 = days(n, [4, 5, 6, 7, 8, 9]) * 24 + rng.integers(0, 24, n)
            dur = rng.integers(96, 361, len(h0))
            kw = np.full(len(h0), 15.)
            kwh = kw * dur
        elif typ == "CONTRACT_DEMAND_BREACH":
            d = rng.choice(hot, min(n, len(hot)), replace=False) if len(hot) else days(n, [5, 6])
            h0, dur = d * 24 + 14, np.full(len(d), 3)
            kw = np.full(len(d), 205.)
            kwh, pen = kw * 3, rng.uniform(20, 90, len(d))
        elif typ == "EV_CHARGER_FAULT":
            h0 = days(n) * 24 + rng.integers(0, 24, n)
            dur = rng.integers(72, 193, n)
            kw = np.full(n, 6.)
            kwh = kw * dur
        elif typ == "KITCHEN_EXHAUST_LEFT_ON":
            h0 = days(n) * 24 + 23
            dur = rng.integers(30, 79, n)
            kw = np.full(n, 22.)
            kwh = kw * 6 * np.ceil(dur / 24)
        elif typ == "LAUNDRY_PEAK_TARIFF":
            h0, dur = days(n) * 24 + 18, np.full(n, 4)
            kw = np.full(n, 74. if site == "GGN" else 50.)
            kwh = np.zeros(n)
        elif typ == "METER_DATA_FAULT":                             # placed later, on grid supply; minutes here
            q = site == "GGN"
            m0 = days(n) * 1440 + (rng.integers(0, 96, n) * 15 if q else rng.integers(0, 24, n) * 60)
            dm = rng.integers(20, 53, n) * 15 if q else rng.integers(5, 13, n) * 60
            rows.append(pd.DataFrame(dict(type=typ, m0=m0, m1=m0 + dm, kw=0., kwh=0., kvah=0., pen=0.)))
            continue
        elif typ == "POWER_FACTOR_DROP":
            h0 = days(n) * 24
            dur = rng.integers(8, 13, n) * 24
            kw, kwh = np.zeros(n), np.zeros(n)
            kvah = avg * dur * (1 / .88 - 1 / .976)
        elif typ == "SIMULTANEOUS_HEAT_COOL":
            h0 = days(n, [11, 12, 1, 2, 3]) * 24 + 8
            dur = rng.integers(48, 145, n)
            kw = rng.uniform(40, 60, n)
            kwh = kw * dur * .5
        elif typ == "POOL_PUMPS_24H":
            h0 = days(n) * 24
            dur = rng.integers(14, 29, n) * 24
            kw = np.full(n, 14.)
            kwh = kw * dur * 14 / 24
        elif typ == "EVENT_LIGHTING_LEFT_ON":
            h0 = (rng.choice(wed, min(n, len(wed)), replace=False) + 1) * 24 + 1
            dur = rng.integers(8, 13, len(h0))
            kw = np.full(len(h0), 55.)
            kwh = kw * dur
        rows.append(pd.DataFrame(dict(type=typ, m0=h0 * 60, m1=(h0 + dur) * 60, kw=kw, kwh=kwh,
                                      kvah=kwh / .976 if kvah is None else kvah, pen=pen)))
    P = pd.concat(rows, ignore_index=True)
    P = P[P.m1 <= ND * 1440]
    return P.iloc[rng.permutation(len(P))].reset_index(drop=True)  # random order, so spares are not biased to early dates


# ---------------------------------------------------------------------------------------------- one site
class Site:
    def __init__(self, code, mp, t, rng):
        self.code, self.mp, self.t, self.rng = code, mp, t, rng
        self.sh = (mp["src"][:, None] * 24 + np.arange(24)).ravel()
        fac = np.repeat(mp["yf"] * np.exp(ar1(rng, ND, .02, .6)), 24)
        self.dT = np.repeat(mp["dt"], 24)
        cool = np.clip(1 + .035 * self.dT, .75, 1.3)
        self.ch = {}
        for c in t["kw"]:
            x = t["sub"][c][self.sh] * fac * (1 + rng.normal(0, .012, NH))
            self.ch[c] = x * cool if c in COOL else x
        self.tr = t["tr"][self.sh] * fac * cool
        self.temp = t["temp"][self.sh] + self.dT
        self.pf_over = np.full(NH, np.nan)
        if code == "GGN":
            self.sp, self.run = t["sp"][self.sh].copy(), t["run"][self.sh].copy()
            self.sup = t["sup"][self.sh] + rng.normal(0, .05, NH)
            sq = (mp["src"][:, None] * 96 + np.arange(96)).ravel()
            self.r15, self.pf15, self.dg15 = t["r15"][sq], t["pf15"][sq].copy(), t["dg15"][sq]
        self.labels, self.cmd, self.faults, self.win = [], [], [], {}
        self.events = self._events()

    def _events(self):
        e = pd.DataFrame(dict(d=np.arange(ND), src=self.mp["src"])).merge(self.t["events"], on="src").sort_values("d")
        g = e["guests"].to_numpy() * (1 + self.rng.normal(0, .05, len(e)))
        e["guests"] = np.maximum(np.round(g), 20).astype("int64")
        return e.drop(columns="src").reset_index(drop=True)

    def total(self, sl=slice(None)):
        return sum(v[sl] for v in self.ch.values()) * self.t["ratio"][self.sh[sl]]

    def grid_hour(self):
        """True for hours with no DG supply at all (comms faults are only seen on grid)."""
        if self.code == "GGN":
            return ~self.dg15.reshape(-1, 4).any(1)
        return self.t["dgfrac"][self.sh] == 0

    def inject(self):
        e, ch, rng = self.events, self.ch, self.rng
        e = e[e.d < ND - 3]
        conf, wed = e.d[e.start_time < "12:00"].to_numpy(), e.d[e.start_time >= "12:00"].to_numpy()
        tmax = self.temp.reshape(ND, 24).max(1)
        d = np.arange(ND - 3)
        hot = d[np.isin(DMON[d], [5, 6]) & (DAYS.day_of_week[d] < 5) & (tmax[d] >= 39)]
        P = plan(rng, self.code, self.t["avg"], conf, wed, hot)
        grid = self.grid_hour()
        done = {}
        for r in P.itertuples():
            if done.get(r.type, 0) >= N_FIXED.get(r.type, RATES[self.code][r.type]):
                continue
            m0, m1 = int(r.m0), int(r.m1)
            if r.type == "METER_DATA_FAULT":                        # move forward until the whole window is on grid
                step = 15 if self.code == "GGN" else 60
                while not grid[m0 // 60:(m1 - 1) // 60 + 1].all():
                    m0, m1 = m0 + 1440 + step, m1 + 1440 + step
            a, b = m0 // 60, m1 // 60
            busy = self.win.setdefault(r.type, np.zeros(NH, bool))
            if busy[a:b].any():
                continue
            sl, h = slice(a, b), np.arange(a, b)
            kwh = 0.0
            if r.type == "AHU_SCHEDULE_OVERRIDE":
                x = ch["ahu_banquet_kw"]
                m = h[x[h] < 5]
                new = r.kw * (1 + rng.normal(0, .03, len(m)))
                kwh = float((new - x[m]).sum())
                x[m] = new
                self.cmd.append((m0, "Banquet AHU mode", 1.0, 2.0, "Banquet supervisor", "Local panel (hand mode)"))
            elif r.type == "CHILLER_ON_LOW_LOAD" and self.code == "GGN":
                m = h[(self.run[h] == 1) & (self.tr[h] < 130)]
                add = .7 * self.tr[m]
                ch["chiller_ch1_kw"][m] += add
                self.run[m] = 2
                kwh = float(add.sum())
            elif r.type == "CHILLER_ON_LOW_LOAD":
                m = h[(HOD[h] >= 22) | (HOD[h] < 8)]
                ch["chillers_kw"][m] += r.kw
                kwh = r.kw * len(m)
            elif r.type == "CHW_SETPOINT_LOWERED":
                self.sp[sl], self.sup[sl] = 5.5, self.sup[sl] - 1.5
                for c in ("chiller_ch1_kw", "chiller_ch3_kw"):
                    kwh += float(ch[c][sl].sum() * .12)
                    ch[c][sl] *= 1.12
                self.cmd.append((m0, "CHW supply setpoint", 7.0, 5.5, "Night shift engineer", "BMS workstation"))
                if rng.random() < .85:
                    self.cmd.append((m1, "CHW supply setpoint", 5.5, 7.0, "Duty engineer", "BMS workstation"))
            elif r.type == "CONTRACT_DEMAND_BREACH":
                need = max(150, CD["GGN"] * 1.03 * .975 - float(self.total(sl).max()))
                if need > 330:
                    continue
                for c, w in (("laundry_kw", .40), ("water_heating_kw", .22), ("ahu_banquet_kw", .38)):
                    ch[c][sl] += need * w
                kwh = need * 3
            elif r.type == "EV_CHARGER_FAULT":
                ch["ev_chargers_kw"][sl] += 6
                kwh = 6.0 * len(h)
            elif r.type == "KITCHEN_EXHAUST_LEFT_ON":
                x = ch["kitchen_exhaust_mua_kw"]
                m = h[HOD[h] < 6]
                new = np.maximum(x[m], r.kw * (1 + rng.normal(0, .01, len(m))))
                kwh = float((new - x[m]).sum())
                x[m] = new
            elif r.type == "LAUNDRY_PEAK_TARIFF":
                x = ch["laundry_kw"]
                x[a:a + 4] += r.kw
                x[a - 9:a - 5] = np.maximum(x[a - 9:a - 5] - r.kw, 0)
            elif r.type == "METER_DATA_FAULT":
                self.faults.append((m0, m1))
            elif r.type == "POWER_FACTOR_DROP":
                self.pf_over[sl] = .88 + rng.normal(0, .006, len(h))
            elif r.type == "SIMULTANEOUS_HEAT_COOL":
                m = h[(HOD[h] >= 8) & (HOD[h] < 20)]
                ch["ahu_heaters_kw"][m] += r.kw
                kwh = r.kw * len(m)
            elif r.type == "POOL_PUMPS_24H":
                m = h[(HOD[h] < 7) | (HOD[h] >= 17)]
                ch["pumps_pool_kw"][m] += r.kw
                kwh = r.kw * len(m)
            elif r.type == "EVENT_LIGHTING_LEFT_ON":
                ch["lighting_kw"][sl] += r.kw
                kwh = r.kw * len(h)
            if r.type not in ("LAUNDRY_PEAK_TARIFF", "METER_DATA_FAULT", "POWER_FACTOR_DROP") and kwh <= 0:
                continue
            busy[a:b] = True
            done[r.type] = done.get(r.type, 0) + 1
            self.labels.append(dict(type=r.type, m0=m0, m1=m1, kw=r.kw, kwh=kwh, kvah=None, pen=0.0))
        self.main = self.total()
        pf0 = self.pf15.reshape(-1, 4).mean(1) if self.code == "GGN" else self.t["pf"][self.sh]
        for L in self.labels:                                       # measured excess from the generated meter
            sl = slice(L["m0"] // 60, L["m1"] // 60)
            if L["type"] == "POWER_FACTOR_DROP":
                L["kvah"] = float((self.main[sl] * (1 / self.pf_over[sl] - 1 / pf0[sl])).sum())
            elif L["type"] == "METER_DATA_FAULT":
                L["kvah"] = 0.0
            else:
                L["kvah"] = L["kwh"] / .976
            if L["type"] == "CONTRACT_DEMAND_BREACH":               # kVA above contract demand at the peak 15 minutes
                L["pen"] = max(float((np.repeat(self.main[sl], 4) * self.r15[sl.start * 4:sl.stop * 4] / self.pf15[sl.start * 4:sl.stop * 4]).max()) - CD["GGN"], 0)

    # ---- tables in the data/clean schemas
    def meter_15min(self):
        pf = self.pf15.copy()
        o = np.repeat(self.pf_over, 4)
        pf[~np.isnan(o)] = o[~np.isnan(o)]
        dg = self.dg15
        kw = np.round(np.repeat(self.main, 4) * self.r15, 1)
        kwh = np.round(kw * .25, 2)
        df = pd.DataFrame(dict(timestamp=us(Q15), grid_kwh=np.where(dg, 0, kwh), grid_kvah=np.where(dg, 0, np.round(kwh / pf, 2)),
                               kw_avg=np.where(dg, 0, kw), kva_demand=np.where(dg, 0, np.round(kw / pf, 1)),
                               power_factor=np.where(dg, np.nan, np.round(pf, 3)), supply_source=np.where(dg, "DG", "GRID"),
                               dg_kwh=np.where(dg, kwh, 0)))
        df["supply_source"] = df["supply_source"].astype("str")
        for c in ("grid_kwh", "grid_kvah", "kva_demand"):
            df[f"{c}_raw"] = df[c]
        fault = np.zeros(len(df), bool)
        for m0, m1 in self.faults:                                  # billed columns freeze, kW and PF stay live
            a, b = m0 // 15, m1 // 15
            fault[a:b] = True
            for c in ("grid_kwh_raw", "grid_kvah_raw", "kva_demand_raw"):
                df.loc[a:b - 1, c] = df[c].iat[a]
        df["is_meter_fault"] = fault
        df["is_dg"] = dg
        df["total_kwh"] = df["grid_kwh"] + df["dg_kwh"]
        df["exclude_from_model"] = fault
        return df

    def meter_hourly(self):
        t, kw = self.t, self.main
        frac = t["dgfrac"][self.sh]
        pf = np.where(np.isnan(self.pf_over), t["pf"][self.sh], self.pf_over)
        gk = kw * (1 - frac)
        kvah = gk / pf
        df = pd.DataFrame(dict(timestamp=us(HOURS), grid_kwh=np.round(gk, 1), grid_kvah=np.round(kvah, 1), kw_avg=np.round(kw, 1),
                               kva_max_in_hour=np.round(kvah * t["kr"][self.sh], 1), power_factor=np.round(pf, 3),
                               dg_kwh=np.round(kw * frac, 1)))
        raw = ["grid_kwh", "grid_kvah", "kw_avg", "kva_max_in_hour", "power_factor"] if self.code == "JAI" else ["grid_kwh", "grid_kvah", "kva_max_in_hour"]
        for c in raw:
            df[f"{c}_raw"] = df[c]
        fault = np.zeros(len(df), bool)
        for m0, m1 in self.faults:
            a, b = m0 // 60, m1 // 60
            fault[a:b] = True
            for c in ("grid_kwh_raw", "grid_kvah_raw", "kva_max_in_hour_raw"):
                df.loc[a:b - 1, c] = df[c].iat[a]
        if self.code == "JAI":
            df["is_imputed"] = fault
        df["is_dg"] = df["dg_kwh"] > 0
        df["total_kwh"] = df["grid_kwh"] + df["dg_kwh"]
        df["exclude_from_model"] = fault
        return df

    def submeters(self):
        if self.code == "GGN":
            d = {"timestamp": us(HOURS)}
            for c in self.t["kw"]:
                d[c] = np.round(self.ch[c], 1)
            d["chiller_ch2_kw"] = np.zeros(NH, "int64")
            d.update(chiller_load_tr=np.round(self.tr).astype("int64"), chw_setpoint_c=np.round(self.sp, 1),
                     chw_supply_temp_c=np.round(self.sup, 1), chillers_running=self.run.astype("int64"),
                     lifts_pool_swapped_fixed=np.zeros(NH, bool))
            df = pd.DataFrame(d)
            ch = df[["chiller_ch1_kw", "chiller_ch2_kw", "chiller_ch3_kw"]].sum(axis=1)
            df["kw_per_tr"] = np.where(df.chiller_load_tr > 0, ch / df.chiller_load_tr.where(df.chiller_load_tr > 0, 1), np.nan)
            return df
        return pd.DataFrame({"site": self.code, "timestamp": us(HOURS), **{c: np.round(self.ch[c], 1) for c in self.t["kw"]},
                             "chiller_load_tr": np.round(self.tr).astype("int64")})

    def weather(self):
        rh = np.clip(np.round(self.t["rh"][self.sh] - 2.5 * self.dT + self.rng.normal(0, 2, NH)), 8, 100).astype("int64")
        return pd.DataFrame(dict(site=self.code, timestamp=us(HOURS), temp_c=np.round(self.temp, 1), rel_humidity_pct=rh, rain_mm=self.t["rain"][self.sh]))

    def occupancy(self):
        t, src, r = self.t, self.mp["src"], self.rng
        occ = np.clip(t["occ"][src] * (1 + r.normal(0, .03, ND)), .1, 1)
        sold = np.round(occ * t["rooms"]).astype("int64")
        return pd.DataFrame(dict(site=self.code, date=us(DAYS), rooms_available=np.int64(t["rooms"]), rooms_sold=sold,
                                 occupancy_pct=np.round(sold / t["rooms"], 3),
                                 guests_in_house=np.round(sold * t["gpr"][src] * (1 + r.normal(0, .03, ND))).astype("int64"),
                                 covers_served_fnb=np.round(t["covers"][src] * (1 + r.normal(0, .06, ND))).astype("int64")))

    def events_frame(self):
        e = self.events.copy()
        e.insert(0, "site", self.code)
        e.insert(1, "date", us(START + pd.to_timedelta(e.pop("d"), unit="D")))
        e["ends_after_midnight"] = e["end_time"].eq("23:59")
        return e

    def commands(self):
        rows = list(self.cmd)
        if self.code == "GGN":                                      # chiller starts/stops from the hourly sub-meter state
            hand = self.win.get("CHILLER_ON_LOW_LOAD", np.zeros(NH, bool))
            for c, p in (("chiller_ch1_kw", "CHILLER_CH1 run command"), ("chiller_ch3_kw", "CHILLER_CH3 run command")):
                on = self.ch[c] > 0
                for h in np.flatnonzero(on[1:] != on[:-1]) + 1:
                    by = "Manual (hand mode)" if hand[h] or self.rng.random() < .1 else "BMS sequence"
                    rows.append((h * 60, p, float(not on[h]), float(on[h]), by, "BMS"))
        c = pd.DataFrame(rows, columns=["m", "point", "old_value", "new_value", "changed_by", "source"])
        c.insert(0, "site", self.code)
        c.insert(1, "timestamp", us(START + pd.to_timedelta(c.pop("m"), unit="m")))
        return c


# ------------------------------------------------------------------------------------------- labels, alarms
CAUSE = {
    "AHU_SCHEDULE_OVERRIDE": lambda r: f"Banquet AHUs left in manual 'hand' mode after an event ended; ran {r.h:.0f} h with the hall empty.",
    "CHILLER_ON_LOW_LOAD": lambda r: (f"300 TR chiller CH-1 left running alongside CH-3 at under 130 TR load ({r.h:.0f} h)." if r.site == "GGN"
                                      else f"Second air-cooled chiller left running overnight at low load ({max(round(r.h / 24), 1)} nights)."),
    "CHW_SETPOINT_LOWERED": lambda r: f"Chilled-water setpoint lowered from 7.0 °C to 5.5 °C by the night shift and not reset for {r.h / 24:.0f} days.",
    "CONTRACT_DEMAND_BREACH": lambda r: "Second laundry shift and a hall pre-cool coincided with peak chiller load on a hot afternoon; demand exceeded contract demand.",
    "EV_CHARGER_FAULT": lambda r: f"EV charger stuck drawing 6 kW with no vehicle connected ({r.h / 24:.0f} days).",
    "KITCHEN_EXHAUST_LEFT_ON": lambda r: f"Kitchen exhaust and make-up air units left running after the kitchen closed ({int(np.ceil(r.h / 24))} nights).",
    "LAUNDRY_PEAK_TARIFF": lambda r: "Laundry batch run in the evening peak window.",
    "METER_DATA_FAULT": lambda r: f"Meter communication failure: billed readings repeated (flat line) for {r.h:g} h while kW and PF stayed live.",
    "POWER_FACTOR_DROP": lambda r: f"Capacitor bank step failed in the APFC panel; power factor fell to about 0.88 for {r.h / 24:.0f} days.",
    "SIMULTANEOUS_HEAT_COOL": lambda r: f"AHU electric re-heat left enabled in the daytime for {r.h / 24:.0f} days while chillers cooled the same zones.",
    "POOL_PUMPS_24H": lambda r: f"Pool filtration pumps switched to continuous running by a contractor and never returned to the 07:00–17:00 schedule ({r.h / 24:.0f} days).",
    "EVENT_LIGHTING_LEFT_ON": lambda r: f"Lawn and façade event lighting left on after a wedding until the next morning ({r.h:.0f} h).",
}


def finalize_labels(L, lab, tar):
    def first(col):                                                 # by site, falling back to the type alone
        d = {(s, t): v for t, v in lab.groupby("anomaly_type")[col].first().items() for s in SITES}
        d.update(lab.groupby(["site", "anomaly_type"])[col].first().to_dict())
        return d

    eq, sev, det = first("equipment_or_meter"), first("severity"), first("detectable_from")
    act = lab.groupby("anomaly_type")["recommended_action"].first().to_dict()
    L = L.sort_values(["m0", "site"]).reset_index(drop=True)
    L["h"] = (L.m1 - L.m0) / 60
    rate = lambda comp: L.site.map(lambda s: tar[s][comp]).to_numpy(float)
    cost = L.kvah.to_numpy() * (rate("Energy charge") + rate("Fuel surcharge adjustment (FSA)") + rate("Electricity duty"))
    ld = (L.type == "LAUNDRY_PEAK_TARIFF").to_numpy()
    cost[ld] = (4 * L.kw.to_numpy() / .976 * rate("Peak ToD surcharge"))[ld]
    cost += L.pen.to_numpy() * rate("Excess demand penalty")
    key = list(zip(L.site, L.type))
    return pd.DataFrame(dict(
        anomaly_id=[f"LV-{i + 1:04d}" for i in range(len(L))], site=L.site, anomaly_type=L.type,
        start=us(START + pd.to_timedelta(L.m0, unit="m")), end=us(START + pd.to_timedelta(L.m1, unit="m")),
        equipment_or_meter=[eq[k] for k in key], excess_kwh=np.round(L.kwh).astype("int64"), excess_kvah=np.round(L.kvah).astype("int64"),
        excess_cost_inr=np.round(cost).astype("int64"), severity=[sev[k] for k in key],
        root_cause=[CAUSE[r.type](r) for r in L.itertuples()], recommended_action=[act[t] for t in L.type],
        detectable_from=[det[k] for k in key]))


def alarm_log(win, rng):
    """BMS alarms at the original per-site counts and mix; ~26 % fall inside a labelled anomaly, as in the brief."""
    AL = [("AHU filter dirty", "—", 332, None), ("BMS controller comms fail", "—", 339, None), ("CHW supply temperature low", "< 6.0 °C", 154, ["CHW_SETPOINT_LOWERED"]),
          ("Chiller kW high", "> 160 kW", 99, ["CHILLER_ON_LOW_LOAD", "CHW_SETPOINT_LOWERED"]),
          ("Main incomer kW high", "> 760 kW", 28, ["CONTRACT_DEMAND_BREACH", "SIMULTANEOUS_HEAT_COOL", "AHU_SCHEDULE_OVERRIDE"]),
          ("Night base load high", "> 400 kW (01:00–05:00)", 70, ["CHILLER_ON_LOW_LOAD", "KITCHEN_EXHAUST_LEFT_ON", "EV_CHARGER_FAULT", "POOL_PUMPS_24H", "EVENT_LIGHTING_LEFT_ON"]),
          ("Power factor low", "< 0.95", 128, ["POWER_FACTOR_DROP"]), ("Sensor out of range", "—", 363, None), ("Supply air temperature high", "—", 316, None)]
    share = np.array([a[2] for a in AL]) / 1829
    ACT = ["Acknowledged — no action", "Checked, normal for event", "Checked, normal for weather", "Raised maintenance ticket",
           "Equipment switched off", "Setpoint reset", "Escalated to chief engineer"]
    pact = np.array([720, 254, 228, 227, 188, 107, 105]) / 1829
    parts = []
    for site in SITES:
        n = rng.poisson({"GGN": 901, "JAI": 487, "GOA": 441}[site])
        k = rng.choice(len(AL), n, p=share)
        m = rng.integers(0, ND * 1440, n)
        w = win[win.site == site]
        for j, a in enumerate(AL):
            sel = np.flatnonzero(k == j)
            if a[0] == "Night base load high":
                m[sel] = (m[sel] // 1440) * 1440 + rng.integers(60, 300, len(sel))
            ww = w[w.type.isin(a[3] or []) & (w.m1 > w.m0)]
            if len(ww):
                hit = sel[rng.random(len(sel)) < .75]
                pick = ww.iloc[rng.choice(len(ww), len(hit), p=((ww.m1 - ww.m0) / (ww.m1 - ww.m0).sum()).to_numpy())]
                m[hit] = (pick.m0.to_numpy() + rng.random(len(hit)) * (pick.m1 - pick.m0).to_numpy()).astype(int)
        cov = np.zeros(NH, bool)
        for a_, b_ in zip(w.m0[w.type != "METER_DATA_FAULT"] // 60, w.m1[w.type != "METER_DATA_FAULT"] // 60):
            cov[a_:b_] = True
        hit = cov[np.clip(m // 60, 0, NH - 1)]
        surplus = int(hit.sum() - rng.uniform(.22, .30) * n)
        cand = np.flatnonzero(hit & np.isin(k, [0, 1, 7, 8]))
        free = np.flatnonzero(~cov)
        if surplus > 0 and len(cand):
            mv = rng.choice(cand, min(surplus, len(cand)), replace=False)
            m[mv] = rng.choice(free, len(mv)) * 60 + rng.integers(0, 60, len(mv))
        val = np.round(rng.uniform(0, 100, n), 2)
        for j, (lo, hi) in {2: (5.8, 5.8), 3: (161.9, 247.5), 4: (761.3, 998), 5: (400, 497.2), 6: (.86, .90)}.items():
            val[k == j] = np.round(rng.uniform(lo, hi, (k == j).sum()), 2 if j != 2 else 1)
        raised = START + pd.to_timedelta(m, unit="m")
        ack = raised + pd.to_timedelta(np.round(rng.lognormal(np.log(67), .8, n) * 60000), unit="ms")
        act = rng.choice(len(ACT), n, p=pact)
        at = raised + pd.to_timedelta(np.round(np.maximum(rng.lognormal(np.log(8.3), .7, n) * 3.6e6, 1.4e6)), unit="ms")
        parts.append(pd.DataFrame(dict(site=site, raised_at=us(raised), alarm=np.array([a[0] for a in AL])[k], value=val,
                                       threshold=np.array([a[1] for a in AL])[k], acknowledged_at=us(ack), action_taken=np.array(ACT)[act],
                                       action_at=us(at).where(act >= 3))))
    df = pd.concat(parts, ignore_index=True).sort_values("raised_at", kind="stable").reset_index(drop=True)
    df.insert(0, "alarm_id", [f"AL-{60001 + j}" for j in range(len(df))])
    for c in ("site", "alarm", "threshold", "action_taken"):
        df[c] = df[c].astype("str")
    return df


# ---------------------------------------------------------------------------------------------------- main
def live_tariffs():
    t = pd.read_parquet(CLEAN / "tariffs.parquet")
    fixed = t.component.isin(["Contract demand", "Municipal tax"])
    t["rate"] = np.where(fixed, t.rate, np.round(t.rate * 1.03, 3))
    t["effective_from"] = us([START] * len(t))
    return t


def build_bills(meter_faults):
    """One bill per site per month, priced by src/bills.py from the meter as read (comms-fault values included)."""
    bills.CLEAN = OUT                                               # bills.py reads its tables from this folder
    rows = []
    for site in SITES:
        q = bills.meter_quantities(site, raw=True)
        cd = bills.tariff(site)["cd"]
        for mo, r in q.iterrows():
            md = float(np.round(r.recorded_md_kva))
            p = bills.price(site, r.grid_kvah, r.peak_window_kvah, r.offpeak_window_kvah, md, r.dg_kwh)
            rn = lambda x: int(np.round(x))
            rows.append(dict(site=site, billing_month=mo, grid_kwh=rn(r.grid_kwh), grid_kvah=rn(r.grid_kvah),
                             avg_power_factor=round(r.grid_kwh / r.grid_kvah, 3), recorded_md_kva=rn(md), contract_demand_kva=rn(cd),
                             billing_demand_kva=rn(p["billing_demand_kva"]), peak_window_kvah=rn(r.peak_window_kvah),
                             offpeak_window_kvah=rn(r.offpeak_window_kvah), **{k: rn(p[k]) for k in bills.LINES[:8]},
                             dg_kwh=rn(r.dg_kwh), dg_cost_inr=rn(p["dg_cost_inr"]), total_energy_cost_inr=rn(p["total_energy_cost_inr"]),
                             bill_status="Actual", is_provisional=False,
                             bill_issued=(pd.Period(mo, "M") + 1).to_timestamp() + pd.Timedelta(days=4)))
    b = pd.DataFrame(rows)
    b["bill_issued"] = us(b["bill_issued"])
    for c in ("site", "billing_month", "bill_status"):
        b[c] = b[c].astype("str")
    return b


def main():
    rng = np.random.default_rng(SEED)
    OUT.mkdir(parents=True, exist_ok=True)
    T, lab = build_templates(rng)
    S = {}
    for i, site in enumerate(SITES):
        S[site] = Site(site, make_map(np.random.default_rng([SEED, i])), T[site], np.random.default_rng([SEED, 100 + i]))
        S[site].inject()

    tar = live_tariffs()
    tables = {"meter_ggn_15min": S["GGN"].meter_15min(), "meter_jai_hourly": S["JAI"].meter_hourly(), "meter_goa_hourly": S["GOA"].meter_hourly(),
              "sub_ggn_hourly": S["GGN"].submeters(), "sub_jai_goa_hourly": pd.concat([S["JAI"].submeters(), S["GOA"].submeters()], ignore_index=True),
              "weather_hourly": pd.concat([S[s].weather() for s in SITES], ignore_index=True),
              "occupancy_daily": pd.concat([S[s].occupancy() for s in SITES], ignore_index=True),
              "events": pd.concat([S[s].events_frame() for s in SITES], ignore_index=True).sort_values(["date", "site"], kind="stable").reset_index(drop=True),
              "bms_command_log": pd.concat([S[s].commands() for s in SITES], ignore_index=True).sort_values("timestamp", kind="stable").reset_index(drop=True),
              "tariffs": tar, "equipment_register": pd.read_parquet(CLEAN / "equipment_register.parquet")}

    L = pd.concat([pd.DataFrame(s.labels).assign(site=c) for c, s in S.items()], ignore_index=True)
    trate = {s: g.set_index("component").rate.to_dict() for s, g in tar.groupby("site")}
    tables["anomaly_labels"] = finalize_labels(L, lab, trate)
    tables["bms_alarm_log"] = alarm_log(L[["site", "type", "m0", "m1"]], np.random.default_rng([SEED, 500]))

    mf = []
    for c, s in S.items():
        m = tables["meter_ggn_15min"] if c == "GGN" else tables[f"meter_{c.lower()}_hourly"]
        for m0, m1 in s.faults:
            a, b = START + pd.Timedelta(minutes=m0), START + pd.Timedelta(minutes=m1)
            w = m[(m.timestamp >= a) & (m.timestamp < b)]
            unit, step = ("intervals", "15min") if c == "GGN" else ("h", "1h")
            mf.append(dict(site=c, start=a, end=b - pd.Timedelta(step), kind="flat line",
                           detected_at=a + (pd.Timedelta("1h") if c == "GGN" else pd.Timedelta("2h")),
                           evidence=f"billed kWh frozen at {w.grid_kwh_raw.iat[0]:.2f} for {len(w)} {unit} while kW stays live (mean {w.kw_avg.mean() * 1:.0f} kW)"))
    mf = pd.DataFrame(mf)
    for c in ("start", "end", "detected_at"):
        mf[c] = us(mf[c])
    tables["meter_faults"] = mf

    for name, df in tables.items():
        df.to_parquet(OUT / f"{name}.parquet", index=False)
    tables["monthly_bills"] = build_bills(mf)
    tables["monthly_bills"].to_parquet(OUT / "monthly_bills.parquet", index=False)
    print(f"Wrote {len(tables)} tables to {OUT}")
    return tables


# -------------------------------------------------------------------------------------------------- checks
def _hourly_main(folder, site):
    if site == "GGN":
        return gurugram_hourly(pd.read_parquet(folder / "meter_ggn_15min.parquet"))
    return pd.read_parquet(folder / f"meter_{site.lower()}_hourly.parquet")


def _sub_total(folder, site):
    if site == "GGN":
        s = pd.read_parquet(folder / "sub_ggn_hourly.parquet")
    else:
        s = pd.read_parquet(folder / "sub_jai_goa_hourly.parquet").query("site == @site")
    return s.set_index("timestamp")[[c for c in s.columns if c.endswith("_kw")]].sum(axis=1)


def _ratio(folder, site):
    m = _hourly_main(folder, site).set_index("timestamp")
    r = (m.total_kwh / _sub_total(folder, site).reindex(m.index))[~m.is_dg.to_numpy() & ~m.exclude_from_model.to_numpy()]
    return r.dropna()


def report():
    out = []
    P = out.append
    P("# Live data year (synthetic) — generation report\n")
    P("Built by `tools/make_live_year.py` from data/clean/ (Oct 2025 – Sep 2026). Period 1 Oct 2026 – 30 Sep 2027, IST, start of interval. "
      "**Synthetic**; the anomaly mix comes from the full original label set, so scores on it are a robustness check, not a clean held-out test.\n")
    P("## 1. Tables: rows, date range, gaps, duplicates\n")
    P("| table | rows | from | to | duplicate keys | missing steps |")
    P("|---|---:|---|---|---:|---:|")
    spec = {"meter_ggn_15min": ("timestamp", [], "15min"), "meter_jai_hourly": ("timestamp", [], "h"), "meter_goa_hourly": ("timestamp", [], "h"),
            "sub_ggn_hourly": ("timestamp", [], "h"), "sub_jai_goa_hourly": ("timestamp", ["site"], "h"), "weather_hourly": ("timestamp", ["site"], "h"),
            "occupancy_daily": ("date", ["site"], "D"), "events": ("date", ["site", "date", "venue", "start_time"], None),
            "bms_command_log": ("timestamp", None, None), "bms_alarm_log": ("raised_at", ["alarm_id"], None), "monthly_bills": (None, ["site", "billing_month"], None),
            "tariffs": (None, ["site", "component"], None), "equipment_register": (None, ["site", "equipment_id"], None),
            "meter_faults": ("start", None, None), "anomaly_labels": ("start", ["anomaly_id"], None)}
    for name, (tc, keys, freq) in spec.items():
        d = pd.read_parquet(OUT / f"{name}.parquet")
        lo = hi = "—"
        if tc:
            lo, hi = str(d[tc].min()), str(d[tc].max())
        elif name == "monthly_bills":
            lo, hi = d.billing_month.min(), d.billing_month.max()
        k = (keys or []) + ([tc] if freq else [])
        dup = int(d.duplicated(k).sum()) if k else 0
        miss = "—"
        if freq:
            full = pd.date_range(START, START + pd.DateOffset(years=1), freq=freq, inclusive="left")
            groups = [g for _, g in d.groupby(keys)] if keys else [d]
            miss = sum(len(full.difference(pd.DatetimeIndex(g[tc]))) for g in groups)
        P(f"| {name} | {len(d):,} | {lo} | {hi} | {dup if k else '—'} | {miss} |")

    P("\n## 2. Energy and demand per site\n")
    P("| site | original kWh | live kWh | change |")
    P("|---|---:|---:|---:|")
    peaks, ok_kwh = {}, True
    for s in SITES:
        a, b = _hourly_main(CLEAN, s), _hourly_main(OUT, s)
        ch = b.total_kwh.sum() / a.total_kwh.sum() - 1
        ok_kwh &= 0.0 <= ch <= 0.04
        P(f"| {s} | {a.total_kwh.sum():,.0f} | {b.total_kwh.sum():,.0f} | {ch:+.1%} |")
        for tag, m in (("orig", a), ("live", b)):
            peaks[(s, tag)] = m.groupby(m.timestamp.dt.month).kva_max_in_hour.max()
    P("\nMonthly peak kVA (original year → live year, same calendar month):\n")
    P("| month | " + " | ".join(f"{s} orig | {s} live" for s in SITES) + " |")
    P("|---|" + "---:|" * 6)
    for mo in [10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9]:
        P(f"| {pd.Timestamp(2000, mo, 1):%b} | " + " | ".join(f"{peaks[(s, 'orig')][mo]:,.0f} | {peaks[(s, 'live')][mo]:,.0f}" for s in SITES) + " |")
    days = {}
    for tag, f in (("original", CLEAN), ("live", OUT)):
        g = pd.read_parquet(f / "meter_ggn_15min.parquet")
        dmax = g.groupby(g.timestamp.dt.date).kva_demand.max()
        days[tag] = dmax[dmax > 1000]
    P(f"\nGurugram days above 1,000 kVA: original {len(days['original'])}, live {len(days['live'])} "
      f"({', '.join(f'{d} {v:,.0f} kVA' for d, v in days['live'].items())}).\n")

    P("## 3. Sub-meters vs main meter, power factor\n")
    P("Main ÷ sum of sub-meters, hourly, grid-only hours outside meter faults. Tolerance = the original year's largest deviation.\n")
    P("| site | orig p1–p99 | orig max dev (tol.) | live p1–p99 | live max dev | ok |")
    P("|---|---|---:|---|---:|---|")
    ok_sub = True
    for s in SITES:
        a, b = _ratio(CLEAN, s), _ratio(OUT, s)
        ta, tb = (a - 1).abs().max(), (b - 1).abs().max()
        ok_sub &= tb <= ta + 1e-3
        P(f"| {s} | {a.quantile(.01):.3f}–{a.quantile(.99):.3f} | {ta:.1%} | {b.quantile(.01):.3f}–{b.quantile(.99):.3f} | {tb:.1%} | {'yes' if tb <= ta + 1e-3 else 'NO'} |")
    P("\n| site | PF min | PF max | rows outside 0.85–1.0 |")
    P("|---|---:|---:|---:|")
    ok_pf = True
    for s in SITES:
        m = pd.read_parquet(OUT / ("meter_ggn_15min.parquet" if s == "GGN" else f"meter_{s.lower()}_hourly.parquet"))
        pf = m.power_factor[~m.is_dg.to_numpy()]
        bad = int(((pf < .85) | (pf > 1.0)).sum())
        ok_pf &= bad == 0
        P(f"| {s} | {pf.min():.3f} | {pf.max():.3f} | {bad} |")

    P("\n## 4. Bills rebuild from the meter\n")
    bills.CLEAN = OUT
    b = pd.read_parquet(OUT / "monthly_bills.parquet")
    gaps = []
    for s in SITES:
        q = bills.meter_quantities(s, raw=True)
        for r in b[b.site == s].itertuples():
            x = q.loc[r.billing_month]
            p = bills.price(s, x.grid_kvah, x.peak_window_kvah, x.offpeak_window_kvah, round(x.recorded_md_kva), x.dg_kwh)  # MD billed in whole kVA
            gaps.append(abs(p["total_energy_cost_inr"] - r.total_energy_cost_inr))
    rec = bills.reconcile_all()
    ok_bill = max(gaps) <= 200 and rec.tariff_check_max_gap.max() <= 200
    P(f"{len(b)} bills ({b.groupby('site').size().to_dict()}), {b.billing_month.min()} – {b.billing_month.max()}, issued on the 5th of the next month. "
      f"Largest gap between a bill's total and the rebuild from its meter readings: ₹{max(gaps):,.0f}; largest tariff-line gap in "
      f"`bills.reconcile_all()`: ₹{rec.tariff_check_max_gap.max():,.0f}. Reconcile status: {rec.status.value_counts().to_dict()} "
      "(the Gurugram comms-fault month is billed on the frozen readings, as in the original data). "
      f"Live tariffs: every ₹ rate ×1.03, effective 1 Oct 2026.\n")
    P("| site | months | annual bill ₹ | max MD kVA | months with excess-demand penalty |")
    P("|---|---:|---:|---:|---:|")
    for s, g in b.groupby("site"):
        P(f"| {s} | {len(g)} | {g.total_energy_cost_inr.sum():,.0f} | {g.recorded_md_kva.max():,} | {(g.excess_demand_penalty_inr > 0).sum()} |")

    P("\n## 5. Injected anomalies vs original yearly rates\n")
    lab = pd.read_parquet(OUT / "anomaly_labels.parquet")
    cnt = lab.groupby(["site", "anomaly_type"]).size()
    P("| site | type | injected | original rate / yr | excess kWh | excess ₹ |")
    P("|---|---|---:|---:|---:|---:|")
    for s in SITES:
        for t, rate in RATES[s].items():
            g = lab[(lab.site == s) & (lab.anomaly_type == t)]
            P(f"| {s} | {t} | {int(cnt.get((s, t), 0))} | {rate} | {g.excess_kwh.sum():,} | {g.excess_cost_inr.sum():,} |")
    P(f"\nTotal {len(lab)} labels (original year: 111). METER_DATA_FAULT is fixed at one per site (listed in meter_faults.parquet); "
      "every other type is injected at exactly its original yearly count, at random times (fewer only where no valid slot exists). Alarms: "
      f"{len(pd.read_parquet(OUT / 'bms_alarm_log.parquet')):,} (original 1,829).\n")
    mf = pd.read_parquet(OUT / "meter_faults.parquet")
    for r in mf.itertuples():
        P(f"- Comms fault {r.site}: {r.start} – {r.end}; {r.evidence}.")
    size = sum(f.stat().st_size for f in OUT.glob("*.parquet")) / 2 ** 20
    verdict = all([ok_kwh, ok_sub, ok_pf, ok_bill])
    P(f"\n## Result\n\nAnnual kWh within +0–4 %: {'yes' if ok_kwh else 'NO'}; sub-meters within tolerance: {'yes' if ok_sub else 'NO'}; "
      f"PF in 0.85–1.0: {'yes' if ok_pf else 'NO'}; bills within ₹200: {'yes' if ok_bill else 'NO'}. "
      f"**{'ALL CHECKS PASS' if verdict else 'SOME CHECKS FAIL'}.** Files: {size:.1f} MB in data/live/.\n")
    txt = "\n".join(out)
    (OUT / "_report.md").write_text(txt, encoding="utf-8")
    print(txt)
    return verdict


if __name__ == "__main__":
    import time
    t0 = time.time()
    main()
    print(f"generated in {time.time() - t0:.0f} s\n")
    report()
