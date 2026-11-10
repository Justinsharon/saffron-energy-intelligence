"""Engineer-trust test: a fixed set of 20 alerts to rate, and storage that survives app restarts.

Why a fixed set: the brief's metric is "2 engineers rate 20 alerts, mean ≥ 4/5", so every rater must see the same 20.
The set is chosen by rule, not by hand: held-out period only (start ≥ 1 Apr 2026), one alert per hotel × waste type
(the largest ₹ of each, so every kind of alert is judged), then the next largest ₹ until there are 20.

Storage: Streamlit Cloud's disk is wiped on restart, so ratings go to a private GitHub Gist when the secrets
GITHUB_TOKEN (gist scope) and RATINGS_GIST_ID are set; otherwise to data/feedback/ratings.csv (fine locally).
"""
import io
import json
import os
import urllib.request

import pandas as pd

from features import CLEAN

APP = CLEAN.parent / "app"
LOCAL = CLEAN.parent / "feedback" / "ratings.csv"
GIST_FILE = "ratings.csv"
COLUMNS = ["time", "rater", "role", "alert_id", "usefulness", "would_act", "cause_right", "comment", "round"]
ROUND = 2          # card wording version: 1 = before the 10 Nov dry-run fixes (no "round" column saved), 2 = after


def rating_set(n: int = 20) -> pd.DataFrame:
    c = pd.read_parquet(APP / "cards.parquet")
    h = c[c.start >= "2026-04-01"].sort_values("cost_inr", ascending=False)
    first = h.groupby(["site", "rule"], sort=False).head(1)
    rest = h.drop(first.index).head(max(0, n - len(first)))
    return pd.concat([first, rest]).head(n).sort_values("start").reset_index(drop=True)


def _secret(name):
    try:
        import streamlit as st
        return st.secrets[name]
    except Exception:
        return os.environ.get(name)


def _gist():
    tok, gid = _secret("GITHUB_TOKEN"), _secret("RATINGS_GIST_ID")
    return (tok, gid) if tok and gid else None


def _api(method, gid, tok, body=None):
    req = urllib.request.Request(f"https://api.github.com/gists/{gid}", method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def storage() -> str:
    return "GitHub Gist (persistent)" if _gist() else "local file (lost when the hosted app restarts)"


def load() -> pd.DataFrame:
    g = _gist()
    if g:
        files = _api("GET", g[1], g[0])["files"]
        txt = files.get(GIST_FILE, {}).get("content", "")
        return pd.read_csv(io.StringIO(txt)) if txt.strip() else pd.DataFrame(columns=COLUMNS)
    return pd.read_csv(LOCAL) if LOCAL.exists() else pd.DataFrame(columns=COLUMNS)


def save(row: dict) -> None:
    row = {**row, "round": ROUND}
    df = pd.concat([load(), pd.DataFrame([row])[COLUMNS]], ignore_index=True)
    g = _gist()
    if g:
        _api("PATCH", g[1], g[0], {"files": {GIST_FILE: {"content": df.to_csv(index=False)}}})
    else:
        LOCAL.parent.mkdir(exist_ok=True)
        df.to_csv(LOCAL, index=False)


def rounds(df: pd.DataFrame) -> pd.Series:
    """Card version of each rating; rows saved before the column existed are round 1."""
    if "round" not in df:
        return pd.Series(1, index=df.index)
    return pd.to_numeric(df["round"], errors="coerce").fillna(1).astype(int)


def summary(df: pd.DataFrame) -> dict:
    if df.empty:
        return dict(n=0)
    df = df.copy()
    df["round"] = rounds(df)
    by_round = (df.sort_values("time").groupby(["round", "rater", "alert_id"]).tail(1)
                .groupby("round").agg(ratings=("usefulness", "size"), mean=("usefulness", "mean"),
                                      would_act=("would_act", lambda s: (s == "Yes").mean() * 100)))
    df = df[df["round"] == df["round"].max()]                                # headline = latest card version
    last = df.sort_values("time").groupby(["rater", "alert_id"]).tail(1)      # a re-rating replaces the earlier one
    by = last.groupby("rater").agg(rated=("alert_id", "nunique"), mean=("usefulness", "mean"),
                                   would_act=("would_act", lambda s: (s == "Yes").mean() * 100))
    return dict(n=len(last), raters=by, mean=float(last.usefulness.mean()),
                would_act=float((last.would_act == "Yes").mean() * 100), cause_right=float((last.cause_right == "Yes").mean() * 100),
                per_alert=last.groupby("alert_id").usefulness.mean(), by_round=by_round, round=int(df["round"].max()))
