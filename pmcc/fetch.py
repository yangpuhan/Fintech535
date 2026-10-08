"""
Pull the daily tape the PMCC book trades on.

    python -m pmcc.fetch

Needs LSEG Workspace running and an app key in lseg-data.config.json
(gitignored). Run once; everything downstream reads data.pkl.

Why daily, when 1.2 was hourly
------------------------------
Hourly option history on LSEG goes back about one year — a probe on
7 Oct 2026 found the first hourly bar of a Jan-2026 contract on 7 Oct 2025
and nothing before it. Daily history on the expired-RIC space goes back to
2021. A strategy whose long leg lives for a year and whose short leg turns
over monthly needs years, not weeks, and one year of hourly bars would be
one regime. So: daily closes, 3 Jan 2022 to 7 Oct 2026 — a bear market
(2022), two rallies (2023-24), a crash (April 2025) and the recovery.

The cost of daily bars is the timestamp. Every quote here is the closing
NBBO, so the book cannot decide and fill on the same print. book.py handles
that with a one-session lag: decide on yesterday's close, fill on today's.

What gets pulled
----------------
SHORT LEG  every standard monthly AAPL call from Feb 2022 to Oct 2026, on
           the listed $2.50 grid, banded per expiry off the stock's own
           range in the weeks a call on that expiry could be sold.
LONG LEG   every January LEAPS from Jan 2023 to Jan 2028, on the $5 grid,
           banded off the stock's range around the day it would be bought.
STOCK      AAPL.O daily.
RATE       US3MT=RR, the 3-month T-bill yield: the discount rate for the
           Black-Scholes delta and the interest idle cash earns.
EVENTS     dividends (ex-date, pay-date, amount) and earnings report dates.

Bands are wider than the headline rule needs (0.30 / 0.80 delta) so the
sensitivity grid in book.py (0.20-0.40 short, 0.70-0.90 long) runs off the
same pull.

A constructed RIC may name a contract that never listed. On the hourly
endpoint (1.2) one bad name took the whole batch down; the daily endpoint
drops it silently and returns the rest — probed with a batch of 18500 /
18600 / 19000, where 186 is not a listed strike. The bisect from 1.2 stays,
for a batch that fails outright, and the per-expiry resolved count is kept
so a silent drop is still visible.
"""

from __future__ import annotations

import calendar
import datetime as dt
import pickle
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from covered_call.ric import build_option_ric

warnings.filterwarnings("ignore")

TICKER = "AAPL"
STOCK_RIC = "AAPL.O"
RATE_RIC = "US3MT=RR"

# The backtest window. START is the first session of 2022; END is the last
# complete session before the pull (it ran during the 8 Oct 2026 session).
START = dt.date(2022, 1, 3)
END = dt.date(2026, 10, 7)
# Contracts expiring on or after this date are still listed and use the live
# RIC, with no ^ suffix.
PULL_DATE = dt.date(2026, 10, 8)

# Short leg: the first monthly with >= MIN_SHORT_DTE days left. A call on
# expiry E can therefore be opened anywhere from ~E-56d (the session after
# the previous monthly) to E-21d.
MIN_SHORT_DTE = 21
SHORT_OPEN_WINDOW = (60, MIN_SHORT_DTE)   # days before expiry
SHORT_STEP = 2.50
SHORT_BAND = (0.97, 1.25)                 # x min / x max spot in that window

# Long leg: nearest January with >= 300 DTE, rolled at <= 120 DTE.
MIN_LONG_DTE = 300
ROLL_LONG_DTE = 120
LONG_STEP = 5.0
LONG_BAND = (0.45, 1.02)

OPTION_FIELDS = ["BID", "ASK", "MID_PRICE", "TRDPRC_1", "ACVOL_UNS",
                 "OPINT_1", "IMP_VOLT", "DELTA"]
STOCK_FIELDS = ["OPEN_PRC", "HIGH_1", "LOW_1", "TRDPRC_1", "BID", "ASK",
                "ACVOL_UNS"]

DATA_FILE = Path(__file__).with_name("data.pkl")


# ── the calendar ─────────────────────────────────────────────────────────

def third_friday(year: int, month: int) -> dt.date:
    weeks = calendar.Calendar(calendar.MONDAY).monthdatescalendar(year, month)
    fridays = [d for w in weeks for d in w if d.weekday() == 4 and d.month == month]
    return fridays[2]


