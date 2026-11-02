"""
Pull the tape the wheel trades on.

    python -m wheel.fetch

Needs LSEG Workspace running and an app key in lseg-data.config.json
(gitignored). Run once; everything downstream reads data.pkl.

Two pulls, for two different questions
--------------------------------------
DAILY      What the book trades on. Every standard monthly AAPL put and
           call that could be sold in the window, closing quotes, 3 Jan 2022
           to 30 Sep 2025: a bear market (2022), two rallies (2023-24), the
           April 2025 crash and the recovery. Daily because hourly option
           history on LSEG reaches back about a year (probed 1 Nov 2026: an
           expired Nov-2025 put's first hourly bar is 31 Oct 2025), and the
           wheel needs several regimes, not one. Same tape and timing as
           1.3: decide on the t-1 close, fill on the t close.

HOURLY     What the fill assumption is tested on: the one year LSEG keeps
           hourly, Nov 2025 to Oct 2026. Out-of-the-money monthly puts and
           calls near the strikes the wheel sells, every bar from 45 days
           before expiry. Each bar carries the last trade and the quote, which
           is how 1.2 measured where AAPL options actually print relative to
           the mid. It sits after the backtest window, so the daily tape is
           used to check that the five years before traded the same way.

Bands
-----
PUTS       0.78 x the lowest close to 1.03 x the highest, over the days a
           put on that expiry could be sold (63 to 21 days out). Wide enough
           for the 0.20-0.40 delta grid in a 50%-vol month.
CALLS      0.97 x low to 1.45 x high. The top is far out because the wheel's
           calls must be struck at or above the cost basis of the shares,
           and after a sell-off the basis sits well above spot. $2.50 grid
           to 1.15 x, $5 beyond, which is what AAPL lists that far out.

The daily endpoint drops an unlisted RIC silently and returns the rest; the
hourly endpoint fails the whole batch. Both go through the same bisect, and
the per-expiry resolved count is kept so a silent drop is visible.
"""

from __future__ import annotations

import datetime as dt
import pickle
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from covered_call.ric import build_option_ric
from pmcc.fetch import monthly_expiries

warnings.filterwarnings("ignore")

TICKER = "AAPL"
STOCK_RIC = "AAPL.O"
RATE_RIC = "US3MT=RR"

START = dt.date(2022, 1, 3)
# The last session of the backtest.
END = dt.date(2025, 9, 30)
# Contracts expiring on or after this date are still listed: live RIC, no ^.
PULL_DATE = dt.date(2026, 11, 1)

# A short on expiry E is opened between E-63d (the session after the
# previous monthly, or a profit-take roll) and E-21d.
OPEN_WINDOW = (63, 21)
STEP = 2.50
PUT_BAND = (0.78, 1.03)
CALL_BAND = (0.97, 1.45)
CALL_FINE_TOP = 1.15          # $2.50 grid up to here, $5 above

# Hourly history starts about a year before the pull; the fill test uses all
# of it, to the last complete session before the pull (Sunday 1 Nov 2026).
HOURLY_FROM = dt.date(2025, 11, 3)
HOURLY_TO = dt.date(2026, 10, 30)
HOURLY_WINDOW = 45
HOURLY_PUT = (0.85, 1.00)     # x spot: the out-of-the-money side the wheel sells
HOURLY_CALL = (1.00, 1.15)
HOURLY_STEP = 5.0             # always listed, so batches rarely bisect

DAILY_FIELDS = ["BID", "ASK", "MID_PRICE", "TRDPRC_1", "HIGH_1", "LOW_1",
                "ACVOL_UNS", "OPINT_1", "IMP_VOLT", "DELTA"]
HOURLY_FIELDS = ["BID", "ASK", "TRDPRC_1", "ACVOL_UNS", "NUM_MOVES"]
STOCK_FIELDS = ["OPEN_PRC", "HIGH_1", "LOW_1", "TRDPRC_1", "BID", "ASK",
                "ACVOL_UNS"]

