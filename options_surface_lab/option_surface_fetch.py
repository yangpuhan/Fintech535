"""
LSEG pull for the options surface lab.

Why this file exists
--------------------
The starter asked LSEG for ``SETTLE``. That field does not exist on this
universe -- OPRA equity options come back with::

    TSCC.QS.UserRequestError.90006, The universe does not support the
    following fields: [SETTLE]

so every SETTLE column was all-NaN and got dropped, which is why the original
cache holds nothing but TRDPRC_1.

``THEO_VALUE`` plays the role the assignment gives SETTLE: an exchange-side
model mark that prints on more series than trades do.  BID/ASK come along so
the "what would you actually get filled at" question has an honest answer,
and IMP_VOLT is already here for next week's volatility surface.

Run directly to (re)build the cache::

    python -m options_surface_lab.option_surface_fetch
"""

from __future__ import annotations

import datetime as dt
import pickle
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# The mark (THEO_VALUE) first, the print (TRDPRC_1) second, then the evidence
# that lets us argue about fills.
OPTION_FIELDS = [
    "TRDPRC_1",
    "THEO_VALUE",
    "MID_PRICE",
    "BID",
    "ASK",
    "ACVOL_UNS",
    "OPINT_1",
    "IMP_VOLT",
]
STOCK_FIELDS = ["OPEN_PRC", "HIGH_1", "LOW_1", "TRDPRC_1"]

DATA_FILE = Path(__file__).with_name("option_surface_data.pkl")


def build_ric(expiry: dt.date, strike: float, cp: str, root: str = "UUUU") -> str:
    """
    OPRA-style expired-contract RIC: ``{ROOT}{M}{DD}{YY}{SSSSS}.U^{M}{YY}``.

    The brief's Appendix A says the ``^`` suffix "repeats the month letter",
    and for calls it does. For puts it does not, and following the brief
    returns ``TS.Interday.UserRequestError.70005, The universe is not found``
    on every put in the window::

        UUUUT212601500.U^T26   put code in the suffix   -> not found
        UUUUT212601500.U^H26   call code in the suffix  -> resolves

    The suffix names the expiry *chain*, which is keyed off the call code
    regardless of the contract's own right. Getting this wrong is why the
    first pull came back with 313 calls and zero puts.
    """
    body = chr(ord("A") + expiry.month - 1) if cp == "C" else chr(ord("M") + expiry.month - 1)
    chain = chr(ord("A") + expiry.month - 1)
    return (
        f"{root.upper()}{body}{expiry:%d}{expiry:%y}"
        f"{int(round(strike * 100)):05d}.U^{chain}{expiry:%y}"
    )


def expired_fridays(start: dt.date, end: dt.date) -> list[dt.date]:
    """
    Fridays in the window that have *already expired*.

    The ``^{M}{YY}`` suffix only resolves for dead contracts. Asking for a
    still-live expiry returns an empty frame, which is what the probe run
    showed for Sep/Oct 2026.
    """
    today = dt.date.today()
    return [d.date() for d in pd.date_range(start, end, freq="W-FRI") if d.date() < today]


def strike_band(
    df_stock: pd.DataFrame,
    expiry: dt.date,
    pad: float = 3.0,
    step: float = 0.50,
) -> np.ndarray:
    """
    Strikes to request for one expiry.

    The starter took the high/low across the *entire* window and generated
    every strike in between for every expiry. README flags that as the reason
    the pull crawls; banding per expiry cuts the request count a lot.
    """
    alive = df_stock[df_stock.index.date <= expiry]
    if alive.empty:
        alive = df_stock
    lo = float(alive["LOW_1"].min()) - pad
    hi = float(alive["HIGH_1"].max()) + pad
    lo = max(step, np.floor(lo / step) * step)
    hi = np.ceil(hi / step) * step
    return np.arange(lo, hi + step, step)


def fetch(
    ticker_stock: str = "UUUU.K",
    ticker_root: str = "UUUU",
    weeks_back: int = 14,
    batch_size: int = 40,
    verbose: bool = True,
) -> dict:
    """Pull the stock history and every expired option chain in the window."""
    import lseg.data as ld

    ld.open_session()
    try:
        end = dt.date.today()
        start = end - dt.timedelta(weeks=weeks_back)
        start_s, end_s = start.isoformat(), end.isoformat()

        df_stock = ld.get_history(
            universe=[ticker_stock],
            fields=STOCK_FIELDS,
            start=start_s,
            end=end_s,
            interval="daily",
        )
        df_stock = df_stock.astype(float)
        if verbose:
            print(f"stock: {df_stock.shape[0]} sessions "
                  f"{df_stock.index.min():%Y-%m-%d} -> {df_stock.index.max():%Y-%m-%d}")

        candidates: list[str] = []
        for expiry in expired_fridays(start, end):
            for strike in strike_band(df_stock, expiry):
                for cp in ("C", "P"):
                    candidates.append(build_ric(expiry, float(strike), cp, ticker_root))
        if verbose:
            print(f"requesting {len(candidates)} candidate RICs "
                  f"in {-(-len(candidates) // batch_size)} batches")

        frames = []
        for i in range(0, len(candidates), batch_size):
            batch = candidates[i : i + batch_size]
            try:
                df = ld.get_history(
                    universe=batch,
                    fields=OPTION_FIELDS,
                    start=start_s,
                    end=end_s,
                    interval="daily",
                )
            except Exception:
                # Synthetic RICs include contracts that never listed; a single
                # bad name can take the whole batch down, so retry one by one.
                for ric in batch:
                    try:
                        df1 = ld.get_history(
                            universe=[ric],
                            fields=OPTION_FIELDS,
                            start=start_s,
                            end=end_s,
                            interval="daily",
                        )
                    except Exception:
                        continue
                    if df1 is not None and not df1.empty:
                        frames.append(_tag_single(df1, ric))
                continue

            if df is not None and not df.empty:
                df = df.dropna(how="all", axis=1)
                if not df.empty:
                    frames.append(df)
            if verbose:
                print(f"  batch {i // batch_size + 1}: {len(frames)} frames so far", flush=True)

        df_options = pd.DataFrame()
        if frames:
            df_options = pd.concat(frames, axis=1)
            df_options = df_options.loc[:, ~df_options.columns.duplicated()]
    finally:
        ld.close_session()

    payload = {
        "stock": df_stock,
        "options": df_options,
        "ticker": ticker_root,
        "fields": OPTION_FIELDS,
        "fetched_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "synthetic": False,
    }
    return payload


def _tag_single(df: pd.DataFrame, ric: str) -> pd.DataFrame:
    """A single-RIC pull comes back with flat field columns; restore (RIC, field)."""
    if isinstance(df.columns, pd.MultiIndex):
        return df
    df = df.copy()
    df.columns = pd.MultiIndex.from_product([[ric], df.columns])
    return df


def main() -> Path:
    payload = fetch()
    opts = payload["options"]
    with DATA_FILE.open("wb") as f:
        pickle.dump(payload, f)
    print(f"\nwrote {DATA_FILE}")
    print(f"  options frame: {opts.shape}")
    if not opts.empty and isinstance(opts.columns, pd.MultiIndex):
        rics = opts.columns.get_level_values(0).nunique()
        print(f"  distinct RICs: {rics}")
        print(f"  fields present: {sorted(set(opts.columns.get_level_values(1)))}")
    return DATA_FILE


if __name__ == "__main__":
    main()