def monthly_expiries(sessions: list[dt.date], first: dt.date,
                     last: dt.date) -> list[dt.date]:
    """
    Standard monthly expiries, read off the tape rather than a holiday table.

    The third Friday, or the last session before it when the exchange is
    shut — 14 Apr 2022 and 17 Apr 2025 (Good Friday), 18 Jun 2026
    (Juneteenth). Probed: AAPLD172520000.U^D25 resolves, ...D1825... does
    not, so the RIC carries the Thursday. Expiries after the last session on
    the tape keep their Friday; none of those is a holiday.
    """
    have = set(sessions)
    out = []
    y, m = first.year, first.month
    while (y, m) <= (last.year, last.month):
        f = third_friday(y, m)
        if f > sessions[-1]:
            out.append(f)
        elif f in have:
            out.append(f)
        else:
            out.append(max(s for s in sessions if s < f))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return [e for e in out if first <= e <= last]


def january_expiry(year: int, sessions: list[dt.date]) -> dt.date:
    return monthly_expiries(sessions, dt.date(year, 1, 1), dt.date(year, 1, 31))[0]


def long_schedule(sessions: list[dt.date]) -> list[dict]:
    """
    Which January LEAPS is held when. Deterministic — it depends only on the
    calendar, never on prices — so it can be fixed before the pull.
    """
    out = []
    day = START
    while day <= END:
        year = day.year + 1
        while (january_expiry(year, sessions) - day).days < MIN_LONG_DTE:
            year += 1
        exp = january_expiry(year, sessions)
        exit_ = exp - dt.timedelta(days=ROLL_LONG_DTE)
        out.append({"expiry": exp, "enter": day, "exit": min(exit_, END)})
        day = exit_
    return out


# ── the pull ─────────────────────────────────────────────────────────────

def option_ric(expiry: dt.date, strike: float) -> str:
    ric = build_option_ric(TICKER, expiry, strike, "C")
    return ric if expiry < PULL_DATE else ric.split("^")[0]


def _band(stock: pd.Series, lo_day: dt.date, hi_day: dt.date,
          mult: tuple[float, float], step: float) -> list[float]:
    px = stock[(stock.index.date >= lo_day) & (stock.index.date <= hi_day)].dropna()
    if px.empty:
        px = stock[stock.index.date <= hi_day].dropna().iloc[-5:]
    lo = np.floor(px.min() * mult[0] / step) * step
    hi = np.ceil(px.max() * mult[1] / step) * step
    return [round(k, 2) for k in np.arange(lo, hi + step / 2, step)]


def _long(df: pd.DataFrame) -> pd.DataFrame:
    """Wide (ric, field) frame -> tidy rows of (date, ric, fields...)."""
    if not isinstance(df.columns, pd.MultiIndex):
        raise ValueError("expected (ric, field) columns")
    df = df.copy()
    df.index = pd.DatetimeIndex(df.index).normalize()
    out = df.stack(level=0, future_stack=True)
    out.index.names = ["date", "ric"]
    out = out.reset_index()
    fields = [c for c in OPTION_FIELDS if c in out.columns]
    out[fields] = out[fields].apply(pd.to_numeric, errors="coerce")
    return out.dropna(subset=fields, how="all")


def _get(ld, universe: list[str], start: str, end: str) -> pd.DataFrame | None:
    df = ld.get_history(universe=universe, fields=OPTION_FIELDS,
                        start=start, end=end, interval="1D")
    if df is None or df.empty:
        return None
    if not isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = pd.MultiIndex.from_product([[universe[0]], df.columns])
    return _long(df)


def _pull(ld, universe: list[str], start: str, end: str, out: list) -> None:
    """Batch, and bisect on failure so one dead RIC costs log2(n), not n."""
    if not universe:
        return
    try:
        df = _get(ld, universe, start, end)
    except Exception:
        if len(universe) == 1:
            return
        half = len(universe) // 2
        _pull(ld, universe[:half], start, end, out)
        _pull(ld, universe[half:], start, end, out)
        return
    if df is not None and not df.empty:
        out.append(df)


