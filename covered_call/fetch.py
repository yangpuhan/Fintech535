"""
Pull the hourly tape the covered-call book trades on.

    python -m covered_call.fetch

Needs LSEG Workspace running and an app key in lseg-data.config.json
(gitignored). Run once; everything downstream reads data.pkl.

What gets pulled, and why that and not more
-------------------------------------------
Same bar size for stock and options — hourly — so the combo is priced at one
timestamp. The book only ever acts at one bar a day (ORDER_HOUR_UTC), but the
whole week is pulled anyway: the mid-vs-print regression needs every bar it
can get, and a backtest that can only see the bars it trades on cannot be
audited.

Options are near-the-money calls along the chain, banded per expiry off that
week's own stock range. Banding matters. Taking the high and low across the
whole window and generating every strike in between for every expiry turns a
two-minute pull into a twenty-minute one.

A constructed RIC may name a contract that never listed, and one bad name
takes the whole batch down with it (TS.Intraday.UserRequestError.90001). So
batches split on failure rather than falling straight back to singles — a
bisect costs log2(n) requests instead of n.
"""

from __future__ import annotations

import datetime as dt
import pickle
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from .ric import build_option_ric

warnings.filterwarnings("ignore")

TICKER = "AAPL"
STOCK_RIC = "AAPL.O"

# Hourly, as the brief's default. Timestamps come back in UTC: the US cash
# session is 13:30-20:00 UTC, so 13:00 is a part-bar and 19:00 is the last
# full hour.
INTERVAL = "1h"
SESSION_OPEN_UTC, SESSION_CLOSE_UTC = 13, 20

# Every order in the book is stamped at this bar — 14:00 UTC is 10:00 ET, one
# hour into the session. Late enough that the opening auction has cleared and
# the option has a two-sided quote; early enough to be a real decision rather
# than a closing mark dressed up as a fill.
ORDER_HOUR_UTC = 14

# First and last expiry. The 18 Sep chain had not been published to the
# expired RIC space yet when this was pulled (two days after it expired), so
# the window ends at 11 Sep.
FIRST_EXPIRY = dt.date(2026, 7, 10)
LAST_EXPIRY = dt.date(2026, 9, 11)

# AAPL weeklies list on a $2.50 grid at this price. Probed, not assumed:
# 328/329/331/332/333 do not resolve, 330.00 and 332.50 do.
STRIKE_STEP = 2.50
BAND = 0.05  # +/- 5% of the week's own range -> ~13 strikes per expiry

OPTION_FIELDS = ["BID", "ASK", "TRDPRC_1", "OPEN_PRC", "HIGH_1", "LOW_1",
                 "ACVOL_UNS", "NUM_MOVES"]
STOCK_FIELDS = ["OPEN_PRC", "HIGH_1", "LOW_1", "TRDPRC_1", "ACVOL_UNS", "BID", "ASK"]

DATA_FILE = Path(__file__).with_name("data.pkl")


# ── the calendar, read off the tape rather than assumed ──────────────────

def sessions_of(stock: pd.DataFrame) -> list[dt.date]:
    """Trading days, taken from the stock's own bars. No holiday table."""
    idx = pd.DatetimeIndex(stock.index)
    return sorted({t.date() for t in idx})


def weeks_of(sessions: list[dt.date]) -> list[dict]:
    """
    One entry per expiry week: the Friday, and the sessions leading to it.

    ``entry`` is the first session of the week, not "Monday" — 7 Sep 2026 is
    Labor Day, so that week opens on Tuesday the 8th. A rule that says Monday
    and means it would have skipped a perfectly tradeable week.
    """
    have = set(sessions)
    out = []
    day = FIRST_EXPIRY
    while day <= LAST_EXPIRY:
        monday = day - dt.timedelta(days=4)
        week = [s for s in sessions if monday <= s <= day]
        if day in have and week:
            out.append({"expiry": day, "entry": week[0], "sessions": week})
        else:
            out.append({"expiry": day, "entry": None, "sessions": week,
                        "skip": "expiry Friday is not a trading session"})
        day += dt.timedelta(days=7)
    return out


def strike_band(stock: pd.DataFrame, week: list[dt.date]) -> list[float]:
    """
    Strikes on the listed grid spanning that week's traded range, +/- BAND.

    Banded off TRDPRC_1 and not off LOW_1, because LOW_1 on this tape is
    dirty: the 19:00 UTC bar routinely carries a low tens of dollars under
    the session — 280.11 on 10 Jul, when AAPL never traded below 312 all day
    — and the 13:00 bar does the same on the way in. Those are stray prints
    in the consolidated low, not the stock. Band off them and the request
    count triples on strikes nobody was ever going to write.
    """
    idx = pd.DatetimeIndex(stock.index)
    inside = stock[np.isin(idx.date, list(week))]
    if inside.empty:
        return []
    prints = inside["TRDPRC_1"].dropna()
    lo = float(prints.min()) * (1 - BAND)
    hi = float(prints.max()) * (1 + BAND)
    lo = np.floor(lo / STRIKE_STEP) * STRIKE_STEP
    hi = np.ceil(hi / STRIKE_STEP) * STRIKE_STEP
    return [round(k, 2) for k in np.arange(lo, hi + STRIKE_STEP / 2, STRIKE_STEP)]