DATA_FILE = Path(__file__).with_name("data.pkl")
# One file per (bar size, right, expiry) chunk, so a pull that dies an hour in
# resumes where it stopped. The first full pull lost its daily half to a
# Workspace disconnect in the last minutes of the hourly half; later passes ran
# into LSEG's rate limit (HTTP 429), which drops requests from a batch
# silently. Compare each chunk's resolved count across passes and delete any
# file that came back short before re-running. Gitignored.
CACHE = Path(__file__).with_name(".cache")


def option_ric(expiry: dt.date, strike: float, right: str) -> str:
    ric = build_option_ric(TICKER, expiry, strike, right)
    return ric if expiry < PULL_DATE else ric.split("^")[0]


def _grid(lo: float, hi: float, step: float) -> list[float]:
    lo = np.floor(lo / step) * step
    hi = np.ceil(hi / step) * step
    return [round(float(k), 2) for k in np.arange(lo, hi + step / 2, step)]


def _window_px(px: pd.Series, lo_day: dt.date, hi_day: dt.date) -> pd.Series:
    w = px[(px.index.date >= lo_day) & (px.index.date <= hi_day)].dropna()
    return w if not w.empty else px[px.index.date <= hi_day].dropna().iloc[-5:]


def put_strikes(px: pd.Series, lo_day, hi_day) -> list[float]:
    w = _window_px(px, lo_day, hi_day)
    return _grid(w.min() * PUT_BAND[0], w.max() * PUT_BAND[1], STEP)


def call_strikes(px: pd.Series, lo_day, hi_day) -> list[float]:
    w = _window_px(px, lo_day, hi_day)
    fine = _grid(w.min() * CALL_BAND[0], w.max() * CALL_FINE_TOP, STEP)
    coarse = _grid(fine[-1], w.max() * CALL_BAND[1], 5.0)
    return sorted(set(fine) | set(coarse))


# ── the pull ─────────────────────────────────────────────────────────────

def _tidy(df: pd.DataFrame, fields: list[str], universe: list[str]) -> pd.DataFrame:
    """Wide (ric, field) frame -> tidy rows of (date, ric, fields...)."""
    if not isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = pd.MultiIndex.from_product([[universe[0]], df.columns])
    df = df.copy()
    df.index = pd.DatetimeIndex(df.index)
    out = df.stack(level=0, future_stack=True)
    out.index.names = ["date", "ric"]
    out = out.reset_index()
    have = [c for c in fields if c in out.columns]
    out[have] = out[have].apply(pd.to_numeric, errors="coerce")
    return out.dropna(subset=have, how="all")


def _pull(ld, universe, fields, start, end, interval, out) -> None:
    """Batch, and bisect on failure so one dead RIC costs log2(n), not n."""
    if not universe:
        return
    try:
        df = ld.get_history(universe=universe, fields=fields, start=start,
                            end=end, interval=interval)
    except Exception:
        if len(universe) == 1:
            return
        half = len(universe) // 2
        _pull(ld, universe[:half], fields, start, end, interval, out)
        _pull(ld, universe[half:], fields, start, end, interval, out)
        return
    if df is not None and not df.empty:
        out.append(_tidy(df, fields, universe))


def _chain(ld, rics, fields, start: dt.date, end: dt.date, interval: str,
           batch: int) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    # daily `start` is exclusive and intraday `end` cuts at midnight: pad both
    s = (start - dt.timedelta(days=3)).isoformat()
    e = (end + dt.timedelta(days=1)).isoformat()
    for i in range(0, len(rics), batch):
        _pull(ld, rics[i:i + batch], fields, s, e, interval, frames)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _retry(fn, tries: int = 4, wait: float = 20.0):
    """Workspace drops the odd request ("Server disconnected"); try again."""
    for i in range(tries):
        try:
            return fn()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(wait)


def _cached(key: str, pull, complete=lambda df: not df.empty) -> pd.DataFrame:
    f = CACHE / f"{key}.pkl"
    if f.exists():
        return pd.read_pickle(f)
    df = pull()
    if complete(df):
        CACHE.mkdir(exist_ok=True)
        df.to_pickle(f)
    return df