def _pull_chain(ld, rics: list[str], start: dt.date, end: dt.date,
                batch: int) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    # LSEG's daily `start` is exclusive; pad it so the first session lands
    s, e = (start - dt.timedelta(days=3)).isoformat(), end.isoformat()
    for i in range(0, len(rics), batch):
        _pull(ld, rics[i:i + batch], s, e, frames)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def fetch(verbose: bool = True) -> dict:
    import lseg.data as ld

    ld.open_session()
    try:
        pad = START - dt.timedelta(days=40)
        stock = ld.get_history(universe=[STOCK_RIC], fields=STOCK_FIELDS,
                               start=pad.isoformat(), end=END.isoformat(),
                               interval="1D")
        stock.index = pd.DatetimeIndex(stock.index).normalize()
        stock = stock.apply(pd.to_numeric, errors="coerce").sort_index()
        sessions = sorted({t.date() for t in stock.index})
        px = stock["TRDPRC_1"]
        if verbose:
            print(f"stock: {len(stock)} sessions {sessions[0]} -> {sessions[-1]}")

        rate = ld.get_history(universe=[RATE_RIC], fields=["MID_YLD_1", "B_YLD_1"],
                              start=pad.isoformat(), end=END.isoformat(),
                              interval="1D")
        rate.index = pd.DatetimeIndex(rate.index).normalize()
        rate = rate.apply(pd.to_numeric, errors="coerce").sort_index()

        div = ld.get_data(STOCK_RIC, ["TR.DivExDate", "TR.DivPayDate",
                                      "TR.DivUnadjustedGross"],
                          {"SDate": "2020-01-01", "EDate": "2026-12-31"})
        div.columns = ["ric", "ex_date", "pay_date", "amount"]
        div = div.dropna(subset=["ex_date"])[["ex_date", "pay_date", "amount"]]
        eps = ld.get_data(STOCK_RIC, ["TR.EPSActReportDate"],
                          {"SDate": "2021-10-01", "EDate": END.isoformat(),
                           "Period": "FQ0", "Frq": "FQ"})
        eps.columns = ["ric", "report"]
        earnings = sorted({pd.Timestamp(t) for t in eps["report"].dropna()})

        # ── short leg: every monthly, banded ───────────────────────────
        expiries = monthly_expiries(sessions, START + dt.timedelta(days=MIN_SHORT_DTE),
                                    END + dt.timedelta(days=60))
        shorts, chain = [], []
        for e in expiries:
            lo_day = e - dt.timedelta(days=SHORT_OPEN_WINDOW[0])
            hi_day = min(e - dt.timedelta(days=SHORT_OPEN_WINDOW[1]), END)
            if lo_day > END:
                continue
            strikes = _band(px, lo_day, hi_day, SHORT_BAND, SHORT_STEP)
            rics = [option_ric(e, k) for k in strikes]
            got = _pull_chain(ld, rics, max(lo_day, pad), min(e, END), batch=25)
            n = got["ric"].nunique() if not got.empty else 0
            chain.append({"leg": "short", "expiry": e, "requested": len(rics),
                          "resolved": n, "lo": strikes[0], "hi": strikes[-1]})
            if not got.empty:
                shorts.append(got)
            if verbose:
                print(f"  short {e}  {strikes[0]:.2f}-{strikes[-1]:.2f}  "
                      f"{n}/{len(rics)}", flush=True)

        # ── long leg: each January LEAPS over its holding window ───────
        longs = []
        sched = long_schedule(sessions)
        for leg in sched:
            strikes = _band(px, leg["enter"] - dt.timedelta(days=7),
                            leg["enter"] + dt.timedelta(days=21),
                            LONG_BAND, LONG_STEP)
            rics = [option_ric(leg["expiry"], k) for k in strikes]
            got = _pull_chain(ld, rics, leg["enter"] - dt.timedelta(days=10),
                              min(leg["exit"] + dt.timedelta(days=10), END),
                              batch=8)
            n = got["ric"].nunique() if not got.empty else 0
            chain.append({"leg": "long", "expiry": leg["expiry"],
                          "requested": len(rics), "resolved": n,
                          "lo": strikes[0], "hi": strikes[-1]})
            if not got.empty:
                longs.append(got)
            if verbose:
                print(f"  long  {leg['expiry']}  held {leg['enter']} -> {leg['exit']}  "
                      f"{strikes[0]:.0f}-{strikes[-1]:.0f}  {n}/{len(rics)}", flush=True)
    finally:
        ld.close_session()

    options = pd.concat(shorts + longs, ignore_index=True)
    # a LEAPS strike can turn up in both pulls only if a January monthly is
    # also the LEAPS; keep one row per (date, ric)
    options = options.drop_duplicates(subset=["date", "ric"]).sort_values(["date", "ric"])

    return {
        "stock": stock,
        "rate": rate,
        "dividends": div.reset_index(drop=True),
        "earnings": earnings,
        "options": options.reset_index(drop=True),
        "ticker": TICKER,
        "stock_ric": STOCK_RIC,
        "rate_ric": RATE_RIC,
        "start": START,
        "end": END,
        "monthly_expiries": expiries,
        "long_schedule": sched,
        "chain": chain,
        "option_fields": OPTION_FIELDS,
        "fetched_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "synthetic": False,
    }


def main() -> Path:
    payload = fetch()
    with DATA_FILE.open("wb") as f:
        pickle.dump(payload, f)
    o = payload["options"]
    print(f"\nwrote {DATA_FILE}  ({DATA_FILE.stat().st_size / 1e6:.1f} MB)")
    print(f"  stock    {payload['stock'].shape}")
    print(f"  options  {len(o):,} rows, {o['ric'].nunique():,} contracts")
    print(f"  dividends {len(payload['dividends'])}, earnings {len(payload['earnings'])}")
    return DATA_FILE


if __name__ == "__main__":
    main()