# ── the pull ─────────────────────────────────────────────────────────────

def _restore_levels(df: pd.DataFrame, ric: str) -> pd.DataFrame:
    """A single-RIC pull returns flat field columns; put (RIC, field) back."""
    if isinstance(df.columns, pd.MultiIndex):
        return df
    df = df.copy()
    df.columns = pd.MultiIndex.from_product([[ric], df.columns])
    return df


def _get(ld, universe: list[str], start: str, end: str) -> pd.DataFrame | None:
    df = ld.get_history(universe=universe, fields=OPTION_FIELDS,
                        start=start, end=end, interval=INTERVAL)
    if df is None or df.empty:
        return None
    if len(universe) == 1:
        df = _restore_levels(df, universe[0])
    return df.dropna(how="all", axis=1)


def _pull(ld, universe: list[str], start: str, end: str, out: list) -> None:
    """Batch, and bisect on failure so one dead RIC costs log2(n), not n."""
    if not universe:
        return
    try:
        df = _get(ld, universe, start, end)
    except Exception:
        if len(universe) == 1:
            return  # that contract never listed
        half = len(universe) // 2
        _pull(ld, universe[:half], start, end, out)
        _pull(ld, universe[half:], start, end, out)
        return
    if df is not None and not df.empty:
        out.append(df)


def fetch(verbose: bool = True) -> dict:
    import lseg.data as ld

    ld.open_session()
    try:
        start = FIRST_EXPIRY - dt.timedelta(days=6)
        # +1 day: the intraday `end` cuts at midnight of the date given, so
        # asking for LAST_EXPIRY exactly loses the whole last session.
        end = LAST_EXPIRY + dt.timedelta(days=1)
        stock = ld.get_history(universe=[STOCK_RIC], fields=STOCK_FIELDS,
                               start=start.isoformat(), end=end.isoformat(),
                               interval=INTERVAL)
        stock.index = pd.DatetimeIndex(stock.index)
        stock = stock.astype(float).sort_index()
        hours = stock.index.hour
        stock = stock[(hours >= SESSION_OPEN_UTC) & (hours < SESSION_CLOSE_UTC)]
        if verbose:
            print(f"stock: {len(stock)} hourly bars, "
                  f"{len(sessions_of(stock))} sessions, "
                  f"{stock.index.min()} -> {stock.index.max()}")

        weeks = weeks_of(sessions_of(stock))
        frames, chain = [], []
        for w in weeks:
            if w["entry"] is None:
                if verbose:
                    print(f"  {w['expiry']}  skipped — {w['skip']}")
                continue
            strikes = strike_band(stock, w["sessions"])
            rics = [build_option_ric(TICKER, w["expiry"], k, "C") for k in strikes]
            before = len(frames)
            _pull(ld, rics,
                  w["sessions"][0].isoformat(),
                  (w["expiry"] + dt.timedelta(days=1)).isoformat(), frames)
            got = pd.concat(frames[before:], axis=1) if len(frames) > before else pd.DataFrame()
            n = got.columns.get_level_values(0).nunique() if not got.empty else 0
            chain.append({"expiry": w["expiry"], "requested": len(rics), "resolved": n})
            if verbose:
                print(f"  {w['expiry']}  entry {w['entry']}  "
                      f"strikes {strikes[0]:.2f}-{strikes[-1]:.2f}  "
                      f"{n}/{len(rics)} resolved", flush=True)

        options = pd.DataFrame()
        if frames:
            options = pd.concat(frames, axis=1).sort_index()
            options = options.loc[:, ~options.columns.duplicated()]
    finally:
        ld.close_session()

    return {
        "stock": stock,
        "options": options,
        "ticker": TICKER,
        "stock_ric": STOCK_RIC,
        "interval": INTERVAL,
        "order_hour_utc": ORDER_HOUR_UTC,
        "weeks": weeks,
        "chain": chain,
        "option_fields": OPTION_FIELDS,
        "stock_fields": STOCK_FIELDS,
        "fetched_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "synthetic": False,
    }


def main() -> Path:
    payload = fetch()
    with DATA_FILE.open("wb") as f:
        pickle.dump(payload, f)

    options = payload["options"]
    print(f"\nwrote {DATA_FILE}")
    print(f"  stock   {payload['stock'].shape}")
    print(f"  options {options.shape}")
    if not options.empty:
        print(f"  contracts {options.columns.get_level_values(0).nunique()}")
        print(f"  fields    {sorted(set(options.columns.get_level_values(1)))}")
    return DATA_FILE


if __name__ == "__main__":
    main()
