"""
Carry 1.4's daily tape forward from 30 Sep 2025 to the last completed session.

    python -m gearwheel.backfill

Needs LSEG Workspace running (desktop session, lseg-data.config.json), like
every other fetcher in this repo. Run once; everything downstream reads
gearwheel/data.pkl.

What it does
------------
wheel/data.pkl ends on 30 Sep 2025. This re-pulls the stock, the T-bill,
dividends and earnings dates over the whole span (one request each), and the
monthly AAPL puts and calls for every expiry from Oct 2025 on, with the same
strike bands, fields and batching as wheel/fetch.py. Expiries whose window
straddles the old end (Oct and Nov 2025) are pulled whole and replace the
truncated rows. The result has the shape of wheel/data.pkl, so
wheel.book.Market reads it unchanged.

The hourly tape is carried over as it was: the fill assumption (k = 0.57 of
the half-spread) is 1.4's measurement and is reused, not re-measured.
"""

from __future__ import annotations

import datetime as dt
import pickle
import warnings
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from covered_call.ric import build_option_ric
from pmcc.fetch import monthly_expiries
from wheel import fetch as wf

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
OLD_FILE = HERE.parent / "wheel" / "data.pkl"
DATA_FILE = HERE / "data.pkl"
# Resumable, one file per (right, expiry); gitignored.
CACHE = HERE / ".cache"
SIGNAL_FROM = dt.date(2020, 1, 2)


def _cached(key: str, pull, complete=lambda df: not df.empty) -> pd.DataFrame:
    f = CACHE / f"{key}.pkl"
    if f.exists():
        return pd.read_pickle(f)
    df = pull()
    if complete(df):
        CACHE.mkdir(exist_ok=True)
        df.to_pickle(f)
    return df


def option_ric(expiry: dt.date, strike: float, right: str, today: dt.date) -> str:
    """Expired contracts carry the ^ suffix; a still-listed one does not."""
    ric = build_option_ric(wf.TICKER, expiry, strike, right)
    return ric if expiry < today else ric.split("^")[0]


