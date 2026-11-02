"""
Black-Scholes-Merton for both rights: implied vol from a mid, delta from that.

The call side is 1.3's (pmcc/greeks.py); the put side is parity on top of it.
Same reason as 1.3 for computing delta here rather than reading LSEG's DELTA
field: both legs of the wheel are picked by delta, so delta has to exist on
every session the book might decide on, and LSEG's field has holes.

Conventions are 1.3's: T = calendar days / 365, r = 3-month T-bill yield,
q = trailing-twelve-month dividends over spot. European formulas on American
contracts — negligible for the out-of-the-money options the wheel sells; the
early-exercise cases are handled as explicit events in book.py.
"""

from __future__ import annotations

import numpy as np

from pmcc.greeks import call_delta, call_price


def put_price(S, K, T, r, q, v):
    S, K, T, r, q, v = np.broadcast_arrays(*map(np.asarray, (S, K, T, r, q, v)))
    return call_price(S, K, T, r, q, v) - S * np.exp(-q * T) + K * np.exp(-r * T)


def put_delta(S, K, T, r, q, v):
    return call_delta(S, K, T, r, q, v) - np.exp(-q * np.asarray(T))


def delta(S, K, T, r, q, v, is_call):
    return np.where(is_call, call_delta(S, K, T, r, q, v), put_delta(S, K, T, r, q, v))


def implied_vol(price, S, K, T, r, q, is_call, lo=0.01, hi=4.0, iters=60) -> np.ndarray:
    """
    Bisection, all rows at once, calls and puts together. NaN where the mid
    sits outside the European no-arbitrage band or the solution pins to a
    bracket edge — in practice deep in-the-money contracts, which are never
    near the deltas the wheel sells.
    """
    price, S, K, T, r, q = np.broadcast_arrays(
        *[np.asarray(a, dtype=float) for a in (price, S, K, T, r, q)])
    is_call = np.broadcast_to(np.asarray(is_call, dtype=bool), price.shape)
    fs, fk = S * np.exp(-q * T), K * np.exp(-r * T)
    lower = np.where(is_call, np.maximum(0.0, fs - fk), np.maximum(0.0, fk - fs))
    upper = np.where(is_call, fs, fk)
    ok = np.isfinite(price) & (T > 0) & (price > lower + 1e-6) & (price < upper)
    a = np.full(price.shape, lo)
    b = np.full(price.shape, hi)
    for _ in range(iters):
        m = 0.5 * (a + b)
        c = call_price(S, K, T, r, q, m)
        model = np.where(is_call, c, c - fs + fk)
        high = model > price
        b = np.where(high, m, b)
        a = np.where(high, a, m)
    out = 0.5 * (a + b)
    pinned = (out <= lo * 1.001) | (out >= hi * 0.999)
    return np.where(ok & ~pinned, out, np.nan)
