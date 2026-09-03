"""
Pull expired UUUU option history from LSEG into data.pkl.

Run once; everything else reads the pickle. Needs LSEG Workspace running and
an app key in lseg-data.config.json (gitignored).

    python -m options_surface_lab.fetch

Two things this has to get right
-------------------------------
1. There is no settlement price. ``SETTLE`` answers "the universe does not
   support the following fields", so MID_PRICE — the closing NBBO midpoint —
   is the mark. BID and ASK come along so the fill question is answerable.
2. The expiry chain suffix uses the *call* month code even for puts. See
   ric.py; get it wrong and the puts come back empty with no error.
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

OPTION_FIELDS = ["TRDPRC_1", "MID_PRICE", "BID", "ASK", "ACVOL_UNS", "OPINT_1", "IMP_VOLT"]
STOCK_FIELDS = ["OPEN_PRC", "HIGH_1", "LOW_1", "TRDPRC_1"]

DATA_FILE = Path(__file__).with_name("data.pkl")


def expired_fridays(start: dt.date, end: dt.date) -> list[dt.date]:
    """
    Fridays in the window that have already expired.

    The ``^`` suffix only resolves for dead contracts — a still-live expiry
    returns an empty frame, so asking for one is pure latency.
    """
    today = dt.date.today()
    return [d.date() for d in pd.date_range(start, end, freq="W-FRI") if d.date() < today]


def strike_band(df_stock: pd.DataFrame, expiry: dt.date,
                pad: float = 3.0, step: float = 0.50) -> np.ndarray:
    """
    Strikes worth requesting for one expiry.

    Taking the high and low across the whole window and generating every
    strike in between for every expiry is what makes the pull crawl. Banding
    per expiry cuts the request count a lot.
    """
    alive = df_stock[df_stock.index.date <= expiry]
    if alive.empty:
        alive = df_stock
    low = max(step, np.floor((float(alive["LOW_1"].min()) - pad) / step) * step)
    high = np.ceil((float(alive["HIGH_1"].max()) + pad) / step) * step
    return np.arange(low, high + step, step)


def _restore_levels(df: pd.DataFrame, ric: str) -> pd.DataFrame:
    """A single-RIC pull returns flat field columns; put (RIC, field) back."""
    if isinstance(df.columns, pd.MultiIndex):
        return df
    df = df.copy()
    df.columns = pd.MultiIndex.from_product([[ric], df.columns])
    return df


def fetch(underlying: str = "UUUU", stock_ric: str = "UUUU.K",
          weeks_back: int = 14, batch_size: int = 40, verbose: bool = True) -> dict:
    import lseg.data as ld

    ld.open_session()
    try:
        end = dt.date.today()
        start = end - dt.timedelta(weeks=weeks_back)
        start_s, end_s = start.isoformat(), end.isoformat()

        df_stock = ld.get_history(universe=[stock_ric], fields=STOCK_FIELDS,
                                  start=start_s, end=end_s, interval="daily").astype(float)
        if verbose:
            print(f"stock: {len(df_stock)} sessions "
                  f"{df_stock.index.min():%Y-%m-%d} → {df_stock.index.max():%Y-%m-%d}")

        candidates = [
            build_option_ric(underlying, expiry, float(strike), right)
            for expiry in expired_fridays(start, end)
            for strike in strike_band(df_stock, expiry)
            for right in ("C", "P")
        ]
        if verbose:
            print(f"requesting {len(candidates)} candidate RICs in "
                  f"{-(-len(candidates) // batch_size)} batches")

        frames = []
        for i in range(0, len(candidates), batch_size):
            batch = candidates[i:i + batch_size]
            try:
                df = ld.get_history(universe=batch, fields=OPTION_FIELDS,
                                    start=start_s, end=end_s, interval="daily")
            except Exception:
                # Constructed RICs include contracts that never listed, and a
                # single bad name can take a whole batch down. Retry alone.
                for ric in batch:
                    try:
                        one = ld.get_history(universe=[ric], fields=OPTION_FIELDS,
                                             start=start_s, end=end_s, interval="daily")
                    except Exception:
                        continue
                    if one is not None and not one.empty:
                        frames.append(_restore_levels(one, ric))
                continue

            if df is not None and not df.empty:
                df = df.dropna(how="all", axis=1)
                if not df.empty:
                    frames.append(df)
            if verbose:
                print(f"  batch {i // batch_size + 1}: {len(frames)} frames", flush=True)

        options = pd.DataFrame()
        if frames:
            options = pd.concat(frames, axis=1)
            options = options.loc[:, ~options.columns.duplicated()]
    finally:
        ld.close_session()

    return {
        "stock": df_stock,
        "options": options,
        "underlying": underlying,
        "fields": OPTION_FIELDS,
        "fetched_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def main() -> Path:
    payload = fetch()
    with DATA_FILE.open("wb") as f:
        pickle.dump(payload, f)

    options = payload["options"]
    print(f"\nwrote {DATA_FILE}")
    print(f"  frame {options.shape}")
    if not options.empty and isinstance(options.columns, pd.MultiIndex):
        print(f"  contracts {options.columns.get_level_values(0).nunique()}")
        print(f"  fields {sorted(set(options.columns.get_level_values(1)))}")
    return DATA_FILE


if __name__ == "__main__":
    main()
