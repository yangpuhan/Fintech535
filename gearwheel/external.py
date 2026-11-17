"""
Signals from outside the stock and outside the course: market stress and
volatility sizing. Shared by the lab (gearwheel/lab2.py) and the nightly
orders, so the rule tested is the rule traded.

Sources (free, no key; a snapshot sits in gearwheel/ext/ so the backtest is
reproducible, and the nightly run fetches fresh copies):

    CBOE   VIX_History.csv, VIX3M_History.csv    daily closes since 1990 / 2009
    FRED   BAA10Y                                Moody's Baa yield less the
                                                 10-year Treasury, daily

(The LSEG account is not permissioned for CBOE indices, and FRED now serves
only three years of the ICE high-yield spread, so neither could be used.)

Signals, each decided on a session's close with what was published by then:

    vix     VIX close > VIX3M close: the term structure is inverted, the
            market is paying more for one month of protection than for
            three. That happens in stress, and short puts sold into it are
            the ones that get run over.
    credit  BAA10Y above its own 200-observation average, using the value
            published before the session (FRED posts a day late): credit
            is getting worse.
    size    min(1, median 21-day vol over the past 252 sessions / today's
            21-day vol): sell fewer puts when the stock is unusually
            volatile (Moreira & Muir 2017, volatility-managed portfolios).

No threshold here was tuned: 1.0 is where the curve inverts, 200 is the
same average as everywhere else on this site, and the vol median is the one
gearwheel/signals.py already uses.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd

from .signals import gears

EXT = Path(__file__).resolve().parent / "ext"
URLS = {
    "VIX": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
    "VIX3M": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX3M_History.csv",
    "BAA10Y": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAA10Y&cosd=2019-01-01",
}
CREDIT_MA = 200


def _parse(name: str, text: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(text))
    df.columns = [c.strip() for c in df.columns]
    col = "CLOSE" if "CLOSE" in df.columns else df.columns[-1]
    s = pd.Series(pd.to_numeric(df[col], errors="coerce").to_numpy(),
                  index=pd.to_datetime(df[df.columns[0]]).dt.normalize(), name=name)
    return s.dropna().sort_index()


def fetch(names=None, save: bool = False, tries: int = 3) -> dict[str, pd.Series]:
    """Fresh copies. FRED times out now and then, so each series gets a few
    tries with a pause between; a series that never arrives raises."""
    import time
    import urllib.request
    out = {}
    for name in (names or URLS):
        url = URLS[name]
        for i in range(tries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research script)"})
                with urllib.request.urlopen(req, timeout=45) as r:
                    text = r.read().decode("utf-8")
                break
            except Exception:
                if i == tries - 1:
                    raise
                time.sleep(10 * (i + 1))
        out[name] = _parse(name, text)
        if save:
            EXT.mkdir(exist_ok=True)
            (EXT / f"{name}.csv").write_text(text)
    return out


def credit_now(baa: pd.Series, decided) -> dict:
    """The credit signal as the backtest sees it on the decided close: the
    latest observation dated before that session, against the average of the
    200 observations up to it."""
    known = baa[baa.index < pd.Timestamp(decided)].dropna()
    if len(known) < CREDIT_MA:
        return {"stress": None, "baa": None, "baa_ma": None, "asof": None}
    ma = float(known.tail(CREDIT_MA).mean())
    last = float(known.iloc[-1])
    return {"stress": bool(last > ma), "baa": round(last, 3), "baa_ma": round(ma, 3),
            "asof": str(known.index[-1].date())}


def snapshot() -> dict[str, pd.Series]:
    return {name: _parse(name, (EXT / f"{name}.csv").read_text()) for name in URLS}


def stress(series: dict[str, pd.Series]) -> pd.DataFrame:
    """Per calendar day with data: vix inverted, credit worsening (both bools)."""
    vix, v3m, baa = series["VIX"], series["VIX3M"], series["BAA10Y"]
    ratio = (vix / v3m).dropna()
    # FRED posts BAA10Y the next morning: on a session's close, yesterday's is the latest
    baa_known = baa.shift(1)
    baa_ma = baa_known.rolling(CREDIT_MA, min_periods=CREDIT_MA).mean()
    credit = (baa_known > baa_ma) & baa_ma.notna()
    out = pd.DataFrame({"vix_ratio": ratio, "vix": ratio > 1.0})
    out = out.join(pd.DataFrame({"baa": baa_known, "baa_ma": baa_ma, "credit": credit}), how="outer")
    out[["vix", "credit"]] = out[["vix", "credit"]].astype("boolean").ffill().fillna(False).astype(bool)
    return out


def pause_map(series: dict[str, pd.Series], sessions, use_vix: bool, use_credit: bool) -> dict:
    """{session: True} where any chosen signal says stress, as of that close."""
    st = stress(series)
    st = st[~st.index.duplicated(keep="last")].sort_index()
    out = {}
    for d in sessions:
        row = st.loc[:pd.Timestamp(d)].tail(1)
        if row.empty:
            continue
        hit = (use_vix and bool(row["vix"].iloc[0])) or (use_credit and bool(row["credit"].iloc[0]))
        if hit:
            out[d] = True
    return out


def size_map(close: pd.Series) -> dict:
    """{session: scale in (0, 1]} from the stock's own vol against its 1-year median."""
    g = gears(close)
    scale = (g["rv_median"] / g["rv"]).clip(upper=1.0)
    return {t.date(): float(v) for t, v in scale.items() if np.isfinite(v)}