def fetch(verbose: bool = True) -> dict:
    import lseg.data as ld

    with OLD_FILE.open("rb") as f:
        old = pickle.load(f)
    old_end: dt.date = old["end"]
    today = dt.datetime.now(ZoneInfo("America/New_York")).date()
    tag = today.isoformat()

    ld.open_session()
    try:
        pad = wf.START - dt.timedelta(days=80)
        stock = _cached(f"stock_1D_{tag}", lambda: wf._retry(lambda: ld.get_history(
            universe=[wf.STOCK_RIC], fields=wf.STOCK_FIELDS, start=pad.isoformat(),
            end=today.isoformat(), interval="1D")))
        stock.index = pd.DatetimeIndex(stock.index).normalize()
        stock = stock.apply(pd.to_numeric, errors="coerce").sort_index()
        # today's bar, if any, is still forming
        stock = stock[stock.index.date < today]
        new_end = stock.index[-1].date()
        sessions = sorted({t.date() for t in stock.index})
        px = stock["TRDPRC_1"]
        if verbose:
            print(f"stock: {len(stock)} sessions {sessions[0]} -> {new_end}")

        # The gear signals (200-day average, a year of 21-day vols) need about
        # 18 months of closes before the first decision; the book's own tape
        # starts 80 days before it. One extra request, closes only.
        long_px = _cached(f"stock_long_{tag}", lambda: wf._retry(lambda: ld.get_history(
            universe=[wf.STOCK_RIC], fields=["TRDPRC_1"], start=SIGNAL_FROM.isoformat(),
            end=today.isoformat(), interval="1D")))
        long_px.index = pd.DatetimeIndex(long_px.index).normalize()
        long_px = pd.to_numeric(long_px["TRDPRC_1"], errors="coerce").dropna().sort_index()
        long_px = long_px[long_px.index.date <= new_end]

        rate = _cached(f"rate_1D_{tag}", lambda: wf._retry(lambda: ld.get_history(
            universe=[wf.RATE_RIC], fields=["MID_YLD_1", "B_YLD_1"],
            start=pad.isoformat(), end=today.isoformat(), interval="1D")))
        rate.index = pd.DatetimeIndex(rate.index).normalize()
        rate = rate.apply(pd.to_numeric, errors="coerce").sort_index()
        rate = rate[rate.index.date <= new_end]

        div = _cached(f"dividends_{tag}", lambda: wf._retry(lambda: ld.get_data(
            wf.STOCK_RIC, ["TR.DivExDate", "TR.DivPayDate", "TR.DivUnadjustedGross"],
            {"SDate": "2020-01-01", "EDate": "2027-12-31"})))
        div.columns = ["ric", "ex_date", "pay_date", "amount"]
        div = div.dropna(subset=["ex_date"])[["ex_date", "pay_date", "amount"]]

        eps = _cached(f"earnings_{tag}", lambda: wf._retry(lambda: ld.get_data(
            wf.STOCK_RIC, ["TR.EPSActReportDate"],
            {"SDate": "2021-10-01", "EDate": new_end.isoformat(),
             "Period": "FQ0", "Frq": "FQ"})))
        eps.columns = ["ric", "report"]
        earnings = sorted({pd.Timestamp(t) for t in eps["report"].dropna()})
        if verbose:
            print(f"dividends: {len(div)}  earnings: {len(earnings)} "
                  f"(last {earnings[-1].date() if earnings else None})")

        # ── daily: every monthly put and call from Oct 2025 on ─────────
        fresh = monthly_expiries(sessions, old_end + dt.timedelta(days=1),
                                 new_end + dt.timedelta(days=wf.OPEN_WINDOW[0]))
        frames, chain = [], []
        for e in fresh:
            lo_day = e - dt.timedelta(days=wf.OPEN_WINDOW[0])
            hi_day = min(e - dt.timedelta(days=wf.OPEN_WINDOW[1]), new_end)
            if lo_day > new_end:
                continue
            last = min(e, new_end)
            for right, strikes in (("P", wf.put_strikes(px, lo_day, hi_day)),
                                   ("C", wf.call_strikes(px, lo_day, hi_day))):
                rics = [option_ric(e, k, right, today) for k in strikes]
                got = _cached(f"1D_{right}_{e}_{last}", lambda: wf._chain(
                    ld, rics, wf.DAILY_FIELDS, max(lo_day, pad), last, "1D", batch=8))
                if not got.empty:
                    got["date"] = pd.DatetimeIndex(got["date"]).normalize()
                    got = got[got["date"].dt.date <= new_end]
                    frames.append(got)
                n = got["ric"].nunique() if not got.empty else 0
                chain.append({"right": right, "expiry": e, "requested": len(rics),
                              "resolved": n, "lo": strikes[0], "hi": strikes[-1]})
                if verbose:
                    print(f"  {right} {e}  {strikes[0]:.2f}-{strikes[-1]:.2f}  "
                          f"{n}/{len(rics)}", flush=True)
    finally:
        ld.close_session()

    new_opts = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    options = pd.concat([old["options"], new_opts], ignore_index=True)
    options["date"] = pd.DatetimeIndex(options["date"]).normalize()
    # a re-pulled expiry's rows replace the truncated ones from 1.4
    options = (options.drop_duplicates(subset=["date", "ric"], keep="last")
               .sort_values(["date", "ric"]).reset_index(drop=True))
    redone = set(fresh)
    chain = [c for c in old["chain"] if c["expiry"] not in redone] + chain

    out = dict(old)
    out.update({
        "stock": stock,
        "signal_px": long_px,
        "rate": rate,
        "dividends": div.reset_index(drop=True),
        "earnings": earnings,
        "options": options,
        "end": new_end,
        "monthly_expiries": monthly_expiries(
            sessions, wf.START + dt.timedelta(days=wf.OPEN_WINDOW[1]),
            new_end + dt.timedelta(days=wf.OPEN_WINDOW[0])),
        "chain": chain,
        "extended_from": old_end,
        "fetched_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    return out


def main() -> Path:
    payload = fetch()
    with DATA_FILE.open("wb") as f:
        pickle.dump(payload, f)
    o = payload["options"]
    print(f"\nwrote {DATA_FILE}  ({DATA_FILE.stat().st_size / 1e6:.1f} MB)")
    print(f"  stock    {payload['stock'].shape}  -> {payload['end']}")
    print(f"  daily    {len(o):,} rows, {o['ric'].nunique():,} contracts")
    print(f"  dividends {len(payload['dividends'])}, earnings {len(payload['earnings'])}")
    short = [c for c in payload["chain"] if c["resolved"] < 0.8 * c["requested"]]
    for c in short:
        print(f"  SHORT {c['right']} {c['expiry']}: {c['resolved']}/{c['requested']}")
    return DATA_FILE


if __name__ == "__main__":
    main()