def fetch(verbose: bool = True) -> dict:
    import lseg.data as ld

    ld.open_session()
    try:
        pad = START - dt.timedelta(days=80)
        stock = _cached("stock_1D", lambda: _retry(lambda: ld.get_history(
            universe=[STOCK_RIC], fields=STOCK_FIELDS, start=pad.isoformat(),
            end=END.isoformat(), interval="1D")))
        stock.index = pd.DatetimeIndex(stock.index).normalize()
        stock = stock.apply(pd.to_numeric, errors="coerce").sort_index()
        sessions = sorted({t.date() for t in stock.index})
        px = stock["TRDPRC_1"]
        if verbose:
            print(f"stock: {len(stock)} sessions {sessions[0]} -> {sessions[-1]}")

        rate = _cached("rate_1D", lambda: _retry(lambda: ld.get_history(
            universe=[RATE_RIC], fields=["MID_YLD_1", "B_YLD_1"], start=pad.isoformat(),
            end=END.isoformat(), interval="1D")))
        rate.index = pd.DatetimeIndex(rate.index).normalize()
        rate = rate.apply(pd.to_numeric, errors="coerce").sort_index()

        div = _cached("dividends", lambda: _retry(lambda: ld.get_data(
            STOCK_RIC, ["TR.DivExDate", "TR.DivPayDate", "TR.DivUnadjustedGross"],
            {"SDate": "2020-01-01", "EDate": "2026-12-31"})))
        div.columns = ["ric", "ex_date", "pay_date", "amount"]
        div = div.dropna(subset=["ex_date"])[["ex_date", "pay_date", "amount"]]
        eps = _cached("earnings", lambda: _retry(lambda: ld.get_data(
            STOCK_RIC, ["TR.EPSActReportDate"],
            {"SDate": "2021-10-01", "EDate": END.isoformat(), "Period": "FQ0", "Frq": "FQ"})))
        eps.columns = ["ric", "report"]
        earnings = sorted({pd.Timestamp(t) for t in eps["report"].dropna()})

        # ── daily: every monthly put and call, banded ──────────────────
        expiries = monthly_expiries(sessions, START + dt.timedelta(days=OPEN_WINDOW[1]),
                                    END + dt.timedelta(days=OPEN_WINDOW[0]))
        frames, chain = [], []
        for e in expiries:
            lo_day = e - dt.timedelta(days=OPEN_WINDOW[0])
            hi_day = min(e - dt.timedelta(days=OPEN_WINDOW[1]), END)
            if lo_day > END:
                continue
            for right, strikes in (("P", put_strikes(px, lo_day, hi_day)),
                                   ("C", call_strikes(px, lo_day, hi_day))):
                rics = [option_ric(e, k, right) for k in strikes]
                got = _cached(f"1D_{right}_{e}", lambda: _chain(
                    ld, rics, DAILY_FIELDS, max(lo_day, pad), min(e, END), "1D", batch=8))
                if not got.empty:
                    got["date"] = pd.DatetimeIndex(got["date"]).normalize()
                    got = got[got["date"].dt.date <= END]
                    frames.append(got)
                n = got["ric"].nunique() if not got.empty else 0
                chain.append({"right": right, "expiry": e, "requested": len(rics),
                              "resolved": n, "lo": strikes[0], "hi": strikes[-1]})
                if verbose:
                    print(f"  {right} {e}  {strikes[0]:.2f}-{strikes[-1]:.2f}  "
                          f"{n}/{len(rics)}", flush=True)

        # ── hourly: the fill test, the year LSEG keeps ─────────────────
        hstock = _cached("stock_1h", lambda: _retry(lambda: ld.get_history(
            universe=[STOCK_RIC], fields=["TRDPRC_1", "BID", "ASK"],
            start=(HOURLY_FROM - dt.timedelta(days=3)).isoformat(),
            end=(HOURLY_TO + dt.timedelta(days=1)).isoformat(), interval="1h")))
        hstock.index = pd.DatetimeIndex(hstock.index)
        hstock = hstock.apply(pd.to_numeric, errors="coerce").sort_index()
        # that year's calendar and closes come off the hourly tape itself
        hpx = hstock["TRDPRC_1"].groupby(hstock.index.normalize()).last()
        hexp = monthly_expiries(sorted({t.date() for t in hpx.index}),
                                HOURLY_FROM + dt.timedelta(days=21),
                                HOURLY_TO + dt.timedelta(days=30))
        hourly, hchain = [], []
        for e in hexp:
            lo_day = max(e - dt.timedelta(days=HOURLY_WINDOW), HOURLY_FROM)
            hi_day = min(e, HOURLY_TO)
            if hi_day <= lo_day or e - dt.timedelta(days=21) < HOURLY_FROM:
                continue
            w = _window_px(hpx, lo_day, min(e - dt.timedelta(days=14), HOURLY_TO))
            ref = float(w.mean())
            strikes = {"P": _grid(ref * HOURLY_PUT[0], ref * HOURLY_PUT[1], HOURLY_STEP),
                       "C": _grid(ref * HOURLY_CALL[0], ref * HOURLY_CALL[1], HOURLY_STEP)}
            for right, ks in strikes.items():
                rics = [option_ric(e, k, right) for k in ks]
                # $5 strikes are always listed, so a short count is a dropped
                # request, not a missing contract: cache only a complete chunk
                got = _cached(f"1h_{right}_{e}", lambda: _chain(
                    ld, rics, HOURLY_FIELDS, lo_day, hi_day, "1h", batch=5),
                    complete=lambda df: not df.empty and df["ric"].nunique() == len(rics))
                if not got.empty:
                    hourly.append(got)
                n = got["ric"].nunique() if not got.empty else 0
                hchain.append({"right": right, "expiry": e, "requested": len(rics),
                               "resolved": n})
                if verbose:
                    print(f"  hourly {right} {e}  {ks[0]:.0f}-{ks[-1]:.0f}  "
                          f"{n}/{len(rics)}  {len(got)} bars", flush=True)
    finally:
        ld.close_session()

    options = pd.concat(frames, ignore_index=True)
    options = options.drop_duplicates(subset=["date", "ric"]).sort_values(["date", "ric"])
    hourly = pd.concat(hourly, ignore_index=True) if hourly else pd.DataFrame()
    if not hourly.empty:
        hourly = hourly.drop_duplicates(subset=["date", "ric"]).sort_values(["date", "ric"])

    return {
        "stock": stock,
        "rate": rate,
        "dividends": div.reset_index(drop=True),
        "earnings": earnings,
        "options": options.reset_index(drop=True),
        "hourly": hourly.reset_index(drop=True),
        "hourly_stock": hstock,
        "ticker": TICKER,
        "stock_ric": STOCK_RIC,
        "rate_ric": RATE_RIC,
        "start": START,
        "end": END,
        "monthly_expiries": expiries,
        "chain": chain,
        "hourly_chain": hchain,
        "daily_fields": DAILY_FIELDS,
        "hourly_fields": HOURLY_FIELDS,
        "fetched_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "synthetic": False,
    }


def main() -> Path:
    payload = fetch()
    with DATA_FILE.open("wb") as f:
        pickle.dump(payload, f)
    o, h = payload["options"], payload["hourly"]
    print(f"\nwrote {DATA_FILE}  ({DATA_FILE.stat().st_size / 1e6:.1f} MB)")
    print(f"  stock    {payload['stock'].shape}")
    print(f"  daily    {len(o):,} rows, {o['ric'].nunique():,} contracts")
    print(f"  hourly   {len(h):,} bars, {h['ric'].nunique() if len(h) else 0:,} contracts")
    print(f"  dividends {len(payload['dividends'])}, earnings {len(payload['earnings'])}")
    return DATA_FILE


if __name__ == "__main__":
    main()
