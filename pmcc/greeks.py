"""
Black-Scholes-Merton, vectorised: implied vol from a mid, and delta from that.

Why compute delta here instead of using LSEG's DELTA field
-----------------------------------------------------------
Both legs of the PMCC are picked by delta, so delta is a decision input and
has to exist on every session the book might decide on. LSEG's DELTA does
not: on the Feb-2022 and Jan-2023 AAPL calls it is blank for the first ten
sessions of 2022 (24 of 34 rows filled). A rule that cannot see its own
input on day one is not mechanical. So delta is recomputed from things that
are always there — the closing mid, the stock close, the T-bill yield and
the trailing dividend — and LSEG's field is kept only as a cross-check
(build.py reports the agreement).

Conventions
-----------
T   calendar days to expiry / 365
r   3-month T-bill yield (US3MT=RR), as a decimal, simple -> continuous
q   trailing-twelve-month dividends with ex-date <= today, over spot

These are European formulas on American contracts. For a call on a stock
yielding under 1% the early-exercise premium is small except deep in the
money on the eve of an ex-date, which book.py handles as an explicit event
rather than through the model.
"""

from __future__ import annotations

import numpy as np
from scipy.special import ndtr


def _d1(S, K, T, r, q, v):
    return (np.log(S / K) + (r - q + 0.5 * v * v) * T) / (v * np.sqrt(T))


def call_price(S, K, T, r, q, v):
    S, K, T, r, q, v = np.broadcast_arrays(*map(np.asarray, (S, K, T, r, q, v)))
    d1 = _d1(S, K, T, r, q, v)
    d2 = d1 - v * np.sqrt(T)
    return S * np.exp(-q * T) * ndtr(d1) - K * np.exp(-r * T) * ndtr(d2)


def call_delta(S, K, T, r, q, v):
    return np.exp(-q * T) * ndtr(_d1(S, K, T, r, q, v))


def implied_vol(price, S, K, T, r, q, lo=0.01, hi=4.0, iters=60) -> np.ndarray:
    """
    Bisection, all rows at once. NaN where the mid sits outside the no-
    arbitrage band [max(0, Se^-qT - Ke^-rT), Se^-qT] — which on daily
    closes happens mostly to deep in-the-money calls whose mid is a cent
    under parity. Those rows get no delta and are not eligible to be picked;
    they are never near 0.30 or 0.80 anyway.
    """
    price, S, K, T, r, q = np.broadcast_arrays(
        *[np.asarray(a, dtype=float) for a in (price, S, K, T, r, q)])
    lower = np.maximum(0.0, S * np.exp(-q * T) - K * np.exp(-r * T))
    upper = S * np.exp(-q * T)
    ok = np.isfinite(price) & (T > 0) & (price > lower + 1e-6) & (price < upper)
    a = np.full(price.shape, lo)
    b = np.full(price.shape, hi)
    for _ in range(iters):
        m = 0.5 * (a + b)
        high = call_price(S, K, T, r, q, m) > price
        b = np.where(high, m, b)
        a = np.where(high, a, m)
    out = 0.5 * (a + b)
    # pinned at a bracket edge means no solution inside it
    pinned = (out <= lo * 1.001) | (out >= hi * 0.999)
    return np.where(ok & ~pinned, out, np.nan)
