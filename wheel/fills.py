"""
What price does a wheel trade actually get?

The brief asks for every fill assumption to be stated and justified with
data. 1.2 and 1.3 filled at the mid and showed the natural side as a bound.
Here the fill is measured instead of assumed:

    sell at  mid - k x half-spread        buy at  mid + k x half-spread

where k is the *effective* spread as a share of the quoted one — how far
real AAPL option prints land from the mid, on average, in half-spreads.
k = 0 is the mid, k = 1 is the bid (selling) or the ask (buying).

Three pieces of evidence
------------------------
HOURLY     The estimate. Out-of-the-money AAPL monthlies 14-45 days out,
           the last year (the only year LSEG keeps hourly). Each bar's last
           trade against the bar's closing quote: z = (print - mid) / half.
           k = mean of min(|z|, 1). A print outside its own bar's quote is
           a clock mismatch — the trade came minutes before the quote moved
           — not a price anyone could have been made to pay, so it counts
           as the far side and no worse. The mismatch also pushes the inside
           prints away from the mid, so k is if anything too high.
DAILY      The same statistic on the closing quote and the day's last trade,
           over the whole 2022-2026 window, by year. Noisier (the last trade
           can be well before the close) but it shows whether the last year
           is representative of the five.
THE FILLS  For every option the wheel actually traded: that day's volume and
           open interest against the order, and whether the day's own
           traded range reached the price the book filled at.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from covered_call.ric import parse_option_ric

from .book import Market, _r2, _r4

DTE = (14, 45)
CAP = 1.0


def _z(df: pd.DataFrame) -> pd.Series:
    mid = (df["BID"] + df["ASK"]) / 2.0
    half = (df["ASK"] - df["BID"]) / 2.0
    return (df["TRDPRC_1"] - mid) / half


def _summary(z: pd.Series, half: pd.Series, mid: pd.Series) -> dict:
    a = z.abs()
    return {
        "n": int(len(z)),
        "k": _r4(float(a.clip(upper=CAP).mean())),
        "median_abs": _r4(float(a.median())),
        "mean_z": _r4(float(z.clip(-CAP, CAP).mean())),
        "pct_inside": _r2(float((a <= 1 + 1e-9).mean() * 100)),
        "pct_near_mid": _r2(float((a <= 0.25).mean() * 100)),
        "pct_at_bid": _r2(float((z <= -0.75).mean() * 100)),
        "pct_at_ask": _r2(float((z >= 0.75).mean() * 100)),
        "half": _r4(float(half.median())),
        "spread_pct": _r2(float((2 * half / mid).median() * 100)),
    }


def hourly(raw: dict) -> dict:
    h = raw["hourly"].copy()
    if h.empty:
        return {}
    meta = {r: parse_option_ric(r) for r in h["ric"].unique()}
    h = h[h["ric"].map(lambda r: meta[r] is not None)].copy()
    h["strike"] = h["ric"].map(lambda r: meta[r]["strike"])
    h["expiry"] = pd.to_datetime(h["ric"].map(lambda r: meta[r]["expiry"]))
    h["right"] = h["ric"].map(lambda r: meta[r]["right"])
    ts = pd.DatetimeIndex(h["date"])
    et = ts.tz_localize("UTC").tz_convert("America/New_York")
    h["et_hour"] = et.hour
    # bars are stamped at their start: 09:00 holds 09:30-10:00, 15:00 the last hour
    h = h[(h["et_hour"] >= 9) & (h["et_hour"] <= 15)]
    st = raw["hourly_stock"]
    spot = st["TRDPRC_1"] if "TRDPRC_1" in st.columns else st.iloc[:, 0]
    spot.index = pd.DatetimeIndex(spot.index)
    h["S"] = h["date"].map(spot)
    h["dte"] = (h["expiry"] - pd.to_datetime(h["date"]).dt.normalize()).dt.days
    ok = (h["BID"] > 0) & (h["ASK"] > h["BID"]) & (h["TRDPRC_1"] > 0) & \
         (h["ACVOL_UNS"] > 0) & h["S"].notna() & h["dte"].between(*DTE)
    otm = np.where(h["right"] == "P", h["strike"] <= h["S"], h["strike"] >= h["S"])
    h = h[ok & otm].copy()
    h["z"] = _z(h)
    h["mid"] = (h["BID"] + h["ASK"]) / 2.0
    h["half"] = (h["ASK"] - h["BID"]) / 2.0

    out = _summary(h["z"], h["half"], h["mid"])
    out.update({
        "contracts": int(h["ric"].nunique()),
        "first": str(h["date"].min())[:10], "last": str(h["date"].max())[:10],
        "by_right": {r: _summary(g["z"], g["half"], g["mid"]) for r, g in h.groupby("right")},
        "by_month": [{"month": str(k), **_summary(g["z"], g["half"], g["mid"])}
                     for k, g in h.groupby(h["date"].dt.to_period("M"))],
        "by_hour": [{"hour": int(k), **_summary(g["z"], g["half"], g["mid"])}
                    for k, g in h.groupby("et_hour")],
        "hist": _hist(h["z"]),
    })
    return out


def _hist(z: pd.Series, lo=-1.5, hi=1.5, bins=30) -> dict:
    counts, edges = np.histogram(z.clip(lo, hi), bins=bins, range=(lo, hi))
    return {"centres": [round(float((edges[i] + edges[i + 1]) / 2), 3) for i in range(bins)],
            "counts": [int(c) for c in counts]}


def daily(m: Market) -> dict:
    o = m.opts
    o = o[(o["ACVOL_UNS"] > 0) & (o["BID"] > 0) & (o["ASK"] > o["BID"]) &
          (o["TRDPRC_1"] > 0) & o["delta"].abs().between(0.15, 0.45)]
    dte = (pd.to_datetime(o["expiry"]) - o["date"]).dt.days
    o = o[dte.between(*DTE)].copy()
    o["z"] = _z(o)
    out = _summary(o["z"], o["half"], o["mid"])
    out["by_year"] = [{"year": int(y), **_summary(g["z"], g["half"], g["mid"])}
                      for y, g in o.groupby(o["date"].dt.year)]
    out["hist"] = _hist(o["z"])
    return out


def at_fills(m: Market, trades: list[dict]) -> list[dict]:
    """The book's own option fills, against that day's tape."""
    o = m.opts.set_index(["d", "ric"])
    rows = []
    for t in trades:
        if t["action"] not in ("SELL TO OPEN", "BUY TO CLOSE"):
            continue
        r = o.loc[(t["date"], t["ric"])]
        sell = t["action"] == "SELL TO OPEN"
        hi, lo = r["HIGH_1"], r["LOW_1"]
        reached = None
        if np.isfinite(hi) and np.isfinite(lo):
            reached = bool(hi >= t["price"] - 1e-9) if sell else bool(lo <= t["price"] + 1e-9)
        rows.append({
            "date": t["date"], "ric": t["ric"], "action": t["action"], "qty": abs(t["qty"]),
            "bid": _r4(r["BID"]), "ask": _r4(r["ASK"]), "mid": t["mid"], "price": t["price"],
            "last": _r4(r["TRDPRC_1"]), "high": _r4(hi), "low": _r4(lo),
            "volume": None if not np.isfinite(r["ACVOL_UNS"]) else int(r["ACVOL_UNS"]),
            "oi": None if not np.isfinite(r["OPINT_1"]) else int(r["OPINT_1"]),
            "spread_pct": _r2(2 * r["half"] / r["mid"] * 100),
            "reached": reached,
        })
    return rows


def fill_summary(rows: list[dict]) -> dict:
    vol = [r["volume"] for r in rows if r["volume"]]
    share = [r["qty"] / r["volume"] * 100 for r in rows if r["volume"]]
    reached = [r["reached"] for r in rows if r["reached"] is not None]
    return {
        "n": len(rows),
        "median_volume": int(np.median(vol)) if vol else None,
        "min_volume": int(min(vol)) if vol else None,
        "median_oi": int(np.median([r["oi"] for r in rows if r["oi"]])) if rows else None,
        "median_share_pct": _r2(float(np.median(share))) if share else None,
        "max_share_pct": _r2(float(max(share))) if share else None,
        "median_spread_pct": _r2(float(np.median([r["spread_pct"] for r in rows]))),
        "pct_reached": _r2(sum(reached) / len(reached) * 100) if reached else None,
        "n_reached": int(sum(reached)), "n_range": len(reached),
        "no_volume": sum(1 for r in rows if not r["volume"]),
    }
