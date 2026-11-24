"""
The rule, in one place, for the backtest on the page and the nightly tracker.

    universe   the 20 largest S&P 500 companies by market cap on the first
               session of each year (one share class per company)
    implied    at the last close before the report, the at-the-money call plus
               put on the first weekly expiring after the reaction day, at the
               mid, divided by the share price: the move the options priced
    reaction   the first session that trades on the news (the next day for a
               report after the close, the same day for one before the open)
    signal     |close-to-close move into the reaction day| > implied
    trade      the next open, in the direction of the move; an equal and
               opposite SPY position beside it; out at the open 20 sessions on
    size       25% of equity a position; above four open, all scale down so
               the stock side never exceeds equity. Idle cash sits in a
               T-bill ETF, modelled at the 3-month T-bill rate
    costs      5 bp a side on the stock and on SPY: 20 bp a round trip
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(__file__).resolve().parent / "data"
OUT = ROOT / "docs" / "drift" / "tracker.json"

HOLD = 20            # sessions
SIZE = 0.25          # of equity, per position
COST = 10e-4         # charged on entry and on exit (stock + SPY, 5 bp each)
PAUSE_N = 20         # trades in the short window
LONG_DAYS = 730      # the long window, in calendar days
LOW_SURPRISE = 0.20  # share of reports beating the implied move


def tick(ric: str) -> str:
    t = ric.split(".")[0].upper()
    return {"GOOG": "GOOGL"}.get(t, t)


# ---------------------------------------------------------------- data

def load():
    u = json.load(open(DATA / "universe.json"))
    ev = pd.read_csv(DATA / "events.csv", parse_dates=["t0", "t1"])
    bars = pd.read_csv(DATA / "bars.csv.gz", parse_dates=["date"])
    rate = pd.read_csv(DATA / "rate.csv", parse_dates=["date"]).set_index("date")["yield"]
    return u, ev, bars, rate


def panel(bars: pd.DataFrame, field: str) -> pd.DataFrame:
    return bars.pivot_table(index="date", columns="name", values=field).sort_index()


# ---------------------------------------------------------------- trades

def trades(ev: pd.DataFrame, O: pd.DataFrame, Cl: pd.DataFrame, surprise: bool = True) -> list[dict]:
    """Every signal (or, with surprise=False, every non-signal report followed
    the same way, the control) as a daily path of hedged returns."""
    spy_o, spy_c = O["SPY"], Cl["SPY"]
    sess = Cl.index
    out = []
    for r in ev.itertuples():
        is_sig = abs(r.move) > r.implied
        if is_sig != surprise or r.name not in Cl.columns:
            continue
        d = 1 if r.move > 0 else -1
        after = sess[sess > r.t1]
        if not len(after):
            continue
        days = after[: HOLD + 1]
        path = {}
        for j, t in enumerate(days):
            p = sess[sess.get_loc(t) - 1]
            if j == 0:
                s, m = Cl.at[t, r.name] / O.at[t, r.name] - 1, spy_c[t] / spy_o[t] - 1
            elif j < HOLD:
                s, m = Cl.at[t, r.name] / Cl.at[p, r.name] - 1, spy_c[t] / spy_c[p] - 1
            else:
                s, m = O.at[t, r.name] / Cl.at[p, r.name] - 1, spy_o[t] / spy_c[p] - 1
            path[t] = d * (s - m)
        closed = len(days) == HOLD + 1
        path[days[0]] -= COST
        if closed:
            path[days[-1]] -= COST
        ser = pd.Series(path)
        out.append(dict(name=r.name, t1=r.t1, dir=d, implied=r.implied, move=r.move,
                        entry=days[0], exit=days[-1] if closed else None, closed=closed,
                        ret=float((1 + ser).prod() - 1), path=ser))
    return out


def portfolio(tr: list[dict], cal: pd.DatetimeIndex) -> pd.Series:
    """Daily excess return over cash of the book: SIZE each, scaled above 4."""
    if not tr:
        return pd.Series(0.0, index=cal)
    M = pd.concat([t["path"] for t in tr], axis=1).reindex(cal)
    n = M.notna().sum(axis=1)
    return (M.fillna(0) * SIZE).sum(axis=1) / np.maximum(1, n * SIZE)


def tbill_daily(rate: pd.Series, cal: pd.DatetimeIndex) -> pd.Series:
    r = rate.reindex(cal).ffill().bfill() / 100
    days = pd.Series(cal, index=cal).diff().dt.days.fillna(0)
    return (r.shift(1).bfill() * days / 360).fillna(0)


def stats(q: pd.Series, rf: pd.Series) -> dict:
    eq = (1 + q).cumprod()
    yrs = (q.index[-1] - q.index[0]).days / 365.25
    ex = q - rf
    by = q.groupby(q.index.year).apply(lambda z: (1 + z).prod() - 1)
    return {"cagr": round((eq.iloc[-1] ** (1 / yrs) - 1) * 100, 1),
            "vol": round(q.std() * np.sqrt(252) * 100, 1),
            "sharpe": round(ex.mean() / ex.std() * np.sqrt(252), 2) if ex.std() > 0 else None,
            "max_dd": round((eq / eq.cummax() - 1).min() * 100, 1),
            "years": {str(y): round(v * 100, 1) for y, v in by.items()}}


# ---------------------------------------------------------------- status

def status(tr: list[dict], ev: pd.DataFrame, today: pd.Timestamp) -> dict:
    closed = sorted([t for t in tr if t["closed"]], key=lambda t: t["exit"])
    last20 = [t["ret"] for t in closed[-PAUSE_N:]]
    recent = [t["ret"] for t in closed if (today - t["exit"]).days <= LONG_DAYS]
    q = ev.assign(season=ev.t1.dt.to_period("Q"), sur=ev.move.abs() > ev.implied)
    seasons = q.groupby("season").agg(n=("sur", "size"), rate=("sur", "mean"))
    done = seasons[(seasons.index < today.to_period("Q")) & (seasons.n >= 10)].tail(2)
    s1 = float(np.mean(last20) * 100) if last20 else None
    s2 = float(np.mean(recent) * 100) if recent else None
    return {
        "short": {"value": s1, "n": len(last20), "rule": f"average of the last {PAUSE_N} closed trades < 0: no new trades",
                  "tripped": s1 is not None and s1 < 0},
        "long": {"value": s2, "n": len(recent), "rule": "average of the trades closed in the last two years < 0: the thesis is wrong",
                 "tripped": s2 is not None and s2 < 0},
        "surprise": {"value": [round(float(x) * 100, 1) for x in done["rate"]], "seasons": [str(p) for p in done.index],
                     "rule": f"fewer than {LOW_SURPRISE:.0%} of reports beat the implied move in two straight seasons: the options caught up",
                     "tripped": len(done) == 2 and bool((done["rate"] < LOW_SURPRISE).all())},
    }


def rolling(tr: list[dict]) -> dict:
    closed = sorted([t for t in tr if t["closed"]], key=lambda t: t["exit"])
    if len(closed) < PAUSE_N:
        return {"dates": [], "avg": []}
    r = pd.Series([t["ret"] for t in closed], index=[t["exit"] for t in closed]).rolling(PAUSE_N).mean().dropna()
    return {"dates": [str(d.date()) for d in r.index], "avg": [round(v * 100, 3) for v in r]}


def cumulative(tr: list[dict]) -> dict:
    """Sum of trade returns in order of entry: what following every signal earned."""
    tr = sorted(tr, key=lambda t: t["entry"])
    c = np.cumsum([t["ret"] * 100 for t in tr])
    return {"dates": [str(t["entry"].date()) for t in tr], "cum": [round(float(x), 3) for x in c],
            "name": [t["name"] for t in tr]}


def build_json(u, ev, bars, rate, generated: str, note: str = "") -> dict:
    O, Cl = panel(bars, "open"), panel(bars, "close")
    sig, ctl = trades(ev, O, Cl, True), trades(ev, O, Cl, False)
    cal = Cl.loc["2022-01-03":].index
    rf = tbill_daily(rate, cal)
    book = portfolio(sig, cal) + rf
    spy = Cl["SPY"].reindex(cal).pct_change().fillna(0)
    today = Cl.index[-1]
    st = status(sig, ev, today)
    open_tr = [t for t in sig if not t["closed"]]
    last = sorted(sig, key=lambda t: t["entry"])[-12:]
    eq = (1 + book).cumprod()
    return {
        "generated_utc": generated, "through": str(today.date()), "note": note,
        "spec": {"hold": HOLD, "size": SIZE, "cost_bp_round_trip": COST * 2e4},
        "universe": {y: [tick(r) for r in rics] for y, rics in u["top20"].items()},
        "counts": {"reports": int(len(ev)), "signals": len(sig), "closed": sum(t["closed"] for t in sig),
                   "per_year": round(len(sig) / ((today - pd.Timestamp("2022-01-03")).days / 365.25), 1),
                   "surprise_rate": round(float((ev.move.abs() > ev.implied).mean()) * 100, 1)},
        "trade": {"mean": round(float(np.mean([t["ret"] for t in sig if t["closed"]])) * 100, 2),
                  "median": round(float(np.median([t["ret"] for t in sig if t["closed"]])) * 100, 2),
                  "win": round(float(np.mean([t["ret"] > 0 for t in sig if t["closed"]])) * 100, 0),
                  "control_mean": round(float(np.mean([t["ret"] for t in ctl if t["closed"]])) * 100, 2),
                  "t": round(float(np.mean([t["ret"] for t in sig if t["closed"]]) /
                                   np.std([t["ret"] for t in sig if t["closed"]], ddof=1) *
                                   np.sqrt(sum(t["closed"] for t in sig))), 2)},
        "backtest": {"strategy": stats(book, rf), "spy": stats(spy, rf), "tbills": stats(rf, rf),
                     "equity": {"dates": [str(d.date()) for d in eq.index[::2]], "strategy": [round(float(x), 4) for x in eq.iloc[::2]],
                                "spy": [round(float(x), 4) for x in (1 + spy).cumprod().iloc[::2]]}},
        "tracker": {"signals": cumulative(sig), "control": cumulative(ctl), "rolling": rolling(sig)},
        "status": st,
        "open": [{"name": t["name"], "dir": "long" if t["dir"] > 0 else "short", "entry": str(t["entry"].date()),
                  "ret": round(t["ret"] * 100, 2), "implied": round(t["implied"], 1), "move": round(t["move"], 1)} for t in open_tr],
        "recent": [{"name": t["name"], "dir": "long" if t["dir"] > 0 else "short", "reaction": str(t["t1"].date()),
                    "implied": round(t["implied"], 1), "move": round(t["move"], 1), "entry": str(t["entry"].date()),
                    "exit": str(t["exit"].date()) if t["exit"] is not None else None, "closed": t["closed"],
                    "ret": round(t["ret"] * 100, 2)} for t in reversed(last)],
        "latest_reports": [{"name": r.name, "reaction": str(r.t1.date()), "implied": round(r.implied, 1), "move": round(r.move, 1),
                            "signal": bool(abs(r.move) > r.implied)} for r in ev.sort_values("t1").tail(10).itertuples()][::-1],
    }
