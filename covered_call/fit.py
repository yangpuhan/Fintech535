"""
Does a fill at the mid survive contact with the tape?

The book assumes every call was written at mid = (BID+ASK)/2 on the order
bar. That assumption is free to make and expensive to be wrong about, so it
gets tested against the prints on the same bars.

Three separate questions, and they are not the same question
------------------------------------------------------------
1. Does the mid predict the print at all?  -> regress TRDPRC_1 on mid, R^2.
   A high R^2 here is nearly free: both series are dominated by moneyness, so
   a $40 ITM call and a $0.05 wing will line up no matter how bad the mid is.
   Necessary, not sufficient.

2. Is the print inside the quote?  -> % of bars with bid <= TRDPRC_1 <= ask.
   This is the one that actually licenses the assumption. If trades print
   inside the spread, a limit at the mid is a price someone was there to
   meet.

3. Is the mid *biased*?  -> (print - mid) / halfspread, per bar. Zero means
   the mid is the middle of real trading. Systematically positive means
   trades happen at the offer and a seller at the mid was dreaming.

Question 3 is where a covered call gets judged, because the book is always a
seller. Selling at the mid when the tape trades at the bid is a free lunch
the backtest gave itself.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def regress(x: np.ndarray, y: np.ndarray) -> dict:
    """OLS y = a + b x, with R^2. Plain least squares, nothing robust."""
    if len(x) < 3:
        return {"n": int(len(x)), "slope": None, "intercept": None, "r2": None}
    b, a = np.polyfit(x, y, 1)
    pred = a + b * x
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    return {
        "n": int(len(x)),
        "slope": float(np.round(b, 4)),
        "intercept": float(np.round(a, 4)),
        "r2": float(np.round(1 - ss_res / ss_tot, 4)) if ss_tot > 0 else None,
        "rmse": float(np.round(np.sqrt(ss_res / len(x)), 4)),
        "x_lo": float(np.round(x.min(), 2)),
        "x_hi": float(np.round(x.max(), 2)),
    }


def analyse(opts: pd.DataFrame, stock: pd.DataFrame,
            max_points: int = 4000) -> dict:
    """
    Everything the scatter section needs, from the hourly option table.

    Moneyness is attached from the stock print on the same bar, so the
    scatter can be cut into ITM / near / OTM without a second join later.
    """
    px = stock["TRDPRC_1"]
    df = opts.copy()
    df["spot"] = df["ts"].map(px)
    df = df[df["mid"].notna() & df["TRDPRC_1"].notna() & df["spot"].notna()]
    df = df[df["TRDPRC_1"] > 0]

    df["moneyness"] = df["spot"] / df["strike"] - 1.0
    df["resid"] = df["TRDPRC_1"] - df["mid"]
    half = df["spread"] / 2.0
    df["z"] = np.where(half > 0, df["resid"] / half, np.nan)
    df["inside"] = (df["TRDPRC_1"] >= df["BID"] - 1e-9) & \
                   (df["TRDPRC_1"] <= df["ASK"] + 1e-9)

    x = df["mid"].to_numpy(float)
    y = df["TRDPRC_1"].to_numpy(float)
    overall = regress(x, y)

    # near the money: within 2% either side, which is the band the book
    # actually writes in
    near = df[df["moneyness"].abs() <= 0.02]
    cuts = {
        "near": regress(near["mid"].to_numpy(float),
                        near["TRDPRC_1"].to_numpy(float)),
        "cheap": regress(df[df["mid"] < 1.0]["mid"].to_numpy(float),
                         df[df["mid"] < 1.0]["TRDPRC_1"].to_numpy(float)),
    }

    # thin the scatter for the page, keeping the shape: a stratified draw on
    # log-mid, so the cheap end is not swamped by the expensive one
    pts = df
    if len(df) > max_points:
        bins = pd.qcut(np.log(df["mid"].clip(lower=0.01)), 40, duplicates="drop")
        per = max(1, max_points // bins.nunique())
        pts = df.groupby(bins, observed=True, group_keys=False).apply(
            lambda g: g.sample(min(len(g), per), random_state=0))

    return {
        "overall": overall,
        "cuts": cuts,
        "n_pairs": int(len(df)),
        "n_contracts": int(df["ric"].nunique()),
        "pct_inside": float(np.round(df["inside"].mean() * 100, 1)),
        "median_resid": float(np.round(df["resid"].median(), 4)),
        "mean_resid": float(np.round(df["resid"].mean(), 4)),
        "median_z": float(np.round(df["z"].median(), 3)),
        "mean_z": float(np.round(df["z"].mean(), 3)),
        "median_spread": float(np.round(df["spread"].median(), 3)),
        "median_spread_pct": float(np.round(
            (df["spread"] / df["mid"].replace(0, np.nan)).median() * 100, 1)),
        "points": [[float(np.round(m, 4)), float(np.round(t, 4)),
                    float(np.round(mo * 100, 2))]
                   for m, t, mo in zip(pts["mid"], pts["TRDPRC_1"],
                                       pts["moneyness"])],
        "resid_hist": _hist(df["z"].dropna().to_numpy(float)),
    }


def _hist(z: np.ndarray, lo: float = -1.5, hi: float = 1.5,
          bins: int = 31) -> dict:
    """(print - mid) in half-spreads. -1 is the bid, 0 the mid, +1 the ask."""
    counts, edges = np.histogram(np.clip(z, lo, hi), bins=bins, range=(lo, hi))
    return {
        "centres": [float(np.round((edges[i] + edges[i + 1]) / 2, 3))
                    for i in range(len(counts))],
        "counts": [int(c) for c in counts],
        "pct_at_bid": float(np.round((z <= -0.9).mean() * 100, 1)),
        "pct_at_ask": float(np.round((z >= 0.9).mean() * 100, 1)),
        "pct_mid_ish": float(np.round((np.abs(z) <= 0.25).mean() * 100, 1)),
    }


def order_bar_evidence(opts: pd.DataFrame, weeks: list[dict]) -> list[dict]:
    """
    The narrow version of the same question: on the exact bar each call was
    written, did that contract trade, and where?

    Ten rows, one per week. This is the evidence that the book's own fills
    were reachable, as opposed to the chain-wide claim that mids are sane.
    """
    idx = opts.set_index(["ts", "ric"])
    out = []
    for w in weeks:
        ts = pd.Timestamp(w["entry_ts"])
        ric = w.get("ric")
        row = None
        if ric is not None:
            try:
                row = idx.loc[(ts, ric)]
            except KeyError:
                row = None
        if row is None:
            continue
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        trd = row["TRDPRC_1"]
        out.append({
            "entry": w["entry"], "strike": w["strike"],
            "bid": float(row["BID"]), "ask": float(row["ASK"]),
            "mid": float(np.round(row["mid"], 4)),
            "trade": None if pd.isna(trd) else float(trd),
            "volume": None if pd.isna(row["ACVOL_UNS"]) else int(row["ACVOL_UNS"]),
            "moves": None if pd.isna(row["NUM_MOVES"]) else int(row["NUM_MOVES"]),
            "vs_mid": None if pd.isna(trd) else float(np.round(trd - row["mid"], 4)),
        })
    return out
